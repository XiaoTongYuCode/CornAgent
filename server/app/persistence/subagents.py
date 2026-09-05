"""Child queue/inbox transactions adapted from agent_server 1c934f0d6ed2.

Every mutation locks Root before Child. Provider/Redis I/O is forbidden here.
Child leases do not depend on Root lease ownership, which changes on every wait.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.subagents.protocol import TERMINAL_TASK_STATUSES, OperationRequest, SubagentOptions
from app.agent.tools.runtime import RuntimeToolCall
from app.persistence.agent_runtime import (
    TERMINAL_RUN_STATUSES,
    AgentRepository,
    _event,
    _merge_usage,
    _now,
    _run_out,
    _upsert_part,
    checkpoint_json_size_bytes,
    ensure_checkpoint_size,
)
from app.persistence.errors import DomainError
from app.persistence.models import AgentMessage, AgentRun, AgentSubagentTask


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def stable_id(kind: str, root_id: str, call_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"cornagent:{kind}:{root_id}:{call_id}"))


@dataclass
class CheckpointSpaceNeeded(Exception):
    run_id: str
    revision: int
    messages: list[dict[str, Any]]
    checkpoint: dict[str, Any]


def task_summary(task: AgentSubagentTask) -> dict[str, Any]:
    result = task.result_payload or {}
    duration = None
    if task.started_at:
        duration = max(
            0, int((utc(task.terminal_at or _now()) - utc(task.started_at)).total_seconds() * 1000)
        )
    return {
        "task_id": task.id,
        "group_id": task.group_id,
        "task_key": task.task_key,
        "title": task.task_payload["title"],
        "profile": task.profile,
        "status": task.status,
        "required": task.required,
        "duration_ms": duration,
        "attempt_count": task.attempt_count,
        "result_available": task.status in TERMINAL_TASK_STATUSES
        and task.delivery_status == "pending",
        "error_code": (result.get("error") or {}).get("type"),
        "preview": str(result.get("summary") or "")[:400],
    }


def task_part(task: AgentSubagentTask) -> dict[str, Any]:
    result = task.result_payload or {}
    sections = [str(result.get("summary") or "")]
    for item in result.get("evidence") or []:
        claim = str(item.get("claim") or "")
        source = str(item.get("source_title") or item.get("url") or "")
        # Keep provider text as plain Markdown data; never embed raw HTML.
        sections.append(f"- {claim}" + (f" — {source}" if source else ""))
    sections.extend(f"- {warning}" for warning in result.get("warnings") or [])
    if result.get("error"):
        sections.append(str(result["error"].get("message") or ""))
    content = "\n\n".join(section for section in sections if section)
    limit = int(task.task_payload.get("projection_max_chars", 8000))
    if len(content) > limit:
        content = content[: limit - 1].rstrip() + "…"
    return {
        "id": f"subagent-{task.id}",
        "kind": "tool_call",
        "title": task.task_payload["title"],
        "content": content,
        "metadata": {
            "subagent": True,
            "tool_name": "subagent",
            **task_summary(task),
            "delivery_status": task.delivery_status,
            "failed": task.status in {"failed", "timed_out"},
        },
    }


def merge_task_projections(db: Session, run: AgentRun) -> None:
    for task in db.scalars(
        select(AgentSubagentTask)
        .where(AgentSubagentTask.root_run_id == run.id)
        .order_by(AgentSubagentTask.created_at, AgentSubagentTask.ordinal)
    ):
        run.content_parts = _upsert_part(run.content_parts, task_part(task))


def settle_root_children(db: Session, run: AgentRun) -> None:
    """Called with the Root locked, before persisting a terminal Root message."""
    run.cancel_epoch += 1
    for task in db.scalars(
        select(AgentSubagentTask).where(AgentSubagentTask.root_run_id == run.id).with_for_update()
    ):
        if task.status not in TERMINAL_TASK_STATUSES:
            run.subagent_completion_seq += 1
            task.status = "cancelled"
            task.terminal_at = _now()
            task.completion_seq = run.subagent_completion_seq
            task.result_payload = {
                "status": "cancelled",
                "summary": "主任务已结束。",
                "evidence": [],
                "warnings": [],
                "usage": {},
            }
        if task.delivery_status == "pending":
            task.delivery_status = "ignored"
        task.lease_owner = None
        task.lease_expires_at = None
        run.content_parts = _upsert_part(run.content_parts, task_part(task))
    checkpoint = dict(run.checkpoint)
    wait = checkpoint.pop("subagent_wait", None)
    if wait:
        for part in run.content_parts:
            if part["id"] == f"tool-{wait['call_id']}":
                run.content_parts = _upsert_part(
                    run.content_parts,
                    {
                        **part,
                        "metadata": {**part["metadata"], "status": "cancelled"},
                    },
                )
    messages = list(checkpoint.get("provider_messages", []))
    if run.status in TERMINAL_RUN_STATUSES and messages and messages[-1].get("tool_calls"):
        # A cancelled wait must not leave an unmatched provider tool call in
        # the next user turn's historical context.
        for call in messages[-1]["tool_calls"]:
            messages.append(
                {
                    "role": "tool",
                    "name": call["function"]["name"],
                    "tool_call_id": call["id"],
                    "content": json.dumps(
                        {
                            "ok": False,
                            "status": "cancelled",
                            "reason": "parent_run_ended",
                        }
                    ),
                }
            )
        checkpoint["provider_messages"] = messages
        checkpoint["safe_provider_messages"] = messages
        try:
            ensure_checkpoint_size(checkpoint)
        except DomainError as exc:
            if exc.code != "agent_checkpoint_too_large":
                raise
            # Terminal runs never resume; the canonical history remains intact.
            checkpoint.pop("safe_provider_messages", None)
            checkpoint.pop("safe_content_parts", None)
            ensure_checkpoint_size(checkpoint)
    run.checkpoint = checkpoint
    run.checkpoint_revision += 1


def assert_finalizable(db: Session, run: AgentRun) -> None:
    for task in db.scalars(
        select(AgentSubagentTask).where(
            AgentSubagentTask.root_run_id == run.id, AgentSubagentTask.required.is_(True)
        )
    ):
        if task.status not in TERMINAL_TASK_STATUSES or task.delivery_status == "pending":
            raise DomainError(
                "subagents_required", "Required child results must be collected before finalizing."
            )


class SubagentRepository:
    def __init__(self, db: Session, options: SubagentOptions | None = None):
        self.db = db
        self.options = options or SubagentOptions()

    def _root(self, run_id: str, worker: str | None = None, fence: int | None = None) -> AgentRun:
        if worker is not None and fence is not None:
            return AgentRepository(self.db)._locked_leased_run(run_id, worker, fence)
        run = self.db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if (
            run is None
            or run.status in TERMINAL_RUN_STATUSES
            or run.cancel_requested_at is not None
        ):
            raise DomainError("subagent_root_finished", "The parent run is no longer active.")
        return run

    def _tasks(
        self, root: AgentRun, request: OperationRequest | None = None
    ) -> list[AgentSubagentTask]:
        tasks = list(
            self.db.scalars(
                select(AgentSubagentTask)
                .where(AgentSubagentTask.root_run_id == root.id)
                .order_by(AgentSubagentTask.created_at, AgentSubagentTask.ordinal)
            )
        )
        if request is None:
            return tasks
        selected = [
            task
            for task in tasks
            if (not request.group_id or task.group_id == request.group_id)
            and (not request.task_ids or task.id in request.task_ids)
        ]
        if request.task_ids and set(request.task_ids) != {task.id for task in selected}:
            raise DomainError(
                "invalid_subagent_selection", "Tasks must belong to this Root and requested group."
            )
        if request.group_id and not selected:
            raise DomainError("invalid_subagent_selection", "The subagent group is unavailable.")
        return selected

    def boundary(self, run_id: str, worker: str, fence: int) -> dict[str, Any]:
        run = self._root(run_id, worker, fence)
        tasks = self._tasks(run)
        blocked = [
            task.id
            for task in tasks
            if task.required
            and (task.status not in TERMINAL_TASK_STATUSES or task.delivery_status == "pending")
        ]
        available = sum(
            task.status in TERMINAL_TASK_STATUSES and task.delivery_status == "pending"
            for task in tasks
        )
        pending = sum(task.status not in TERMINAL_TASK_STATUSES for task in tasks)
        return {
            "blocked_task_ids": blocked,
            "available": available,
            "pending": pending,
            "blocked_ready_task_ids": [
                task.id
                for task in tasks
                if task.id in blocked and task.status in TERMINAL_TASK_STATUSES
            ],
            "blocked_pending_task_ids": [
                task.id
                for task in tasks
                if task.id in blocked and task.status not in TERMINAL_TASK_STATUSES
            ],
        }

    def _spawn(
        self, root: AgentRun, call_id: str, request: OperationRequest
    ) -> list[AgentSubagentTask]:
        group_id = stable_id("group", root.id, call_id)
        all_tasks = self._tasks(root)
        existing = [task for task in all_tasks if task.group_id == group_id]
        if existing:
            if [task.task_payload["spec"] for task in existing] != [
                task.to_payload() for task in request.tasks
            ]:
                raise DomainError("subagent_call_conflict", "Repeated tool call changed its tasks.")
            return existing
        if not self.options.enabled:
            raise DomainError("subagents_disabled", "New subagent dispatch is disabled.")
        if (
            len(request.tasks) > self.options.spawn_max_tasks
            or len(all_tasks) + len(request.tasks) > self.options.run_max_tasks
        ):
            raise DomainError("subagent_task_limit", "The subagent task limit has been reached.")
        created = []
        for spec in request.tasks:
            task = AgentSubagentTask(
                id=stable_id("task", root.id, f"{call_id}:{spec.ordinal}"),
                root_run_id=root.id,
                group_id=group_id,
                tool_call_id=call_id,
                task_key=spec.task_key,
                ordinal=spec.ordinal,
                profile=spec.profile,
                required=spec.required,
                task_payload={
                    "spec": spec.to_payload(),
                    "title": spec.title,
                    "max_concurrency": min(
                        request.max_concurrency, self.options.run_max_concurrency
                    ),
                    "projection_max_chars": self.options.result_projection_max_chars,
                },
                status="queued",
                deadline_at=_now() + timedelta(seconds=self.options.timeout_seconds),
                root_cancel_epoch=root.cancel_epoch,
            )
            self.db.add(task)
            created.append(task)
        self.db.flush()
        return created

    def _payload(
        self,
        root: AgentRun,
        operation: str,
        tasks: list[AgentSubagentTask],
        *,
        collect: bool,
        timed_out: bool = False,
    ) -> tuple[dict[str, Any], list[AgentSubagentTask]]:
        ready = sorted(
            (
                task
                for task in tasks
                if task.status in TERMINAL_TASK_STATUSES and task.delivery_status == "pending"
            ),
            key=lambda task: task.completion_seq or 0,
        )
        pending = [task.id for task in tasks if task.status not in TERMINAL_TASK_STATUSES]
        selected: list[AgentSubagentTask] = []
        results: list[dict[str, Any]] = []
        base = {
            "ok": True,
            "operation": operation,
            "root_run_id": root.id,
            "group_id": tasks[0].group_id
            if tasks and len({task.group_id for task in tasks}) == 1
            else None,
            "tasks": [task_summary(task) for task in tasks],
            "timed_out": timed_out,
        }
        if collect:
            for task in ready:
                result = {
                    **(task.result_payload or {}),
                    "task_id": task.id,
                    "group_id": task.group_id,
                    "task_key": task.task_key,
                    "status": task.status,
                    "completion_seq": task.completion_seq,
                }
                if checkpoint_json_size_bytes(result) > 3 * 1024 * 1024:
                    raise DomainError(
                        "subagent_result_too_large",
                        "A child result exceeds the durable checkpoint limit.",
                    )
                if (
                    selected
                    and checkpoint_json_size_bytes({**base, "results": [*results, result]})
                    > self.options.result_batch_max_bytes
                ):
                    break
                selected.append(task)
                results.append(result)
        remaining = [task.id for task in ready if task not in selected]
        action = (
            "collect_subagent_results" if remaining else "wait_subagents" if pending else "none"
        )
        return {
            **base,
            "results": results,
            "pending_task_ids": pending,
            "undelivered_result_task_ids": remaining,
            "next_action": action,
            "next_action_task_ids": remaining if remaining else pending,
        }, selected

    @staticmethod
    def _wait_ready(tasks: list[AgentSubagentTask], return_when: str) -> bool:
        terminal = [task.status in TERMINAL_TASK_STATUSES for task in tasks]
        return all(terminal) if return_when == "all" else any(terminal)

    def _save(
        self,
        root: AgentRun,
        messages: list[dict[str, Any]],
        *,
        closed_messages: list[dict[str, Any]],
        selected: list[AgentSubagentTask],
        part: dict[str, Any],
        active_wait: dict[str, Any] | None,
        context_state: dict[str, Any],
        usage: dict[str, Any],
    ) -> list[dict[str, Any]]:
        root.content_parts = _upsert_part(root.content_parts, part)
        for task in selected:
            task.delivery_status = "delivered"
            task.delivered_at = _now()
            task.delivery_checkpoint_revision = root.checkpoint_revision + 1
        merge_task_projections(self.db, root)
        checkpoint = dict(root.checkpoint)
        checkpoint.update(
            {
                "provider_messages": messages,
                "safe_provider_messages": messages,
                "safe_draft_markdown": root.draft_markdown,
                "safe_reasoning_markdown": root.reasoning_markdown,
                "safe_content_parts": root.content_parts,
                "content_parts": root.content_parts,
                "tool_context_state": context_state,
                "tool_context_state_version": 1,
            }
        )
        if active_wait:
            checkpoint["subagent_wait"] = active_wait
        else:
            checkpoint.pop("subagent_wait", None)
        try:
            ensure_checkpoint_size(checkpoint)
        except DomainError as exc:
            if exc.code != "agent_checkpoint_too_large":
                raise
            raise CheckpointSpaceNeeded(
                root.id, root.checkpoint_revision, closed_messages, dict(root.checkpoint)
            ) from exc
        root.checkpoint = checkpoint
        root.checkpoint_revision += 1
        root.provider_usage = _merge_usage(root.provider_usage, usage)
        if active_wait:
            root.status = "waiting_for_subagents"
            root.lease_owner = None
            root.lease_expires_at = None
        assistant = self.db.get(AgentMessage, root.assistant_message_id)
        assert assistant is not None
        assistant.content_parts = root.content_parts
        assistant.markdown = root.draft_markdown
        assistant.updated_at = _now()
        parts = [part, *(task_part(task) for task in self._tasks(root))]
        events = [_event(root, "tool_call", item) for item in parts]
        events.append(
            _event(
                root,
                "session",
                {
                    "run": _run_out(root).model_dump(mode="json"),
                    "run_id": root.id,
                    "session_id": root.session_id,
                },
            )
        )
        self.db.commit()
        return events

    @staticmethod
    def _control_part(
        call_id: str, name: str, waiting: bool, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "id": f"tool-{call_id}",
            "kind": "tool_call",
            "title": name,
            "content": "",
            "metadata": {
                "tool_name": name,
                "tool_call_id": call_id,
                "operation": name,
                "status": "waiting" if waiting else "completed",
                "group_id": payload.get("group_id"),
                "task_count": len(payload.get("tasks", [])),
                "pending_count": len(payload.get("pending_task_ids", [])),
                "undelivered_count": len(payload.get("undelivered_result_task_ids", [])),
                "timed_out": payload.get("timed_out", False),
            },
        }

    def operate(
        self,
        call: RuntimeToolCall,
        request: OperationRequest,
        *,
        expected_revision: int | None = None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        root = self._root(call.run_id, call.worker_id, call.fence)
        if expected_revision is not None and root.checkpoint_revision != expected_revision:
            raise DomainError(
                "subagent_checkpoint_conflict", "Root checkpoint changed during compaction."
            )
        # The durable provider pair is the idempotency receipt; tasks alone are not.
        for message in root.checkpoint.get("provider_messages", []):
            if message.get("role") == "tool" and message.get("tool_call_id") == call.tool_call_id:
                return "continue", list(root.checkpoint["provider_messages"]), []
        tasks = (
            self._spawn(root, call.tool_call_id, request)
            if request.tasks
            else self._tasks(root, request)
        )
        if request.tasks:
            request = replace(
                request, task_ids=tuple(task.id for task in tasks), group_id=tasks[0].group_id
            )
        waiting = request.name in {"wait_subagents", "delegate_tasks"} and not self._wait_ready(
            tasks, request.return_when
        )
        payload, selected = self._payload(
            root,
            request.name,
            tasks,
            collect=not waiting
            and request.name in {"collect_subagent_results", "wait_subagents", "delegate_tasks"},
        )
        assistant = {
            "role": "assistant",
            "content": call.round_content or None,
            "tool_calls": call.normalized_calls,
        }
        if call.round_reasoning:
            assistant["reasoning_content"] = call.round_reasoning
        messages = [*call.provider_messages, assistant]
        active_wait = None
        if waiting:
            active_wait = {
                "call_id": call.tool_call_id,
                "name": request.name,
                "task_ids": list(request.task_ids),
                "return_when": request.return_when,
                "deadline_at": (_now() + timedelta(seconds=request.timeout_seconds)).isoformat(),
            }
        else:
            messages.append(
                {
                    "role": "tool",
                    "name": request.name,
                    "tool_call_id": call.tool_call_id,
                    "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                }
            )
        events = self._save(
            root,
            messages,
            closed_messages=call.provider_messages,
            selected=selected,
            part=self._control_part(call.tool_call_id, request.name, waiting, payload),
            active_wait=active_wait,
            context_state=call.context.checkpoint_state,
            usage=call.usage,
        )
        return "waiting_for_subagents" if waiting else "continue", messages, events

    def waiting_ids(self) -> list[str]:
        return list(
            self.db.scalars(select(AgentRun.id).where(AgentRun.status == "waiting_for_subagents"))
        )

    def resume_wait(
        self,
        run_id: str,
        *,
        compacted_messages: list[dict[str, Any]] | None = None,
        expected_revision: int | None = None,
    ) -> list[dict[str, Any]]:
        root = self._root(run_id)
        if root.status != "waiting_for_subagents":
            return []
        if expected_revision is not None and root.checkpoint_revision != expected_revision:
            raise DomainError(
                "subagent_checkpoint_conflict", "Root checkpoint changed during compaction."
            )
        wait = root.checkpoint.get("subagent_wait")
        if not isinstance(wait, dict):
            raise DomainError("subagent_wait_invalid", "Durable wait continuation is missing.")
        request = OperationRequest(
            wait["name"], task_ids=tuple(wait["task_ids"]), return_when=wait["return_when"]
        )
        tasks = self._tasks(root, request)
        timed_out = datetime.fromisoformat(wait["deadline_at"]) <= _now()
        if not timed_out and not self._wait_ready(tasks, request.return_when):
            return []
        payload, selected = self._payload(
            root, request.name, tasks, collect=True, timed_out=timed_out
        )
        original = list(root.checkpoint["provider_messages"])
        messages = [
            *(compacted_messages if compacted_messages is not None else original[:-1]),
            original[-1],
            {
                "role": "tool",
                "name": request.name,
                "tool_call_id": wait["call_id"],
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ]
        root.status = "pending"
        root.stream_epoch += 1
        root.next_sequence = 1
        return self._save(
            root,
            messages,
            closed_messages=original[:-1],
            selected=selected,
            part=self._control_part(wait["call_id"], request.name, False, payload),
            active_wait=None,
            context_state=dict(root.checkpoint.get("tool_context_state") or {}),
            usage={},
        )

    def queued_ids(self, limit: int) -> list[str]:
        return list(
            self.db.scalars(
                select(AgentSubagentTask.id)
                .where(AgentSubagentTask.status == "queued")
                .order_by(AgentSubagentTask.created_at, AgentSubagentTask.ordinal)
                .limit(limit)
            )
        )

    def _task_root_id(self, task_id: str) -> str | None:
        return self.db.scalar(
            select(AgentSubagentTask.root_run_id).where(AgentSubagentTask.id == task_id)
        )

    def claim(
        self, task_id: str, worker: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        root_id = self._task_root_id(task_id)
        if root_id is None:
            return None
        root = self._root(root_id)
        task = self.db.scalar(
            select(AgentSubagentTask).where(AgentSubagentTask.id == task_id).with_for_update()
        )
        if (
            task is None
            or task.status != "queued"
            or utc(task.deadline_at) <= _now()
            or task.root_cancel_epoch != root.cancel_epoch
        ):
            return None
        running = [
            item
            for item in self._tasks(root)
            if item.status == "running"
            and item.lease_expires_at
            and utc(item.lease_expires_at) > _now()
        ]
        if (
            len(running) >= self.options.run_max_concurrency
            or sum(item.group_id == task.group_id for item in running)
            >= task.task_payload["max_concurrency"]
        ):
            return None
        task.status = "running"
        task.lease_owner = worker
        task.lease_fence += 1
        task.attempt_count += 1
        task.lease_expires_at = _now() + timedelta(seconds=30)
        task.started_at = task.started_at or _now()
        task.updated_at = _now()
        events = self._project(root, task)
        snapshot = {
            "id": task.id,
            "root_run_id": root.id,
            "session_id": root.session_id,
            "tenant_id": root.tenant_id,
            "owner_membership_id": root.owner_membership_id,
            "group_id": task.group_id,
            "spec": dict(task.task_payload["spec"]),
            "fence": task.lease_fence,
            "deadline_at": utc(task.deadline_at),
            "attempt": task.attempt_count,
        }
        self.db.commit()
        return snapshot, events

    def _project(self, root: AgentRun, task: AgentSubagentTask) -> list[dict[str, Any]]:
        part = task_part(task)
        root.content_parts = _upsert_part(root.content_parts, part)
        checkpoint = dict(root.checkpoint)
        checkpoint["content_parts"] = root.content_parts
        # Child projections survive rollback of a half-generated Root model turn.
        checkpoint["safe_content_parts"] = _upsert_part(
            list(checkpoint.get("safe_content_parts", [])), part
        )
        try:
            ensure_checkpoint_size(checkpoint)
        except DomainError as exc:
            if exc.code != "agent_checkpoint_too_large":
                raise
            # Result durability must not depend on space in the Root's draft.
            # Snapshots use root.content_parts; recovery rebuilds the projection
            # from task rows. Collection will compact history or fail explicitly.
        else:
            root.checkpoint = checkpoint
        root.checkpoint_revision += 1
        assistant = self.db.get(AgentMessage, root.assistant_message_id)
        assert assistant is not None
        assistant.content_parts = root.content_parts
        assistant.updated_at = _now()
        return [_event(root, "tool_call", part)]

    def renew(self, task_id: str, worker: str, fence: int) -> bool:
        root_id = self._task_root_id(task_id)
        if root_id is None:
            return False
        root = self._root(root_id)
        task = self.db.scalar(
            select(AgentSubagentTask).where(AgentSubagentTask.id == task_id).with_for_update()
        )
        if not self._matches(root, task, worker, fence):
            return False
        assert task is not None
        task.lease_expires_at = _now() + timedelta(seconds=30)
        self.db.commit()
        return True

    @staticmethod
    def _matches(root: AgentRun, task: AgentSubagentTask | None, worker: str, fence: int) -> bool:
        return bool(
            task
            and task.status == "running"
            and task.lease_owner == worker
            and task.lease_fence == fence
            and task.root_cancel_epoch == root.cancel_epoch
            and task.lease_expires_at
            and utc(task.lease_expires_at) > _now()
            and utc(task.deadline_at) > _now()
        )

    def finish(
        self, task_id: str, worker: str, fence: int, result: dict[str, Any]
    ) -> list[dict[str, Any]]:
        root_id = self._task_root_id(task_id)
        if root_id is None:
            return []
        root = self._root(root_id)
        task = self.db.scalar(
            select(AgentSubagentTask).where(AgentSubagentTask.id == task_id).with_for_update()
        )
        if not self._matches(root, task, worker, fence):
            return []
        assert task is not None
        if result["status"] not in TERMINAL_TASK_STATUSES:
            raise ValueError("Child result must be terminal.")
        self._terminal(root, task, result)
        events = self._project(root, task)
        self.db.commit()
        return events

    @staticmethod
    def _terminal(root: AgentRun, task: AgentSubagentTask, result: dict[str, Any]) -> None:
        root.subagent_completion_seq += 1
        task.result_payload = result
        task.status = result["status"]
        task.completion_seq = root.subagent_completion_seq
        task.terminal_at = _now()
        task.updated_at = _now()
        task.lease_owner = None
        task.lease_expires_at = None

    def recover(self) -> list[tuple[str, list[dict[str, Any]]]]:
        root_ids = list(
            self.db.scalars(
                select(AgentSubagentTask.root_run_id)
                .where(AgentSubagentTask.status.in_(("queued", "running")))
                .distinct()
            )
        )
        changes = []
        for root_id in sorted(root_ids):
            root = self.db.scalar(
                select(AgentRun).where(AgentRun.id == root_id).with_for_update(skip_locked=True)
            )
            if root is None:
                continue
            events = []
            for task in self._tasks(root):
                if task.status in TERMINAL_TASK_STATUSES:
                    continue
                if (
                    root.status in TERMINAL_RUN_STATUSES
                    or task.root_cancel_epoch != root.cancel_epoch
                ):
                    self._terminal(
                        root,
                        task,
                        {
                            "status": "cancelled",
                            "summary": "主任务已结束。",
                            "evidence": [],
                            "warnings": [],
                            "usage": {},
                        },
                    )
                    task.delivery_status = "ignored"
                elif utc(task.deadline_at) <= _now():
                    self._terminal(
                        root,
                        task,
                        {
                            "status": "timed_out",
                            "summary": "子任务达到执行时限。",
                            "evidence": [],
                            "warnings": [],
                            "usage": {},
                            "error": {
                                "type": "SubagentTimeout",
                                "message": "Child execution deadline elapsed.",
                            },
                        },
                    )
                elif (
                    task.status == "running"
                    and task.lease_expires_at
                    and utc(task.lease_expires_at) <= _now()
                ):
                    task.status = "queued"
                    task.lease_owner = None
                    task.lease_expires_at = None
                    task.lease_fence += 1
                else:
                    continue
                events.extend(self._project(root, task))
            if events:
                changes.append((root.id, events))
            self.db.commit()
        return changes

    def live_claims(self, worker: str) -> dict[str, int]:
        return dict(
            self.db.execute(
                select(AgentSubagentTask.id, AgentSubagentTask.lease_fence)
                .join(AgentRun, AgentRun.id == AgentSubagentTask.root_run_id)
                .where(
                    AgentSubagentTask.lease_owner == worker,
                    AgentSubagentTask.status == "running",
                    AgentSubagentTask.lease_expires_at > _now(),
                    AgentSubagentTask.deadline_at > _now(),
                    AgentSubagentTask.root_cancel_epoch == AgentRun.cancel_epoch,
                    AgentRun.status.not_in(TERMINAL_RUN_STATUSES),
                )
            ).all()
        )
