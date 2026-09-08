"""Bounded parent-side client for the isolated File parser."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

from app.persistence.errors import DomainError


@dataclass(frozen=True, slots=True)
class PdfExtraction:
    markdown: str
    parser: str
    parser_version: str
    page_count: int
    truncated: bool


def extract_pdf(
    payload: bytes,
    *,
    max_pages: int,
    max_chars: int,
    timeout_seconds: float,
) -> PdfExtraction:
    result = parse_pdf(
        payload, max_pages=max_pages, max_chars=max_chars, timeout_seconds=timeout_seconds
    )
    return PdfExtraction(**{key: result[key] for key in PdfExtraction.__dataclass_fields__})


def parse_pdf(
    payload: bytes,
    *,
    max_pages: int,
    max_chars: int,
    timeout_seconds: float,
    page_numbers: list[int] | None = None,
) -> dict:
    command = [sys.executable, "-m", "app.file_parser", str(max_pages), str(max_chars)]
    if page_numbers is not None:
        command.append(json.dumps(page_numbers))
    try:
        completed = subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise DomainError(
            "session_file_extraction_timeout",
            "PDF extraction timed out.",
            status_code=422,
        ) from exc
    if completed.returncode != 0:
        raise DomainError(
            "session_file_extraction_failed",
            "PDF extraction failed.",
            status_code=422,
        )
    try:
        result = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DomainError(
            "session_file_extraction_failed",
            "PDF extraction failed.",
            status_code=422,
        ) from exc
    if result.get("ok") is not True:
        code = str(result.get("error_code") or "session_file_extraction_failed")
        messages = {
            "session_file_pdf_encrypted": "Encrypted PDF files are not supported.",
            "session_file_pdf_pages_exceeded": "The PDF has too many pages.",
        }
        raise DomainError(code, messages.get(code, "PDF extraction failed."), status_code=422)
    return result
