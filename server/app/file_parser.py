"""Isolated, stream-only PDF-to-Markdown subprocess entrypoint."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from contextlib import closing
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


def selected_pages(payload, numbers, max_pages, max_chars):
    import pypdfium2 as pdfium
    from markitdown import MarkItDown, StreamInfo
    from markitdown.converters import PdfConverter
    from PIL import Image

    try:
        pdf = pdfium.PdfDocument(payload)
    except pdfium.PdfiumError as exc:
        return {
            "ok": False,
            "error_code": "session_file_pdf_encrypted"
            if exc.err_code == pdfium.raw.FPDF_ERR_PASSWORD
            else "session_file_extraction_failed",
        }
    with pdf:
        if not len(pdf) or len(pdf) > max_pages:
            return {"ok": False, "error_code": "session_file_pdf_pages_exceeded"}
        if len(numbers) != len(set(numbers)) or any(
            type(n) is not int or n < 1 or n > len(pdf) for n in numbers
        ):
            return {"ok": False, "error_code": "pdf_page_out_of_range"}
        converter = MarkItDown(enable_builtins=False, enable_plugins=False)
        converter.register_converter(PdfConverter())
        pages = []
        total_chars = total_bytes = total_images = 0
        for number in sorted(numbers):
            with pdfium.PdfDocument.new() as single:
                single.import_pages(pdf, [number - 1])
                stream = BytesIO()
                single.save(stream)
                stream.seek(0)
                markdown = converter.convert_stream(
                    stream, stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf")
                ).text_content.strip()
            total_chars += len(markdown)
            if total_chars > max_chars:
                return {"ok": False, "error_code": "pdf_text_limit_exceeded"}
            images = []
            with closing(pdf[number - 1]) as page:
                for index, embedded in enumerate(
                    page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE])
                ):
                    total_images += 1
                    width, height = embedded.get_px_size()
                    if total_images > 16 or width * height > 25_000_000:
                        return {"ok": False, "error_code": "pdf_images_too_large"}
                    bitmap = embedded.get_bitmap()
                    try:
                        source = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
                    source.thumbnail((2048, 2048))
                    with (
                        source,
                        source.convert("RGBA") as rgba,
                        Image.new("RGB", source.size, "white") as rgb,
                    ):
                        rgb.paste(rgba, mask=rgba.getchannel("A"))
                        stream = BytesIO()
                        rgb.save(stream, format="JPEG", quality=90)
                    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
                    total_bytes += len(encoded)
                    if total_bytes > 16 * 1024 * 1024:
                        return {"ok": False, "error_code": "pdf_images_too_large"}
                    images.append(
                        {
                            "name": f"page-{number}-image-{index + 1}.jpg",
                            "data_url": "data:image/jpeg;base64," + encoded,
                        }
                    )
            pages.append({"page_number": number, "markdown": markdown, "images": images})
        return {"ok": True, "page_count": len(pdf), "pages": pages}


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

        if len(sys.argv) > 3:
            _write(selected_pages(payload, json.loads(sys.argv[3]), max_pages, max_chars))
            return
        with pdfplumber.open(BytesIO(payload)) as pdf:
            if getattr(pdf.doc, "is_extractable", True) is False:
                _write({"ok": False, "error_code": "session_file_pdf_encrypted"})
                return
            page_count = len(pdf.pages)
            if not page_count or page_count > max_pages:
                _write({"ok": False, "error_code": "session_file_pdf_pages_exceeded"})
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
        # A valid image-only or blank PDF is still an uploadable attachment.
        # Empty extracted text is a successful result, not a parser failure.
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
