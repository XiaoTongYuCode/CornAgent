"""Branch-authorized immutable tool receipts; callers own the commit boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased, defer

from app.persistence.errors import DomainError
from app.persistence.models import AgentMessage, AgentRun, AgentSession, AgentToolReceipt
from app.persistence.page_cursor import (
    decode_page_cursor,
    encode_page_cursor,
    normalize_cursor_time,
)
from app.persistence.scope import Identity

RECEIPT_MAX_BYTES = 4 * 1024 * 1024
RUN_MATERIAL_MAX_BYTES = 64 * 1024 * 1024
MATERIAL_REFERENCE_TYPE = "cornagent_material_ref"
MATERIAL_TOOL_NAMES = frozenset(
    {"read_tool_result", "list_materials", "search_materials", "read_material"}
)


def canonical_json(value: Any) -> str:
    try:
        serialized = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        serialized.encode("utf-8")
        return serialized
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise DomainError(
            "agent_material_invalid_result",
            "Tool receipts must contain valid JSON.",
            status_code=422,
        ) from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _missing() -> DomainError:
    return DomainError(
        "agent_material_unavailable",
        "Material is unavailable in the current branch.",
        status_code=404,
    )


def _truncated(value: Any) -> bool:
    if isinstance(value, list):
        return any(_truncated(item) for item in value)
    if not isinstance(value, dict):
        return False
    return any(
        (key.endswith("truncated") and item is True)
        or (key in {"next_cursor", "continuation_token"} and bool(item))
        or _truncated(item)
        for key, item in value.items()
    )


class MaterialRepository:
    def __init__(self, db: Session):
        self.db = db

    def _owned_run(self, identity: Identity, run_id: str, *, lock: bool = False) -> AgentRun:
        query = (
            select(AgentRun)
            .join(AgentSession, AgentSession.id == AgentRun.session_id)
            .where(
                AgentRun.id == run_id,
                AgentRun.tenant_id == identity.tenant_id,
                AgentRun.owner_membership_id == identity.membership_id,
                AgentSession.tenant_id == identity.tenant_id,
                AgentSession.owner_membership_id == identity.membership_id,
            )
        )
        if lock:
            query = query.with_for_update(of=AgentRun)
        run = self.db.scalar(query)
        if run is None:
            raise _missing()
        return run

    def allowed_run_ids(self, identity: Identity, run_id: str) -> tuple[str, ...]:
        """Follow this Run's input ancestry, never the Session's mutable active leaf."""
        run = self._owned_run(identity, run_id)
        lineage = (
            select(AgentMessage.id, AgentMessage.parent_message_id)
            .where(
                AgentMessage.id == run.user_message_id,
                AgentMessage.session_id == run.session_id,
                AgentMessage.tenant_id == identity.tenant_id,
                AgentMessage.owner_membership_id == identity.membership_id,
            )
            .cte("material_lineage", recursive=True)
        )
        parent = aliased(AgentMessage)
        lineage = lineage.union(
            select(parent.id, parent.parent_message_id)
            .join(lineage, parent.id == lineage.c.parent_message_id)
            .where(
                parent.session_id == run.session_id,
                parent.tenant_id == identity.tenant_id,
                parent.owner_membership_id == identity.membership_id,
            )
        )
        ancestors = self.db.scalars(
            select(AgentRun.id)
            .join(lineage, AgentRun.assistant_message_id == lineage.c.id)
            .where(
                AgentRun.session_id == run.session_id,
                AgentRun.tenant_id == identity.tenant_id,
                AgentRun.owner_membership_id == identity.membership_id,
            )
        )
        return tuple(dict.fromkeys([run.id, *ancestors]))

    def replay(
        self,
        identity: Identity,
        run_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, Any]:
        """Reuse a committed public result before executing a repeated provider call."""
        self._owned_run(identity, run_id)
        item = self.db.scalar(
            select(AgentToolReceipt).where(
                AgentToolReceipt.run_id == run_id,
                AgentToolReceipt.call_id == call_id,
                AgentToolReceipt.tenant_id == identity.tenant_id,
                AgentToolReceipt.owner_membership_id == identity.membership_id,
            )
        )
        if item is None:
            return False, None
        request_hash = _digest(canonical_json({"tool": tool_name, "arguments": arguments}))
        if item.request_hash != request_hash:
            raise DomainError(
                "agent_material_call_conflict",
                "Tool call ID already has different arguments.",
                status_code=409,
            )
        if _digest(item.result_json) != item.content_hash:
            raise DomainError(
                "agent_material_corrupt",
                "Stored tool result failed integrity validation.",
                status_code=503,
            )
        if item.private_result:
            # The caller must execute the read-only source tool again so its current
            # ACL and lifecycle are checked before the provider sees any derivative.
            return False, None
        return True, json.loads(item.result_json)

    def save(
        self,
        identity: Identity,
        *,
        run_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        read_only: bool = True,
        private_result: bool = False,
        public_result: Any = None,
    ) -> dict[str, Any]:
        """Insert in the existing fenced completion transaction, without committing.

        Private derivatives are represented by their public projection and original
        source read arguments. They must be reauthorized and re-read from the source.
        """
        if not call_id or len(call_id) > 240 or not tool_name or len(tool_name) > 160:
            raise DomainError("agent_material_invalid_call", "Invalid tool call identifier.")
        request_hash = _digest(canonical_json({"tool": tool_name, "arguments": arguments}))
        if len(canonical_json(arguments).encode("utf-8")) > 64 * 1024:
            raise DomainError("agent_material_invalid_call", "Tool arguments exceed 64 KiB.")
        run = self._owned_run(identity, run_id, lock=True)
        prior = self.db.scalar(
            select(AgentToolReceipt).where(
                AgentToolReceipt.run_id == run_id, AgentToolReceipt.call_id == call_id
            )
        )
        if prior is not None:
            if (
                prior.request_hash != request_hash
                or prior.private_result != private_result
                or prior.read_only != read_only
            ):
                raise DomainError(
                    "agent_material_call_conflict",
                    "Tool call ID already has different arguments.",
                    status_code=409,
                )
            return self.reference(prior)
        body = canonical_json(public_result if private_result else result)
        size = len(body.encode("utf-8"))
        if size > RECEIPT_MAX_BYTES:
            raise DomainError(
                "agent_material_result_too_large",
                "Full tool result exceeds the 4 MiB limit.",
                status_code=422,
            )
        used = self.db.scalar(
            select(func.coalesce(func.sum(AgentToolReceipt.size_bytes), 0)).where(
                AgentToolReceipt.run_id == run.id
            )
        )
        if used + size > RUN_MATERIAL_MAX_BYTES:
            raise DomainError(
                "agent_material_capacity_exceeded",
                "Run materials exceed the 64 MiB limit.",
                status_code=422,
            )
        # Private source text never influences a persisted title or preview.
        title_payload = public_result if private_result else result
        title = str(title_payload.get("filename") or "") if isinstance(title_payload, dict) else ""
        if not title:
            query = arguments.get("query") if not private_result else None
            title = f"{tool_name}: {query}" if query else tool_name
        item = AgentToolReceipt(
            id=str(uuid5(NAMESPACE_URL, f"cornagent:receipt:{run_id}:{call_id}")),
            tenant_id=identity.tenant_id,
            owner_membership_id=identity.membership_id,
            session_id=run.session_id,
            run_id=run.id,
            call_id=call_id,
            tool_name=tool_name,
            title=title[:240],
            arguments=json.loads(canonical_json(arguments)),
            request_hash=request_hash,
            content_hash=_digest(body),
            result_json=body,
            size_bytes=size,
            read_only=read_only,
            private_result=private_result,
            failed=isinstance(result, dict) and result.get("ok") is False,
            source_truncated=_truncated(json.loads(body))
            or (
                tool_name in {"web_search", "mock_web_search"}
                and isinstance(result, dict)
                and bool(result.get("results"))
            ),
        )
        self.db.add(item)
        self.db.flush()
        return self.reference(item)

    @staticmethod
    def reference(item: AgentToolReceipt, *, preview: str | None = None) -> dict[str, Any]:
        return {
            "type": MATERIAL_REFERENCE_TYPE,
            "receipt_id": item.id,
            "material_id": item.id,
            "run_id": item.run_id,
            "call_id": item.call_id,
            "tool_name": item.tool_name,
            "title": item.title,
            "size_bytes": item.size_bytes,
            "content_hash": item.content_hash,
            "hash": item.content_hash,
            "preview": ""
            if item.private_result
            else (preview if preview is not None else item.result_json[:1000]),
            "complete": not item.private_result,
            "source_truncated": item.source_truncated,
            "source_read_required": item.private_result,
            "read_only": item.read_only,
            "failed": item.failed,
        }

    def resolve(
        self,
        identity: Identity,
        run_id: str,
        *,
        receipt_id: str = "",
        call_id: str = "",
    ) -> AgentToolReceipt:
        if bool(receipt_id) == bool(call_id):
            raise DomainError(
                "agent_material_invalid_reference",
                "Provide receipt_id or call_id, exclusively.",
                status_code=422,
            )
        allowed = self.allowed_run_ids(identity, run_id)
        query = select(AgentToolReceipt).where(
            AgentToolReceipt.tenant_id == identity.tenant_id,
            AgentToolReceipt.owner_membership_id == identity.membership_id,
            AgentToolReceipt.run_id.in_(allowed),
        )
        if receipt_id:
            query = query.where(AgentToolReceipt.id == receipt_id)
        else:
            # Call IDs are only unique within a Run. Do not guess an ancestor's call.
            query = query.where(
                AgentToolReceipt.run_id == run_id, AgentToolReceipt.call_id == call_id
            )
        item = self.db.scalar(query)
        if item is None:
            raise _missing()
        if _digest(item.result_json) != item.content_hash:
            raise DomainError(
                "agent_material_corrupt",
                "Stored tool result failed integrity validation.",
                status_code=503,
            )
        return item

    def read(
        self,
        identity: Identity,
        run_id: str,
        *,
        receipt_id: str = "",
        call_id: str = "",
        cursor: str = "",
        max_chars: int = 12_000,
    ) -> dict[str, Any]:
        item = self.resolve(identity, run_id, receipt_id=receipt_id, call_id=call_id)
        result = {"ok": True, **self.reference(item), "trust": "untrusted_tool_content"}
        if item.private_result:
            return {
                **result,
                "content": "",
                "next_cursor": "",
                "total_chars": 0,
                "source_tool": item.tool_name,
                "source_arguments": item.arguments,
                "message": "Re-read the source tool; private derivatives are not duplicated here.",
            }
        offset = 0
        if cursor:
            try:
                binding, numeric = cursor.split(":", 1)
                if binding != f"{item.id}.{item.content_hash[:16]}" or not numeric.isdigit():
                    raise ValueError
                offset = int(numeric)
                if offset > len(item.result_json):
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise DomainError(
                    "invalid_agent_material_cursor",
                    "Material cursor is invalid.",
                    status_code=422,
                ) from exc
        end = min(offset + min(max(max_chars, 1), 20_000), len(item.result_json))
        return {
            **result,
            "content": item.result_json[offset:end],
            "format": "application/json",
            "offset": offset,
            "total_chars": len(item.result_json),
            "next_cursor": (
                f"{item.id}.{item.content_hash[:16]}:{end}" if end < len(item.result_json) else ""
            ),
        }

    def list(
        self,
        identity: Identity,
        run_id: str,
        *,
        query: str = "",
        tool_name: str = "",
        cursor: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        if len(query) > 200:
            raise DomainError(
                "agent_material_invalid_query", "Search query exceeds 200 characters."
            )
        allowed = self.allowed_run_ids(identity, run_id)
        statement = (
            select(AgentToolReceipt, func.substr(AgentToolReceipt.result_json, 1, 1000))
            .options(defer(AgentToolReceipt.result_json), defer(AgentToolReceipt.arguments))
            .where(
                AgentToolReceipt.tenant_id == identity.tenant_id,
                AgentToolReceipt.owner_membership_id == identity.membership_id,
                AgentToolReceipt.run_id.in_(allowed),
            )
        )
        if tool_name:
            statement = statement.where(AgentToolReceipt.tool_name == tool_name)
        if query:
            statement = statement.where(
                or_(
                    AgentToolReceipt.title.icontains(query, autoescape=True),
                    and_(
                        AgentToolReceipt.private_result.is_(False),
                        AgentToolReceipt.result_json.icontains(query, autoescape=True),
                    ),
                )
            )
        cursor_scope = _digest(canonical_json({"run_id": run_id, "q": query, "tool": tool_name}))
        if cursor:
            at, item_id = decode_page_cursor(
                cursor,
                kind="materials",
                scope=cursor_scope,
                error_code="invalid_agent_material_cursor",
                error_message="Invalid material cursor.",
            )
            at = normalize_cursor_time(at, dialect_name=self.db.get_bind().dialect.name)
            statement = statement.where(
                or_(
                    AgentToolReceipt.created_at < at,
                    and_(AgentToolReceipt.created_at == at, AgentToolReceipt.id < item_id),
                )
            )
        page_size = min(max(limit, 1), 50)
        rows = list(
            self.db.execute(
                statement.order_by(
                    AgentToolReceipt.created_at.desc(), AgentToolReceipt.id.desc()
                ).limit(page_size + 1)
            )
        )
        page = rows[:page_size]
        return {
            "ok": True,
            "materials": [self.reference(item, preview=preview) for item, preview in page],
            "next_cursor": encode_page_cursor(
                "materials", page[-1][0].created_at, page[-1][0].id, scope=cursor_scope
            )
            if len(rows) > page_size
            else "",
        }
