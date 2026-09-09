"""CornAgent sessions, Runs, versions and replayable SSE."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentIdentity, Db, StreamIdentity, get_run_rate_limit_identity
from app.api.routes._common import IdempotencyKey, require_idempotency_key
from app.persistence.agent_runtime import TERMINAL_RUN_STATUSES, AgentRepository
from app.persistence.agent_schemas import (
    AgentMessageEdit,
    AgentQuestionResponse,
    AgentQuestionResult,
    AgentRunCreate,
    AgentRunOut,
    AgentSessionDeleteResult,
    AgentSessionDetail,
    AgentSessionList,
    AgentSessionRunCreate,
    AgentSessionRunOut,
    AgentVersionSwitch,
)
from app.persistence.errors import DomainError

router = APIRouter(prefix="/agent")


def _runtime(request: Request):
    return request.app.state.agent_runtime


def _repository(request: Request, db: Db) -> AgentRepository:
    settings = request.app.state.settings
    return AgentRepository(
        db,
        file_input_enabled=settings.agent_file_input_enabled,
        file_max_count=settings.agent_file_max_count,
        file_max_total_bytes=settings.agent_file_max_total_bytes,
        pdf_max_count=settings.agent_file_pdf_max_count,
    )


async def _run_repository[T](request: Request, operation: Callable[[AgentRepository], T]) -> T:
    def execute() -> T:
        # Each database phase owns its Session in the worker thread.
        with request.app.state.database.session_factory() as db:
            return operation(_repository(request, db))

    return await run_in_threadpool(execute)


@router.get("/status")
def agent_status(request: Request, _identity: CurrentIdentity) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "available": _runtime(request).available,
        "unavailable_reason": (
            "model_not_configured" if _runtime(request).model_client is None
            else "event_stream_not_configured" if _runtime(request).event_stream is None
            else None
        ),
        "file_input": {
            "enabled": bool(
                _runtime(request).available
                and settings.agent_file_input_enabled
                and request.app.state.file_store
            ),
            "accepts": [
                *[
                    {
                        "mime_type": mime_type,
                        "max_bytes": settings.agent_file_image_max_bytes,
                        "max_count": settings.agent_file_max_count,
                    }
                    for mime_type in settings.agent_file_image_mime_types
                ],
                {
                    "mime_type": "application/pdf",
                    "max_bytes": settings.agent_file_pdf_max_bytes,
                    "max_count": settings.agent_file_pdf_max_count,
                },
            ],
            "max_count": settings.agent_file_max_count,
            "max_total_bytes": settings.agent_file_max_total_bytes,
        },
    }


@router.get("/sessions", response_model=AgentSessionList)
def list_agent_sessions(
    identity: CurrentIdentity,
    db: Db,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> AgentSessionList:
    data, next_cursor = AgentRepository(db).list_sessions(
        identity,
        cursor=cursor,
        limit=limit,
        query=query,
    )
    return AgentSessionList(data=data, next_cursor=next_cursor)


@router.post("/sessions", response_model=AgentSessionRunOut)
async def create_agent_session_run(
    payload: AgentSessionRunCreate,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: IdempotencyKey = None,
) -> AgentSessionRunOut:
    runtime = _runtime(request)
    runtime.require_available()
    key = require_idempotency_key(idempotency_key)
    replay = await _run_repository(
        request,
        lambda repository: repository.replay_session_run(
            identity,
            content=payload.content,
            idempotency_key=key,
            title=payload.title,
            context=payload.context,
            attachment_file_ids=[item.file_id for item in payload.attachments],
        ),
    )
    if replay is not None:
        session, run = replay
        if run.status == "pending":
            runtime.kick(run.id)
        return AgentSessionRunOut(session=session, run=run)
    await request.app.state.agent_run_rate_limiter.require(get_run_rate_limit_identity(request))
    verified_context = await runtime.verify_source_context(identity, payload.context)
    session, run = await _run_repository(
        request,
        lambda repository: repository.create_session_run(
            identity,
            content=payload.content,
            idempotency_key=key,
            title=payload.title,
            context=verified_context,
            request_context=payload.context,
            attachment_file_ids=[item.file_id for item in payload.attachments],
        ),
    )
    if run.status == "pending":
        runtime.kick(run.id)
    return AgentSessionRunOut(session=session, run=run)


@router.get("/sessions/{session_id}", response_model=AgentSessionDetail)
def get_agent_session(
    session_id: str,
    identity: CurrentIdentity,
    db: Db,
    before: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 40,
) -> AgentSessionDetail:
    return AgentRepository(db).session_detail(
        identity,
        session_id,
        before_message_id=before,
        limit=limit,
    )


@router.delete("/sessions/{session_id}", response_model=AgentSessionDeleteResult)
def delete_agent_session(
    session_id: str,
    identity: CurrentIdentity,
    db: Db,
) -> AgentSessionDeleteResult:
    return AgentRepository(db).delete_session(identity, session_id)


@router.post("/sessions/{session_id}/messages", response_model=AgentRunOut)
async def create_agent_run(
    session_id: str,
    payload: AgentRunCreate,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: IdempotencyKey = None,
) -> AgentRunOut:
    runtime = _runtime(request)
    runtime.require_available()
    key = require_idempotency_key(idempotency_key)
    replay = await _run_repository(
        request,
        lambda repository: repository.replay_run(
            identity,
            idempotency_key=key,
            operation="create_run",
            target_id=session_id,
            content=payload.content,
            attachment_file_ids=[item.file_id for item in payload.attachments],
        ),
    )
    if replay is not None:
        return replay
    await request.app.state.agent_run_rate_limiter.require(get_run_rate_limit_identity(request))
    run = await _run_repository(
        request,
        lambda repository: repository.create_run(
            identity,
            session_id,
            payload.content,
            key,
            attachment_file_ids=[item.file_id for item in payload.attachments],
        ),
    )
    if run.status == "pending":
        runtime.kick(run.id)
    return run


@router.post("/messages/{message_id}/regenerate", response_model=AgentRunOut)
async def regenerate_agent_message(
    message_id: str,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: IdempotencyKey = None,
) -> AgentRunOut:
    runtime = _runtime(request)
    runtime.require_available()
    key = require_idempotency_key(idempotency_key)
    replay = await _run_repository(
        request,
        lambda repository: repository.replay_run(
            identity,
            idempotency_key=key,
            operation="regenerate",
            target_id=message_id,
        ),
    )
    if replay is not None:
        return replay
    await request.app.state.agent_run_rate_limiter.require(get_run_rate_limit_identity(request))
    run = await _run_repository(
        request, lambda repository: repository.regenerate(identity, message_id, key)
    )
    if run.status == "pending":
        runtime.kick(run.id)
    return run


@router.post("/messages/{message_id}/edit", response_model=AgentRunOut)
async def edit_agent_message(
    message_id: str,
    payload: AgentMessageEdit,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: IdempotencyKey = None,
) -> AgentRunOut:
    runtime = _runtime(request)
    runtime.require_available()
    key = require_idempotency_key(idempotency_key)
    replay = await _run_repository(
        request,
        lambda repository: repository.replay_run(
            identity,
            idempotency_key=key,
            operation="edit",
            target_id=message_id,
            content=payload.content,
            attachment_file_ids=(
                [item.file_id for item in payload.attachments]
                if payload.attachments is not None
                else None
            ),
        ),
    )
    if replay is not None:
        return replay
    await request.app.state.agent_run_rate_limiter.require(get_run_rate_limit_identity(request))
    run = await _run_repository(
        request,
        lambda repository: repository.edit_user_message(
            identity,
            message_id,
            payload.content,
            key,
            attachment_file_ids=(
                [item.file_id for item in payload.attachments]
                if payload.attachments is not None
                else None
            ),
        ),
    )
    if run.status == "pending":
        runtime.kick(run.id)
    return run


@router.post("/sessions/{session_id}/active-version", response_model=AgentSessionDetail)
def switch_agent_version(
    session_id: str,
    payload: AgentVersionSwitch,
    identity: CurrentIdentity,
    db: Db,
) -> AgentSessionDetail:
    return AgentRepository(db).switch_version(identity, session_id, payload.message_id)


@router.post("/questions/{question_id}/respond", response_model=AgentQuestionResult)
async def respond_to_agent_question(
    question_id: str,
    payload: AgentQuestionResponse,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: IdempotencyKey = None,
) -> AgentQuestionResult:
    runtime = _runtime(request)
    runtime.require_available()
    key = require_idempotency_key(idempotency_key)
    replay = await _run_repository(
        request,
        lambda repository: repository.preflight_question_response(
            identity,
            question_id,
            payload,
            key,
        ),
    )
    if replay is not None:
        runtime.kick(replay.run_id)
        return replay
    result, event = await _run_repository(
        request,
        lambda repository: repository.respond_question(
            identity,
            question_id,
            payload,
            key,
        ),
    )
    await runtime.publish_persisted(result.run_id, event)
    runtime.kick(result.run_id)
    return result


@router.post("/runs/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: IdempotencyKey = None,
) -> dict[str, str]:
    event = await _run_repository(
        request,
        lambda repository: repository.cancel_run(
            identity,
            run_id,
            require_idempotency_key(idempotency_key),
        ),
    )
    runtime = _runtime(request)
    if runtime.available and event is not None:
        await runtime.publish_persisted(run_id, event)
        await runtime.cancel(run_id)
    return {"status": "cancelled"}


def _parse_cursor(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    try:
        epoch, sequence = value.split(":", 1)
        parsed = (int(epoch), int(sequence))
    except (TypeError, ValueError):
        raise DomainError(
            "invalid_agent_stream_cursor", "Last-Event-ID must be <epoch>:<sequence>."
        ) from None
    if parsed[0] < 1 or parsed[1] < 0:
        raise DomainError(
            "invalid_agent_stream_cursor", "Last-Event-ID must be <epoch>:<sequence>."
        )
    return parsed


def _snapshot(application: Any, identity: Any, run_id: str):
    with application.state.database.session_factory() as db:
        return AgentRepository(db).stream_snapshot(identity, run_id)


def _sse(event_id: str, event: str, data: dict[str, Any]) -> str:
    return (
        f"id: {event_id}\n"
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


@router.get("/runs/{run_id}/stream")
async def stream_agent_run(
    run_id: str,
    request: Request,
    stream_auth: StreamIdentity,
    after: Annotated[str | None, Query()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    runtime = _runtime(request)
    runtime.require_available()
    if after is not None and last_event_id is not None and after != last_event_id:
        raise DomainError(
            "agent_stream_cursor_conflict",
            "after and Last-Event-ID must match.",
            status_code=409,
        )
    _parse_cursor(after or last_event_id)
    lease = await request.app.state.agent_stream_connection_limiter.acquire(
        stream_auth.identity,
        run_id,
    )
    try:
        snapshot = await run_in_threadpool(_snapshot, request.app, stream_auth.identity, run_id)
    except BaseException:
        await lease.release()
        raise

    async def read_stream():
        current = (snapshot.run.stream_epoch, snapshot.run.next_sequence - 1)
        snapshot_id = f"{current[0]}:{current[1]}"
        yield _sse(snapshot_id, "snapshot", snapshot.model_dump(mode="json"))
        if snapshot.run.status in TERMINAL_RUN_STATUSES:
            return
        redis_cursor = "0-0"
        heartbeat_at = time.monotonic()
        # The database snapshot is authoritative and replaces all earlier stream
        # state, so subsequent Redis events are compared with that snapshot—not
        # with an untrusted or stale client cursor.
        visible_cursor = current
        while not await request.is_disconnected():
            now = time.monotonic()
            if request.app.state.settings.users_enabled:
                try:
                    current_identity = await run_in_threadpool(
                        request.app.state.identity_provider.authenticate, request
                    )
                    if current_identity != stream_auth.identity:
                        return
                except DomainError:
                    return
            try:
                redis_cursor, events = await runtime.read_events(run_id, redis_cursor)
            except Exception:
                events = []
                await asyncio.sleep(request.app.state.settings.event_poll_seconds)
            for event in events:
                event_cursor = (int(event["epoch"]), int(event["sequence"]))
                if event_cursor <= visible_cursor:
                    continue
                if (
                    event_cursor[0] != visible_cursor[0]
                    or event_cursor[1] != visible_cursor[1] + 1
                    or event["event"] in {"done", "error", "cancelled"}
                ):
                    # Root and Child commits share a sequence, but Redis publication
                    # may race. Never skip a missing fact by advancing past a gap.
                    refreshed = await run_in_threadpool(
                        _snapshot, request.app, stream_auth.identity, run_id
                    )
                    visible_cursor = (refreshed.run.stream_epoch, refreshed.run.next_sequence - 1)
                    yield _sse(
                        f"{visible_cursor[0]}:{visible_cursor[1]}",
                        "snapshot",
                        refreshed.model_dump(mode="json"),
                    )
                    if refreshed.run.status in TERMINAL_RUN_STATUSES:
                        return
                    if event_cursor <= visible_cursor:
                        continue
                visible_cursor = event_cursor
                yield _sse(event["id"], event["event"], event["data"])
                if event["event"] in {"done", "error", "cancelled"}:
                    return
            now = time.monotonic()
            if now - heartbeat_at >= request.app.state.settings.event_heartbeat_seconds:
                refreshed = await run_in_threadpool(
                    _snapshot, request.app, stream_auth.identity, run_id
                )
                refreshed_cursor = (
                    refreshed.run.stream_epoch,
                    refreshed.run.next_sequence - 1,
                )
                if refreshed_cursor > visible_cursor:
                    visible_cursor = refreshed_cursor
                    yield _sse(
                        f"{visible_cursor[0]}:{visible_cursor[1]}",
                        "snapshot",
                        refreshed.model_dump(mode="json"),
                    )
                else:
                    yield ": heartbeat\n\n"
                heartbeat_at = now
                if refreshed.run.status in TERMINAL_RUN_STATUSES:
                    return

    async def generate():
        try:
            async for chunk in read_stream():
                yield chunk
        finally:
            await lease.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        background=BackgroundTask(lease.release),
    )


__all__ = ["router"]
