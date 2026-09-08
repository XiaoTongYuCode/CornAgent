"""Schedules durable child work using the Root runtime's execution slots."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from app.agent.model import AgentModelConfigurationError
from app.agent.subagents.protocol import SubagentOptions
from app.agent.subagents.runner import ChildAgentRunner
from app.agent.subagents.tools import parse_operation
from app.agent.tools import RuntimeToolCall, RuntimeToolOutcome
from app.persistence.agent_runtime import AgentRepository, _now
from app.persistence.errors import DomainError
from app.persistence.subagents import CheckpointSpaceNeeded, SubagentRepository

if TYPE_CHECKING:
    from app.agent.runtime import AgentRuntime

logger = logging.getLogger(__name__)


class SubagentRuntime:
    def __init__(self, root: AgentRuntime, runner: ChildAgentRunner, options: SubagentOptions):
        self.root = root
        self.runner = runner
        self.options = options
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.claims: dict[str, dict[str, Any]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.loop_task: asyncio.Task[None] | None = None
        self.closing = False

    async def db(self, operation: Callable[[SubagentRepository], Any]) -> Any:
        def invoke():
            with self.root.session_factory() as db:
                return operation(SubagentRepository(db, self.options))

        return await asyncio.to_thread(invoke)

    def start(self) -> None:
        self.loop_task = asyncio.create_task(self._loop(), name="cornagent-subagents-reconciler")

    async def close(self) -> None:
        self.closing = True
        tasks = [*self.tasks.values(), *([self.loop_task] if self.loop_task else [])]
        for event in self.cancel_events.values():
            event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel_root(self, root_id: str) -> None:
        cancelled = []
        for task_id, claim in list(self.claims.items()):
            if claim["root_run_id"] == root_id and task_id in self.tasks:
                self.cancel_events[task_id].set()
                self.tasks[task_id].cancel()
                cancelled.append(self.tasks[task_id])
        if cancelled:
            await asyncio.gather(*cancelled, return_exceptions=True)

    async def handle(self, call: RuntimeToolCall) -> RuntimeToolOutcome:
        request = parse_operation(
            call.definition.name,
            call.arguments,
            call.tool_call_id,
            wait_default_seconds=self.options.wait_default_seconds,
        )
        expected_revision = None
        compacted = False
        while True:
            try:
                status, messages, events = await self.db(
                    lambda repo, call=call, expected_revision=expected_revision: repo.operate(
                        call, request, expected_revision=expected_revision
                    )
                )
                for event in events:
                    await self.root._publish(call.run_id, event)
                self.root.metrics.increment(
                    "cornagent_subagent_operations_total", operation=request.name, outcome=status
                )
                # The transaction is already committed. Reconciliation remains authoritative.
                return RuntimeToolOutcome(status, messages if status == "continue" else None)
            except CheckpointSpaceNeeded as exc:
                if compacted:
                    raise DomainError(
                        "subagent_result_too_large",
                        "Complete child results cannot fit the durable checkpoint.",
                    ) from exc
                messages = await self._compact(exc)
                call = replace(call, provider_messages=messages)
                expected_revision = exc.revision
                compacted = True
            except DomainError as exc:
                if exc.code != "subagent_checkpoint_conflict":
                    raise
                # Child projections can advance the revision while compaction runs.
                # Refresh the Root history and compact again without any row locks.
                state = await self.root._db(
                    lambda repo, call=call: repo.runtime_state(
                        call.run_id, call.worker_id, call.fence
                    )
                )
                call = replace(
                    call, provider_messages=list(state["checkpoint"]["provider_messages"])
                )
                expected_revision = None
                compacted = False

    async def _compact(self, error: CheckpointSpaceNeeded) -> list[dict[str, Any]]:
        assert self.root.context_manager is not None
        messages, _ = await self.root.context_manager.fit(
            error.messages,
            error.checkpoint,
            tool_context_state=dict(error.checkpoint.get("tool_context_state") or {}),
            trigger="subagent_result_delivery",
            force=True,
        )
        return messages

    async def _resume(self, run_id: str) -> None:
        compacted = None
        revision = None
        while True:
            try:
                events = await self.db(
                    lambda repo, compacted=compacted, revision=revision: repo.resume_wait(
                        run_id, compacted_messages=compacted, expected_revision=revision
                    )
                )
                for event in events:
                    await self.root._publish(run_id, event)
                if events:
                    self.root.metrics.increment("cornagent_subagent_wait_resumes_total")
                    self.root.kick(run_id)
                return
            except CheckpointSpaceNeeded as exc:
                if compacted is not None:
                    await self._fail_wait(
                        run_id,
                        exc.revision,
                        "subagent_result_too_large",
                        "Complete child results cannot fit the durable checkpoint.",
                    )
                    return
                try:
                    compacted = await self._compact(exc)
                    revision = exc.revision
                except DomainError as failure:
                    await self._fail_wait(run_id, exc.revision, failure.code, failure.message)
                    return
                except Exception:
                    logger.exception("Subagent wait context compaction failed")
                    await self._fail_wait(
                        run_id,
                        exc.revision,
                        "agent_context_compaction_failed",
                        "The model could not compact history to deliver complete child results.",
                    )
                    return
            except DomainError as exc:
                if exc.code == "subagent_checkpoint_conflict":
                    compacted = None
                    revision = None
                    continue
                if exc.code in {"subagent_root_finished", "agent_lease_lost"}:
                    return
                if exc.code == "subagent_result_too_large":
                    await self._fail_wait(run_id, revision, exc.code, exc.message)
                    return
                raise

    async def _fail_wait(self, run_id: str, revision: int | None, code: str, message: str) -> None:
        def fail(repo: SubagentRepository):
            root = repo._root(run_id)
            if root.status != "waiting_for_subagents" or (
                revision is not None and root.checkpoint_revision != revision
            ):
                return None
            return AgentRepository(repo.db).fail_run(run_id, code=code, message=message)

        try:
            event = await self.db(fail)
        except DomainError as exc:
            if exc.code == "subagent_root_finished":
                return
            raise
        if event:
            await self.root._publish(run_id, event)
            await self.cancel_root(run_id)

    async def reconcile_once(self) -> None:
        for root_id, events in await self.db(lambda repo: repo.recover()):
            for event in events:
                await self.root._publish(root_id, event)
            self.root.metrics.increment("cornagent_subagent_recoveries_total")
        live = await self.db(lambda repo: repo.live_claims(self.root.worker_id))
        for task_id, claim in list(self.claims.items()):
            if live.get(task_id) != claim["fence"] and task_id in self.tasks:
                self.cancel_events[task_id].set()
                self.tasks[task_id].cancel()
        for run_id in await self.db(lambda repo: repo.waiting_ids()):
            await self._resume(run_id)
        for task_id in await self.db(lambda repo: repo.queued_ids(self.root.max_concurrency * 5)):
            if task_id not in self.tasks:
                task = asyncio.create_task(
                    self._execute(task_id), name=f"cornagent-child-{task_id}"
                )
                self.tasks[task_id] = task
                task.add_done_callback(lambda done, key=task_id: self._finished(key, done))

    def _finished(self, task_id: str, task: asyncio.Task[None]) -> None:
        self.tasks.pop(task_id, None)
        self.claims.pop(task_id, None)
        self.cancel_events.pop(task_id, None)
        if not task.cancelled() and task.exception():
            logger.error(
                "Child worker failed; durable reconciliation will recover it",
                exc_info=task.exception(),
            )

    async def _loop(self) -> None:
        while not self.closing:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Subagent reconciliation failed; will retry")
            await asyncio.sleep(self.options.reconcile_seconds)

    async def _execute(self, task_id: str) -> None:
        async with self.root._execution_slots:
            try:
                claimed = await self.db(lambda repo: repo.claim(task_id, self.root.worker_id))
            except DomainError as exc:
                if exc.code == "subagent_root_finished":
                    return
                raise
            if claimed is None:
                return
            claim, events = claimed
            self.claims[task_id] = claim
            cancellation = self.cancel_events.setdefault(task_id, asyncio.Event())
            current = asyncio.current_task()
            assert current is not None
            heartbeat = asyncio.create_task(self._heartbeat(claim, current, cancellation))
            started = time.monotonic()
            self.root.metrics.increment("cornagent_subagent_attempts_total")
            self.root.metrics.child_started()
            try:
                for event in events:
                    await self.root._publish(claim["root_run_id"], event)
                try:
                    remaining = max(0.001, (claim["deadline_at"] - _now()).total_seconds())
                    async with asyncio.timeout(remaining):
                        result = await self.runner.run(claim, cancellation)
                except TimeoutError:
                    # The original deadline is authoritative; recover() creates timed_out.
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    result = {
                        "status": "failed",
                        "summary": str(exc)
                        if isinstance(exc, AgentModelConfigurationError)
                        else "子任务执行失败。",
                        "evidence": [],
                        "warnings": [],
                        "usage": {},
                        "error": {
                            "type": "agent_model_configuration_error"
                            if isinstance(exc, AgentModelConfigurationError)
                            else exc.code
                            if isinstance(exc, DomainError)
                            else type(exc).__name__,
                            "message": str(exc)
                            if isinstance(exc, AgentModelConfigurationError)
                            else exc.message
                            if isinstance(exc, DomainError)
                            else "The child could not complete its task.",
                        },
                    }
                events = await self.db(
                    lambda repo: repo.finish(task_id, self.root.worker_id, claim["fence"], result)
                )
                for event in events:
                    await self.root._publish(claim["root_run_id"], event)
                if events:
                    self.root.metrics.increment(
                        "cornagent_subagent_finished_total", status=result["status"]
                    )
                    await self._resume(claim["root_run_id"])
            except DomainError as exc:
                if exc.code != "subagent_root_finished":
                    raise
            finally:
                self.root.metrics.child_finished()
                self.root.metrics.observe_duration(
                    "cornagent_subagent_attempt", time.monotonic() - started
                )
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat

    async def _heartbeat(
        self, claim: dict[str, Any], task: asyncio.Task[None], cancellation: asyncio.Event
    ) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                renewed = await self.db(
                    lambda repo: repo.renew(claim["id"], self.root.worker_id, claim["fence"])
                )
            except Exception:
                renewed = False
            if not renewed:
                cancellation.set()
                task.cancel()
                return
