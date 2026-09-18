from io import BytesIO
from zipfile import ZipFile

import pytest

from app.document_formats import DOCX, TEXT_TYPES, document_text
from app.file_extraction import extract_document
from tests.test_files import upload
from tests.test_lifecycle import post, wait_run


def docx_bytes(xml=None):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            xml
            or """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第一段</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格内容</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>""",
        )
    return stream.getvalue()


@pytest.mark.parametrize("mime", [*TEXT_TYPES, DOCX])
def test_document_upload_extract_attach_download_and_restore(client_factory, mime):
    payload = docx_bytes() if mime == DOCX else "标题\n甲,乙\n一\t二".encode()
    with client_factory() as client:
        file_id = upload(client, payload, mime, "材料.docx" if mime == DOCX else "材料.txt")
        response = client.post(f"/api/v1/files/{file_id}/extract")
        assert response.status_code == 200, response.text
        assert response.json()["extraction_status"] == "ready"
        created = post(client, "/sessions", {"attachments": [{"file_id": file_id}]}).json()
        detail = wait_run(client, created["session"]["id"])
        assert detail["messages"][0]["attachments"][0]["media_kind"] == "document"
        download = client.get(f"/api/v1/files/{file_id}/content?download=true")
        assert download.content == payload
        assert download.headers["content-disposition"].startswith("attachment;")
        assert (
            client.get(f"/api/v1/files/{file_id}/content")
            .headers["content-disposition"]
            .startswith("inline;")
        )
        assert "标题" not in str(detail)
        assert "表格内容" not in str(detail)


def test_docx_text_tables_limits_and_external_entities():
    assert document_text(docx_bytes(), DOCX) == "第一段\n表格内容"
    extracted = extract_document(
        docx_bytes(), mime_type=DOCX, max_pages=50, max_chars=3, timeout_seconds=10
    )
    assert extracted.markdown == "第一段" and extracted.truncated
    with pytest.raises(ValueError):
        document_text(
            docx_bytes('<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x>&x;</x>'), DOCX
        )
    with pytest.raises(ValueError):
        document_text(b"not a zip", DOCX)
    with pytest.raises(ValueError):
        document_text(b"hello\x00world", "text/plain")
    assert document_text("中文".encode("utf-16"), "text/plain") == "中文"
