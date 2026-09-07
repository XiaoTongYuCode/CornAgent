"""Session attachment upload, extraction and lifecycle API."""

import asyncio
import hashlib
import warnings
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Request
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentIdentity, Db
from app.api.routes._common import IdempotencyKey, require_idempotency_key
from app.file_extraction import extract_pdf
from app.persistence.errors import DomainError
from app.persistence.models import FileResource, utcnow

router = APIRouter(prefix="/files")


async def _run_file_db[T](request: Request, operation: Callable[[Session], T]) -> T:
    def execute() -> T:
        with request.app.state.database.session_factory() as db:
            return operation(db)

    return await run_in_threadpool(execute)


@asynccontextmanager
async def _file_admission(request: Request, admission: asyncio.Semaphore) -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(request.app.state.settings.file_admission_timeout_seconds):
            await admission.acquire()
    except TimeoutError as exc:
        raise DomainError(
            "file_operations_busy", "File operations are busy. Please retry.", status_code=503
        ) from exc
    try:
        yield
    finally:
        admission.release()


class FileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["session_attachment"]
    filename: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "application/pdf"]
    size_bytes: int = Field(gt=0)


def file_out(item: FileResource):
    return {
        key: getattr(item, key)
        for key in (
            "id",
            "filename",
            "mime_type",
            "size_bytes",
            "state",
            "inspection_status",
            "extraction_status",
        )
    }


def owned_file(db, identity, file_id: str, *, lock: bool = False):
    from sqlalchemy import select

    query = select(FileResource).where(
        FileResource.id == file_id,
        FileResource.tenant_id == identity.tenant_id,
        FileResource.uploaded_by == identity.user_id,
    )
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None or item.state in {"deleted", "delete_pending"}:
        raise DomainError("file_not_found", "File not found.", status_code=404)
    return item


@router.post("")
def create_file(
    payload: FileCreate,
    request: Request,
    identity: CurrentIdentity,
    db: Db,
    idempotency_key: IdempotencyKey = None,
):
    settings = request.app.state.settings
    if not settings.agent_file_input_enabled:
        raise DomainError(
            "session_attachment_input_unavailable", "File input is disabled.", status_code=503
        )
    limit = (
        settings.agent_file_pdf_max_bytes
        if payload.mime_type == "application/pdf"
        else settings.agent_file_image_max_bytes
    )
    if payload.size_bytes > limit:
        raise DomainError(
            "file_too_large", "File size exceeds the configured limit.", status_code=413
        )
    key = require_idempotency_key(idempotency_key)
    file_id = str(
        uuid5(NAMESPACE_URL, f"cornagent:file:{identity.tenant_id}:{identity.user_id}:{key}")
    )

    def replay(item):
        if any(getattr(item, name) != value for name, value in payload.model_dump().items()):
            raise DomainError(
                "file_request_conflict", "This key belongs to another upload.", status_code=409
            )
        if item.state in {"delete_pending", "deleted"}:
            raise DomainError("file_retired", "This upload was already deleted.", status_code=409)
        return file_out(item)

    existing = db.get(FileResource, file_id)
    if existing is not None:
        return replay(existing)
    item = FileResource(
        id=file_id,
        tenant_id=identity.tenant_id,
        uploaded_by=identity.user_id,
        storage_key=file_id,
        **payload.model_dump(),
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(FileResource, file_id)
        if existing is None:
            raise
        return replay(existing)
    return file_out(item)


@router.put("/{file_id}/content")
async def upload_content(file_id: str, request: Request, identity: CurrentIdentity):
    def authorize(db):
        item = owned_file(db, identity, file_id)
        if item.state not in {"pending", "stored"}:
            raise DomainError(
                "file_not_writable", "A claimed file cannot be changed.", status_code=409
            )
        settings = request.app.state.settings
        return (
            settings.agent_file_pdf_max_bytes
            if item.mime_type == "application/pdf"
            else settings.agent_file_image_max_bytes
        )

    # Slow senders occupy only a bounded body slot, never a database connection
    # or a persistence slot. Keep the body slot until its buffer is released.
    async with _file_admission(request, request.app.state.file_body_admission):
        limit = await _run_file_db(request, authorize)
        payload = await _read_content(request, limit)
        async with _file_admission(request, request.app.state.file_upload_admission):
            return await _run_file_db(
                request, lambda db: _store_upload(file_id, payload, request, identity, db)
            )


async def _read_content(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise DomainError(
            "file_too_large", "File size exceeds the configured limit.", status_code=413
        )
    data = bytearray()
    try:
        async with asyncio.timeout(request.app.state.settings.file_upload_body_timeout_seconds):
            async for chunk in request.stream():
                if len(data) + len(chunk) > limit:
                    raise DomainError(
                        "file_too_large", "File size exceeds the configured limit.", status_code=413
                    )
                data.extend(chunk)
    except TimeoutError as exc:
        raise DomainError(
            "file_upload_timeout", "The upload body was not received in time.", status_code=408
        ) from exc
    return bytes(data)


def _store_upload(file_id, payload, request, identity, db):
    item = owned_file(db, identity, file_id, lock=True)
    settings = request.app.state.settings
    if item.state not in {"pending", "stored"}:
        raise DomainError("file_not_writable", "A claimed file cannot be changed.", status_code=409)
    digest = hashlib.sha256(payload).hexdigest()
    if item.state == "stored":
        if item.sha256 != digest:
            raise DomainError(
                "file_content_conflict",
                "Upload retries must contain identical bytes.",
                status_code=409,
            )
        return file_out(item)
    if not payload or len(payload) != item.size_bytes:
        raise DomainError(
            "file_size_mismatch", "The uploaded size does not match.", status_code=422
        )
    try:
        if item.mime_type == "application/pdf":
            if not payload.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF signature")
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(payload)) as image:
                    if Image.MIME.get(image.format) != item.mime_type or getattr(
                        image, "is_animated", False
                    ):
                        raise ValueError("Unsupported image")
                    if (
                        max(image.size) > settings.agent_file_image_max_side
                        or image.width * image.height > settings.agent_file_image_max_pixels
                    ):
                        raise ValueError("Image dimensions exceeded")
                    image.verify()
                with Image.open(BytesIO(payload)) as image:
                    image.load()
    except (
        ValueError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise DomainError(
            "file_format_invalid", "The file is damaged or unsupported.", status_code=422
        ) from exc
    request.app.state.file_store.put(item.storage_key, payload)
    item.sha256 = digest
    item.inspection_status = "validated"
    item.state = "stored"
    db.commit()
    return file_out(item)


@router.post("/{file_id}/extract")
async def extract_file(file_id: str, request: Request, identity: CurrentIdentity):
    def authorize(db):
        item = owned_file(db, identity, file_id)
        if item.mime_type != "application/pdf" or item.state not in {"stored", "ready"}:
            raise DomainError(
                "file_not_extractable", "Upload a PDF before extracting it.", status_code=409
            )
        return file_out(item), item.storage_key, item.sha256

    async with _file_admission(request, request.app.state.file_extraction_admission):
        target, storage_key, digest = await _run_file_db(request, authorize)
        if target["extraction_status"] == "ready":
            return target
        payload = await run_in_threadpool(request.app.state.file_store.read, storage_key)
        if len(payload) != target["size_bytes"] or hashlib.sha256(payload).hexdigest() != digest:
            raise DomainError(
                "file_integrity_error",
                "Stored content failed integrity validation.",
                status_code=409,
            )
        settings = request.app.state.settings
        result, failure = None, None
        try:
            result = await run_in_threadpool(
                extract_pdf,
                payload,
                max_pages=settings.agent_file_pdf_max_pages,
                max_chars=settings.agent_file_extracted_max_chars,
                timeout_seconds=settings.agent_file_extraction_timeout_seconds,
            )
        except DomainError as exc:
            failure = exc
        # Recheck under a short row lock after parsing: deletion, collection or
        # another instance completing extraction must not be overwritten.
        return await _run_file_db(
            request, lambda db: _finish_extraction(db, identity, file_id, digest, result, failure)
        )


def _finish_extraction(db, identity, file_id, digest, result, failure):
    item = owned_file(db, identity, file_id, lock=True)
    if item.state not in {"stored", "ready"} or item.sha256 != digest:
        raise DomainError(
            "file_integrity_error", "Stored content failed integrity validation.", status_code=409
        )
    if item.extraction_status == "ready":
        return file_out(item)
    if failure is not None:
        item.extraction_status = "failed"
        item.extraction_error_code = failure.code
        db.commit()
        raise failure
    assert result is not None
    encoded = result.markdown.encode("utf-8")
    item.extracted_markdown = result.markdown
    item.extraction_parser = result.parser
    item.extraction_parser_version = result.parser_version
    item.extracted_sha256 = hashlib.sha256(encoded).hexdigest()
    item.extracted_size_bytes = len(encoded)
    item.extraction_truncated = result.truncated
    item.extraction_status = "ready"
    item.extraction_error_code = None
    db.commit()
    return file_out(item)


@router.get("/{file_id}/content")
def get_content(file_id: str, request: Request, identity: CurrentIdentity, db: Db):
    item = owned_file(db, identity, file_id)
    if item.state not in {"stored", "ready"}:
        raise DomainError("file_content_unavailable", "File content is not ready.", status_code=404)
    payload = request.app.state.file_store.read(item.storage_key)
    if hashlib.sha256(payload).hexdigest() != item.sha256:
        raise DomainError(
            "file_integrity_error", "Stored content failed integrity validation.", status_code=409
        )
    from urllib.parse import quote

    return Response(
        payload,
        media_type=item.mime_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(item.filename, safe='')}",
        },
    )


@router.delete("/{file_id}")
def delete_file(file_id: str, identity: CurrentIdentity, db: Db):
    item = owned_file(db, identity, file_id, lock=True)
    if item.state == "ready":
        raise DomainError(
            "file_already_claimed",
            "Delete its conversation to retire a claimed file.",
            status_code=409,
        )
    item.state = "delete_pending"
    item.deleted_at = utcnow()
    db.commit()
    return {"id": file_id, "deleted": True}
