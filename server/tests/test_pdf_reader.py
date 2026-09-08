"""Real synthetic PDFs exercise page text, embedded images and bounded reads."""

import asyncio
import base64
import hashlib
from io import BytesIO

import pypdfium2 as pdfium
import pytest
from PIL import Image

from app.agent.model import ModelStreamEvent
from app.file_extraction import parse_pdf
from app.pdf_reader import PdfReader
from app.persistence.errors import DomainError
from app.persistence.models import AgentRun
from app.settings import Settings
from tests.test_files import pdf_bytes, upload
from tests.test_lifecycle import post, wait_run


def image_pdf():
    stream = BytesIO()
    Image.new("RGB", (40, 60), "red").save(stream, format="PDF")
    return stream.getvalue()


def combine(*documents):
    with pdfium.PdfDocument.new() as output:
        for raw in documents:
            with pdfium.PdfDocument(raw) as doc:
                output.import_pages(doc)
        stream = BytesIO()
        output.save(stream)
        return stream.getvalue()


def parse(raw, pages, max_chars=200000):
    return parse_pdf(raw, page_numbers=pages, max_pages=50, max_chars=max_chars, timeout_seconds=20)


def test_selected_pages_contain_markdown_and_embedded_jpeg():
    raw = combine(pdf_bytes(), image_pdf())
    text = parse(raw, [1])["pages"][0]
    assert "CornAgent private document evidence." in text["markdown"]
    assert text["images"] == []
    scan = parse(raw, [2])["pages"][0]
    assert scan["markdown"] == "" and len(scan["images"]) == 1
    image = Image.open(BytesIO(base64.b64decode(scan["images"][0]["data_url"].split(",", 1)[1])))
    assert image.format == "JPEG" and image.size == (40, 60)
    assert [p["page_number"] for p in parse(raw, [2, 1])["pages"]] == [1, 2]


@pytest.mark.parametrize("pages", [[0], [3], [1, 1], [-1], [True]])
def test_invalid_pages_fail(pages):
    with pytest.raises(DomainError) as error:
        parse(combine(pdf_bytes(), image_pdf()), pages)
    assert error.value.code == "pdf_page_out_of_range"


def test_corrupt_and_limits():
    with pytest.raises(DomainError):
        parse(b"%PDF broken", [1])
    with pytest.raises(DomainError) as error:
        parse(pdf_bytes(), [1], max_chars=3)
    assert error.value.code == "pdf_text_limit_exceeded"
    with pytest.raises(DomainError) as error:
        parse(combine(*([image_pdf()] * 17)), list(range(1, 18)))
    assert error.value.code == "pdf_images_too_large"


def test_reader_checks_original_bytes_without_model_credentials():
    raw = image_pdf()

    class Store:
        async def get_bytes(self, key):
            return raw

    target = {
        "storage_key": "pdf",
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    reader = PdfReader(Settings(_env_file=None, agent_api_key=None), Store())
    assert asyncio.run(reader.read_target(target, [1]))["pages"][0]["images"]
    target["sha256"] = "0" * 64
    with pytest.raises(DomainError) as error:
        asyncio.run(reader.read_target(target, [1]))
    assert error.value.code == "session_file_integrity_failed"


def test_pdf_images_are_request_only_and_rehydrate_after_restart(client_factory):
    class Model:
        def __init__(self):
            self.file_id = ""
            self.requests = []

        async def stream(self, messages):
            self.requests.append(messages)
            if len(self.requests) == 1:
                yield ModelStreamEvent(
                    kind="tool_calls",
                    tool_calls=[
                        {
                            "id": "pdf-1",
                            "name": "read_file",
                            "arguments": '{"file_id":"' + self.file_id + '","page_numbers":[1]}',
                        }
                    ],
                )
            else:
                images = [
                    p
                    for m in messages
                    if isinstance(m.get("content"), list)
                    for p in m["content"]
                    if p.get("type") == "image_url"
                ]
                assert len(images) == 1
                assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
                assert (
                    next(m for m in messages if m.get("name") == "read_file")["tool_call_id"]
                    == "pdf-1"
                )
                yield ModelStreamEvent(kind="content", content="PDF image received.")

    model = Model()
    with client_factory(model=model) as client:
        model.file_id = upload(client, image_pdf())
        extracted = client.post(f"/api/v1/files/{model.file_id}/extract", json={})
        assert extracted.status_code == 200, extracted.text
        response = post(
            client,
            "/sessions",
            {"content": "Read page one", "attachments": [{"file_id": model.file_id}]},
        )
        assert response.status_code == 200, response.text
        created = response.json()
        session_id = created["session"]["id"]
        detail = wait_run(client, session_id)
        assert "base64" not in str(detail)
        with client.app.state.database.session_factory() as db:
            run = db.get(AgentRun, created["run"]["id"])
            assert "base64" not in str(run.checkpoint)
            assert "private_tool_result_ref" in str(run.checkpoint)
        stream = client.get(f"/api/v1/agent/runs/{created['run']['id']}/stream")
        assert stream.status_code == 200 and "base64" not in stream.text
    with client_factory(model=model) as client:
        followup = post(client, f"/sessions/{session_id}/messages", {"content": "Describe again"})
        assert followup.status_code == 200, followup.text
        wait_run(client, session_id)
        assert len(model.requests) == 3
