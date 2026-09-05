import asyncio
import base64
import hashlib
import json
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app.agent.model import ModelStreamEvent
from app.agent.tools.base import ToolExecutionContext
from app.agent.tools.files import ReadFileArguments, _read_file_sync
from app.main import collect_files
from app.object_store import LocalObjectStore, ObjectStoreError, S3ObjectStore
from app.persistence.models import AgentRun, FileResource
from app.persistence.scope import LOCAL_SCOPE
from app.settings import Settings
from tests.test_lifecycle import post, start, wait_run


def pdf_bytes():
    content = b"BT /F1 12 Tf 50 750 Td (CornAgent private document evidence.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets)
    return result + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def upload(client, payload, mime="application/pdf", filename="document.pdf"):
    response = client.post(
        "/api/v1/files",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "purpose": "session_attachment",
            "filename": filename,
            "mime_type": mime,
            "size_bytes": len(payload),
        },
    )
    assert response.status_code == 200, response.text
    file_id = response.json()["id"]
    response = client.put(
        f"/api/v1/files/{file_id}/content", content=payload, headers={"Content-Type": mime}
    )
    assert response.status_code == 200, response.text
    return file_id


def test_read_file_roundtrip_keeps_text_out_of_checkpoint_and_sse(client_factory):
    class ReadModel:
        def __init__(self):
            self.file_id = ""
            self.requests = []

        async def stream(self, messages):
            self.requests.append(messages)
            if messages[-1]["role"] != "tool":
                yield ModelStreamEvent(
                    kind="tool_calls",
                    tool_calls=[
                        {
                            "id": "read-1",
                            "name": "read_file",
                            "arguments": json.dumps(
                                {"file_id": self.file_id, "cursor": "", "max_chars": 1000}
                            ),
                        }
                    ],
                )
            else:
                yield ModelStreamEvent(kind="content", content="Read complete.")

    model = ReadModel()
    with client_factory(model) as client:
        file_id = upload(client, pdf_bytes())
        model.file_id = file_id
        extracted = client.post(f"/api/v1/files/{file_id}/extract", json={})
        assert extracted.status_code == 200, extracted.text
        created = post(
            client, "/sessions", {"content": "Read the file", "attachments": [{"file_id": file_id}]}
        ).json()
        session_id, run_id = created["session"]["id"], created["run"]["id"]
        detail = wait_run(client, session_id)
        assert "CornAgent private document evidence." in model.requests[-1][-1]["content"]
        assert "CornAgent private document evidence." not in json.dumps(detail)
        with client.app.state.database.session_factory() as db:
            run = db.get(AgentRun, run_id)
            checkpoint = json.dumps(run.checkpoint)
            assert "CornAgent private document evidence." not in checkpoint
            assert "read_file" in checkpoint
            item = db.get(FileResource, file_id)
            assert item.state == "ready"
        response = client.get(f"/api/v1/agent/runs/{run_id}/stream")
        assert "CornAgent private document evidence." not in response.text
        assert client.delete(f"/api/v1/files/{file_id}").status_code == 409
        foreign_session = start(client)["session"]["id"]
        context = ToolExecutionContext(
            tenant_id=LOCAL_SCOPE.tenant_id,
            owner_membership_id=LOCAL_SCOPE.membership_id,
            session_id=foreign_session,
        )
        denied = _read_file_sync(
            ReadFileArguments(file_id=file_id), context, client.app.state.database.session_factory
        )
        assert denied["error_code"] == "file_not_found"
        assert client.delete(f"/api/v1/agent/sessions/{session_id}").status_code == 200
        assert client.get(f"/api/v1/files/{file_id}/content").status_code == 404
        collect_files(client.app.state.database, client.app.state.file_store)
        with client.app.state.database.session_factory() as db:
            assert db.get(FileResource, file_id).state == "deleted"
        with pytest.raises(ObjectStoreError):
            asyncio.run(client.app.state.file_store.get_bytes(file_id))


def test_image_hydration_validates_immutable_content(client_factory):
    from tests.test_runtime import FinalAgentModel

    model = FinalAgentModel()
    data = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(data, format="PNG")
    with client_factory(model) as client:
        file_id = upload(client, data.getvalue(), "image/png", "image.png")
        assert client.get(f"/api/v1/files/{file_id}/content").content == data.getvalue()
        created = post(
            client, "/sessions", {"content": "Describe", "attachments": [{"file_id": file_id}]}
        ).json()
        wait_run(client, created["session"]["id"])
        assert any(part.get("type") == "image_url" for part in model.requests[0][-1]["content"])
        with client.app.state.database.session_factory() as db:
            assert "base64" not in json.dumps(db.get(AgentRun, created["run"]["id"]).checkpoint)
        assert (
            client.put(f"/api/v1/files/{file_id}/content", content=data.getvalue()).status_code
            == 409
        )
        response = client.post(
            "/api/v1/files",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "purpose": "session_attachment",
                "filename": "fake.png",
                "mime_type": "image/png",
                "size_bytes": 4,
            },
        )
        assert (
            client.put(
                f"/api/v1/files/{response.json()['id']}/content", content=b"fake"
            ).status_code
            == 422
        )


def test_local_blob_store_is_bounded_immutable_and_rejects_paths(tmp_path):
    store = LocalObjectStore(tmp_path, max_bytes=4)
    key = str(uuid4())
    store.put(key, b"data")
    store.put(key, b"data")
    assert asyncio.run(store.get_bytes(key)) == b"data"
    with pytest.raises(ObjectStoreError):
        store.put(key, b"evil")
    with pytest.raises(ObjectStoreError):
        store.put(str(uuid4()), b"large")
    with pytest.raises(ObjectStoreError):
        asyncio.run(store.get_bytes("../secret"))
    store.delete(key)
    store.delete(key)


def test_upload_metadata_retries_are_idempotent(client_factory):
    with client_factory() as client:
        headers = {"Idempotency-Key": str(uuid4())}
        payload = {
            "purpose": "session_attachment",
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 100,
        }
        first = client.post("/api/v1/files", json=payload, headers=headers)
        second = client.post("/api/v1/files", json=payload, headers=headers)
        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert (
            client.post(
                "/api/v1/files", json={**payload, "size_bytes": 101}, headers=headers
            ).status_code
            == 409
        )
        assert client.get("/healthz", headers={"Host": "rebinding.example"}).status_code == 400


def test_pdf_extraction_failure_is_durable_and_retryable(client_factory):
    with client_factory() as client:
        file_id = upload(client, b"%PDF-1.4\ninvalid content")
        for _ in range(2):
            response = client.post(f"/api/v1/files/{file_id}/extract", json={})
            assert response.status_code == 422
            with client.app.state.database.session_factory() as db:
                item = db.get(FileResource, file_id)
                assert item.extraction_status == "failed"
                assert item.extraction_error_code == "session_file_extraction_failed"


def test_s3_adapter_uses_conditional_put_checksum_and_private_keys(monkeypatch):
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    store = S3ObjectStore(Settings(_env_file=None, s3_bucket="test-bucket"))
    key, payload = str(uuid4()), b"data"
    params = {
        "Bucket": "test-bucket",
        "Key": f"cornagent/{key}",
        "Body": payload,
        "ContentType": "application/octet-stream",
        "IfNoneMatch": "*",
        "ChecksumSHA256": base64.b64encode(hashlib.sha256(payload).digest()).decode(),
    }
    with Stubber(store.client) as stub:
        stub.add_response("put_object", {}, params)
        stub.add_response(
            "get_object",
            {"ContentLength": 4, "Body": StreamingBody(BytesIO(payload), 4)},
            {"Bucket": "test-bucket", "Key": f"cornagent/{key}"},
        )
        stub.add_response("delete_object", {}, {"Bucket": "test-bucket", "Key": f"cornagent/{key}"})
        store.put(key, payload)
        assert asyncio.run(store.get_bytes(key)) == payload
        store.delete(key)
        stub.assert_no_pending_responses()


def test_edit_preserves_attachments_and_both_conversation_branches_after_restart(client_factory):
    with client_factory() as client:
        file_id = upload(client, pdf_bytes())
        assert client.post(f"/api/v1/files/{file_id}/extract", json={}).status_code == 200
        created = post(
            client, "/sessions", {"content": "original root", "attachments": [{"file_id": file_id}]}
        ).json()
        session_id = created["session"]["id"]
        original = wait_run(client, session_id)
        root = original["messages"][0]
        assert (
            post(
                client, f"/sessions/{session_id}/messages", {"content": "original follow-up"}
            ).status_code
            == 200
        )
        original = wait_run(client, session_id)
        original_ids = [item["id"] for item in original["messages"]]
        key = str(uuid4())
        response = post(client, f"/messages/{root['id']}/edit", {"content": "edited root"}, key)
        assert response.status_code == 200, response.text
        edited = wait_run(client, session_id)
        new_root = next(
            item for item in edited["messages"] if item["id"] == response.json()["user_message_id"]
        )
        assert new_root["id"] != root["id"]
        assert new_root["previous_version_id"] == root["id"]
        assert new_root["version_count"] == 2
        assert new_root["attachments"][0]["file_id"] == file_id
        assert (
            post(client, f"/messages/{root['id']}/edit", {"content": "edited root"}, key).json()[
                "id"
            ]
            == response.json()["id"]
        )
        assert (
            post(
                client, f"/sessions/{session_id}/messages", {"content": "edited follow-up"}
            ).status_code
            == 200
        )
        edited = wait_run(client, session_id)
        edited_ids = [item["id"] for item in edited["messages"] if item["id"] not in original_ids]
        switched = post(
            client, f"/sessions/{session_id}/active-version", {"message_id": root["id"]}
        ).json()
        assert [item["id"] for item in switched["messages"]] == original_ids
        assert switched["messages"][0]["next_version_id"] == new_root["id"]

    with client_factory() as client:
        restored = client.get(f"/api/v1/agent/sessions/{session_id}").json()
        assert [item["id"] for item in restored["messages"]] == original_ids
        switched = post(
            client, f"/sessions/{session_id}/active-version", {"message_id": new_root["id"]}
        ).json()
        assert switched["active_leaf_message_id"] == edited_ids[-1]
        by_id = {item["id"]: item for item in switched["messages"]}
        branch = []
        current = switched["active_leaf_message_id"]
        while current is not None:
            branch.append(current)
            current = by_id[current]["parent_message_id"]
        assert branch[::-1] == edited_ids
        assert by_id[new_root["id"]]["attachments"][0]["file_id"] == file_id
        assert client.get(f"/api/v1/files/{file_id}/content").status_code == 200
