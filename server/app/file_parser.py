"""Isolated, stream-only PDF-to-Markdown subprocess entrypoint."""

from __future__ import annotations

import hashlib
import json
import sys
from io import BytesIO


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _apply_linux_limits() -> None:
    if not sys.platform.startswith("linux"):
        return
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))


def main() -> None:
    try:
        max_pages = int(sys.argv[1])
        max_chars = int(sys.argv[2])
    except (IndexError, ValueError):
        _write({"ok": False, "error_code": "session_file_parser_configuration_invalid"})
        return
    payload = sys.stdin.buffer.read()
    try:
        _apply_linux_limits()
        from importlib.metadata import version

        import pdfplumber
        from markitdown import MarkItDown, StreamInfo
        from markitdown.converters import PdfConverter

        with pdfplumber.open(BytesIO(payload)) as pdf:
            if getattr(pdf.doc, "is_extractable", True) is False:
                _write({"ok": False, "error_code": "session_file_pdf_encrypted"})
                return
            page_count = len(pdf.pages)
            if page_count > max_pages:
                _write(
                    {
                        "ok": False,
                        "error_code": "session_file_pdf_pages_exceeded",
                        "page_count": page_count,
                    }
                )
                return
        converter = MarkItDown(enable_builtins=False, enable_plugins=False)
        converter.register_converter(PdfConverter())
        result = converter.convert_stream(
            BytesIO(payload),
            stream_info=StreamInfo(
                mimetype="application/pdf",
                extension=".pdf",
                filename="attachment.pdf",
            ),
        )
        markdown = result.text_content.strip()
        if not markdown:
            _write({"ok": False, "error_code": "session_file_extraction_empty"})
            return
        truncated = len(markdown) > max_chars
        if truncated:
            markdown = markdown[:max_chars]
        encoded = markdown.encode("utf-8")
        _write(
            {
                "ok": True,
                "markdown": markdown,
                "page_count": page_count,
                "parser": "markitdown",
                "parser_version": version("markitdown"),
                "extracted_sha256": hashlib.sha256(encoded).hexdigest(),
                "extracted_size_bytes": len(encoded),
                "truncated": truncated,
            }
        )
    except Exception:
        _write({"ok": False, "error_code": "session_file_extraction_failed"})


if __name__ == "__main__":
    main()
