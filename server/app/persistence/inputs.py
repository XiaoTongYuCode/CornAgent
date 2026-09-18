"""Durable input queue. Session serialization, version checks and idempotent mutations."""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.persistence.errors import DomainError
from app.persistence.models import (
    AgentInput,
    AgentInputMutation,
    AgentMessage,
    AgentRun,
    AgentSession,
    new_id,
    utcnow,
)
from app.persistence.scope import Identity


def output(item):
    return {
        name: getattr(item, name)
        for name in (
            "id",
            "session_id",
            "mode",
            "status",
            "content",
            "file_ids",
            "version",
            "error_message",
        )
    }


def pending(db, session_id):
    return list(
        db.scalars(
            select(AgentInput)
            .where(
                AgentInput.session_id == session_id,
                AgentInput.status.in_(["pending", "failed"]),
            )
            .order_by(AgentInput.created_at, AgentInput.id)
        )
    )


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def key_id(identity, key):
    return str(
        uuid5(NAMESPACE_URL, f"cornagent:input:{identity.tenant_id}:{identity.membership_id}:{key}")
    )


def create(repo, identity, session_id, payload, key):
    session = repo._owned_session(identity, session_id, for_update=True)
    item_id = key_id(identity, key)
    digest = fingerprint({"session": session_id, **payload.model_dump()})
    existing = repo.db.get(AgentInput, item_id)
    if existing:
        if existing.request_hash != digest:
            raise DomainError(
                "agent_input_conflict", "This key belongs to another input.", status_code=409
            )
        return output(existing)
    if len(pending(repo.db, session_id)) >= 20:
        raise DomainError(
            "agent_input_queue_full", "At most 20 pending messages are allowed.", status_code=429
        )
    files = [item.file_id for item in payload.attachments]
    repo._attach_files(identity, session_id=session.id, message_id=None, attachment_file_ids=files)
    item = AgentInput(
        id=item_id,
        session_id=session_id,
        user_id=identity.user_id,
        mode=payload.mode,
        content=payload.content,
        file_ids=files,
        request_hash=digest,
    )
    repo.db.add(item)
    repo.db.commit()
    return output(item)


def change(repo, identity, input_id, payload, key):
    item = repo.db.get(AgentInput, input_id)
    if item is None:
        raise DomainError("agent_input_not_found", "Pending message not found.", status_code=404)
    repo._owned_session(identity, item.session_id, for_update=True)
    repo.db.refresh(item)
    mutation_id = key_id(identity, "change:" + key)
    digest = fingerprint({"input_id": input_id, **payload.model_dump()})
    replay = repo.db.get(AgentInputMutation, mutation_id)
    if replay:
        if replay.request_hash != digest:
            raise DomainError(
                "agent_input_conflict", "This key belongs to another change.", status_code=409
            )
        return replay.result
    if item.version != payload.version or item.status not in {"pending", "failed"}:
        raise DomainError(
            "agent_input_changed",
            "The message has already changed. Refresh and retry.",
            status_code=409,
        )
    content = payload.content.strip() if payload.content is not None else item.content
    if not content and not item.file_ids:
        raise DomainError("invalid_agent_input", "A message cannot be empty.", status_code=422)
    item.content = content
    item.mode = payload.mode or item.mode
    item.status = "cancelled" if payload.cancel else "pending"
    item.error_message = None
    item.version += 1
    item.updated_at = utcnow()
    result = output(item)
    repo.db.add(
        AgentInputMutation(id=mutation_id, input_id=item.id, request_hash=digest, result=result)
    )
    repo.db.commit()
    return result


def dispatch(repo):
    """Create one next Run per idle session, in the same transaction as applying its input."""
    from app.persistence.agent_runtime import ACTIVE_RUN_STATUSES

    active = select(AgentRun.session_id).where(AgentRun.status.in_(ACTIVE_RUN_STATUSES))
    sessions = list(
        repo.db.scalars(
            select(AgentSession)
            .where(
                AgentSession.id.in_(
                    select(AgentInput.session_id).where(AgentInput.status == "pending")
                ),
                AgentSession.id.not_in(active),
            )
            .order_by(AgentSession.id)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
    )
    runs = []
    for session in sessions:
        if repo.db.scalar(repo._active_run_query(session.id)):
            continue
        item = next((i for i in pending(repo.db, session.id) if i.status == "pending"), None)
        if item is None:
            continue
        identity = Identity(item.user_id, session.tenant_id, session.owner_membership_id)
        try:
            with repo.db.begin_nested():
                run = repo._append_create_run(
                    identity, session, item.content, attachment_file_ids=item.file_ids
                )
        except DomainError as exc:
            item.status = "failed"
            item.error_message = exc.message
            item.version += 1
            continue
        item.status, item.run_id, item.message_id = "applied", run.id, run.user_message_id
        item.version += 1
        item.updated_at = utcnow()
        runs.append(run.id)
    repo.db.commit()
    return runs


def consume(repo, run, messages, *, commit=True):
    """Caller owns Run lock. Insert steering users before the active assistant atomically."""
    from app.persistence.agent_runtime import _event, ensure_checkpoint_size

    session = repo.db.scalar(
        # Serialize session changes without blocking foreign-key KEY SHARE locks
        # held by telemetry inserts waiting for the Run lock owned by this caller.
        select(AgentSession)
        .where(AgentSession.id == run.session_id)
        .with_for_update(key_share=True)
    )
    items = [
        i for i in pending(repo.db, run.session_id) if i.mode == "steer" and i.status == "pending"
    ]
    if not items:
        return None
    assistant = repo.db.get(AgentMessage, run.assistant_message_id)
    parent = assistant.parent_message_id
    next_messages = list(messages)
    for item in items:
        identity = Identity(item.user_id, session.tenant_id, session.owner_membership_id)
        message_id = new_id()
        message = AgentMessage(
            id=message_id,
            tenant_id=session.tenant_id,
            owner_membership_id=session.owner_membership_id,
            session_id=session.id,
            role="user",
            markdown=item.content,
            parent_message_id=parent,
            version_group_id=message_id,
            version_index=1,
            content_parts=[],
            provider_messages=[],
        )
        repo.db.add(message)
        repo.db.flush()
        files = repo._attach_files(
            identity,
            session_id=session.id,
            message_id=message_id,
            attachment_file_ids=item.file_ids,
        )
        content = item.content
        if files:
            content = [
                {"type": "text", "text": item.content},
                *[
                    {
                        "type": "cintel_file_ref",
                        "file_id": f.id,
                        "filename": f.filename,
                        "mime_type": f.mime_type,
                    }
                    for f in files
                ],
            ]
        next_messages.append({"role": "user", "content": content})
        item.status, item.run_id, item.message_id = "applied", run.id, message_id
        item.version += 1
        item.updated_at = utcnow()
        parent = message_id
    assistant.parent_message_id = parent
    # The active assistant follows newly inserted users in chronological pagination.
    assistant.created_at = utcnow()
    assistant.updated_at = utcnow()
    checkpoint = dict(run.checkpoint)
    checkpoint.update(
        provider_messages=next_messages,
        safe_provider_messages=next_messages,
        safe_draft_markdown=run.draft_markdown,
        safe_reasoning_markdown=run.reasoning_markdown,
        safe_content_parts=run.content_parts,
        content_parts=run.content_parts,
    )
    ensure_checkpoint_size(checkpoint)
    run.checkpoint = checkpoint
    run.checkpoint_revision += 1
    event = _event(run, "input_applied", {"run_id": run.id})
    if commit:
        repo.db.commit()
    return next_messages, event


def notify(repo, session_id):
    from app.persistence.agent_runtime import _event

    run = repo.db.scalar(repo._active_run_query(session_id).with_for_update())
    if run is None:
        return None
    event = _event(run, "input_queued", {"run_id": run.id})
    repo.db.commit()
    return run.id, event


def resume_steering_questions(repo):
    from app.persistence.agent_schemas import AgentQuestionResponse
    from app.persistence.models import AgentQuestion

    rows = list(
        repo.db.execute(
            select(AgentQuestion.id, AgentRun.session_id)
            .join(AgentRun, AgentRun.id == AgentQuestion.run_id)
            .where(
                AgentRun.status == "waiting_for_user",
                AgentQuestion.status == "pending",
                AgentRun.session_id.in_(
                    select(AgentInput.session_id).where(
                        AgentInput.mode == "steer", AgentInput.status == "pending"
                    )
                ),
            )
        )
    )
    events = []
    for question_id, session_id in rows:
        session = repo.db.get(AgentSession, session_id)
        # The steering message cancels an outstanding interaction; it never approves a tool.
        item = next(
            (
                i
                for i in pending(repo.db, session_id)
                if i.mode == "steer" and i.status == "pending"
            ),
            None,
        )
        if item is None:
            continue
        identity = Identity(item.user_id, session.tenant_id, session.owner_membership_id)
        try:
            result, event = repo.respond_question(
                identity,
                question_id,
                AgentQuestionResponse(action="cancel"),
                f"steer:{question_id}",
            )
            if event:
                events.append((result.run_id, event))
        except DomainError as exc:
            repo.db.rollback()
            if exc.status_code != 409:
                raise
    return events


def replay(repo, identity, session_id, payload, key):
    repo._owned_session(identity, session_id)
    existing = repo.db.get(AgentInput, key_id(identity, key))
    if existing is None:
        return None
    if existing.request_hash != fingerprint({"session": session_id, **payload.model_dump()}):
        raise DomainError(
            "agent_input_conflict", "This key belongs to another input.", status_code=409
        )
    return output(existing)
