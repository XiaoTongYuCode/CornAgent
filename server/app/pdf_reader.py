"""Read authorized PDF pages under the same extraction budget as uploads."""

import asyncio
import hashlib

from starlette.concurrency import run_in_threadpool

from app.file_extraction import parse_pdf
from app.persistence.errors import DomainError


class PdfReader:
    def __init__(self, settings, store, admission=None):
        self.settings = settings
        self.store = store
        self.admission = admission or asyncio.Semaphore(1)

    async def read_target(self, target, page_numbers):
        if self.store is None:
            raise DomainError(
                "file_store_unavailable", "File storage is unavailable.", status_code=503
            )
        async with self.admission:
            raw = await self.store.get_bytes(target["storage_key"])
            if (
                len(raw) != target["size_bytes"]
                or hashlib.sha256(raw).hexdigest() != target["sha256"]
            ):
                raise DomainError(
                    "session_file_integrity_failed", "PDF integrity check failed.", status_code=409
                )
            return await run_in_threadpool(
                parse_pdf,
                raw,
                page_numbers=page_numbers,
                max_pages=self.settings.agent_file_pdf_max_pages,
                max_chars=self.settings.agent_file_extracted_max_chars,
                timeout_seconds=self.settings.agent_file_extraction_timeout_seconds,
            )
