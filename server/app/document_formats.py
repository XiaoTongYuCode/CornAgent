"""Shared allowlist and bounded document validation (no network or external entities)."""

from io import BytesIO
from typing import Literal
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_TYPES = ("text/plain", "text/markdown", "text/csv", "text/tab-separated-values")
DOCUMENT_TYPES = ("application/pdf", *TEXT_TYPES, DOCX)
FileMimeType = Literal[
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]


def decode_text(payload: bytes) -> str:
    encoding = "utf-16" if payload.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = payload.decode(encoding)
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise ValueError("Binary data is not a text document")
    return text


def docx_xml(payload: bytes) -> bytes:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 2000
                or sum(i.file_size for i in entries) > 32 * 1024 * 1024
                or len({i.filename for i in entries}) != len(entries)
                or any(i.flag_bits & 1 for i in entries)
            ):
                raise ValueError("Oversized or encrypted DOCX")
            if "[Content_Types].xml" not in archive.namelist():
                raise ValueError("Invalid DOCX package")
            xml = archive.read("word/document.xml")
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper() or b"\x00" in xml:
                raise ValueError("Unsupported XML declarations")
            root = ElementTree.fromstring(xml)
            if root.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
                raise ValueError("Invalid Word document")
            return xml
    except (BadZipFile, KeyError, ElementTree.ParseError, RuntimeError) as exc:
        raise ValueError("Invalid DOCX") from exc


def document_text(payload: bytes, mime_type: str) -> str:
    if mime_type in TEXT_TYPES:
        return decode_text(payload)
    if mime_type != DOCX:
        raise ValueError("Unsupported document")
    root = ElementTree.fromstring(docx_xml(payload))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines = []
    for paragraph in root.iter(ns + "p"):
        lines.append(
            "".join(
                element.text or ""
                if element.tag == ns + "t"
                else "\t"
                if element.tag == ns + "tab"
                else "\n"
                if element.tag in {ns + "br", ns + "cr"}
                else ""
                for element in paragraph.iter()
            )
        )
    return "\n".join(lines)
