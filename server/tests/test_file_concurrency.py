import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx

from app.file_extraction import extract_pdf
from app.persistence.models import FileResource
from tests.test_files import pdf_bytes, upload


def pending_file(client):
    response = client.post(
        "/api/v1/files",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "purpose": "session_attachment",
            "filename": "test.pdf",
            "mime_type": "application/pdf",
            "size_bytes": len(pdf_bytes()),
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_slow_body_releases_connection_and_does_not_block_fast_upload(client_factory, settings):
    settings.file_upload_body_timeout_seconds = 0.3
    settings.file_admission_timeout_seconds = 0.05
    with client_factory() as client:
        slow_id, fast_id = pending_file(client), pending_file(client)

        async def exercise():
            received = asyncio.Event()

            async def slow_body():
                yield b"%PDF-"
                received.set()
                await asyncio.sleep(5)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
            ) as http:
                task = asyncio.create_task(
                    http.put(f"/api/v1/files/{slow_id}/content", content=slow_body())
                )
                await asyncio.wait_for(received.wait(), 1)
                fast = await http.put(f"/api/v1/files/{fast_id}/content", content=pdf_bytes())
                assert fast.status_code == 200, fast.text
                assert (await http.delete(f"/api/v1/files/{slow_id}")).status_code == 200
                response = await asyncio.wait_for(task, 1)
                assert response.status_code == 408
                assert response.json()["error"]["code"] == "file_upload_timeout"
                # A timed-out request released admission capacity.
                assert (
                    await http.put(f"/api/v1/files/{fast_id}/content", content=pdf_bytes())
                ).status_code == 200

        client.portal.call(exercise)


def test_upload_admission_is_bounded_and_cancellation_releases_slot(client_factory, settings):
    settings.file_body_max_concurrency = 1
    settings.file_admission_timeout_seconds = 0.05
    with client_factory() as client:
        first, second = pending_file(client), pending_file(client)

        async def exercise():
            received = asyncio.Event()

            async def body():
                yield b"%PDF-"
                received.set()
                await asyncio.sleep(5)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
            ) as http:
                task = asyncio.create_task(
                    http.put(f"/api/v1/files/{first}/content", content=body())
                )
                await asyncio.wait_for(received.wait(), 1)
                try:
                    response = await http.put(
                        f"/api/v1/files/{second}/content", content=pdf_bytes()
                    )
                    assert response.status_code == 503
                    assert response.json()["error"]["code"] == "file_operations_busy"
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                assert (
                    await http.put(f"/api/v1/files/{second}/content", content=pdf_bytes())
                ).status_code == 200

        client.portal.call(exercise)


def test_pdf_parser_releases_database_and_rechecks_deletion(client_factory, settings, monkeypatch):
    settings.file_admission_timeout_seconds = 0.05
    entered, release = threading.Event(), threading.Event()
    result = extract_pdf(pdf_bytes(), max_pages=50, max_chars=1000, timeout_seconds=5)
    calls = []

    def slow_parser(*_args, **_kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr("app.api.routes.files.extract_pdf", slow_parser)
    with client_factory() as client, ThreadPoolExecutor() as executor:
        first, second = upload(client, pdf_bytes()), upload(client, pdf_bytes())
        future = executor.submit(client.post, f"/api/v1/files/{first}/extract")
        try:
            assert entered.wait(2)
            # With SQLite BEGIN IMMEDIATE this also proves parsing has no open transaction.
            assert (
                executor.submit(client.delete, f"/api/v1/files/{first}")
                .result(timeout=1)
                .status_code
                == 200
            )
            queued = client.post(f"/api/v1/files/{second}/extract")
            assert queued.status_code == 503
            assert len(calls) == 1
        finally:
            release.set()
        assert future.result(timeout=2).status_code == 404
        assert client.post(f"/api/v1/files/{second}/extract").status_code == 200
        with client.app.state.database.session_factory() as db:
            assert db.get(FileResource, first).state == "delete_pending"
            assert db.get(FileResource, first).extracted_markdown is None
            assert db.get(FileResource, second).extraction_status == "ready"
