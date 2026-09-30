"""Resumable tool approval primitive; persistence stays inside fenced repository calls."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from app.agent.outcomes import operation_metadata
from app.agent.tools import RuntimeToolCall, RuntimeToolOutcome, ToolApproval, ToolExecutionContext
from app.persistence.errors import DomainError


class ApprovalRuntimeMixin:
    """Plan, persist decision and execute according to the tool's replay policy."""

    async def _prepare_tool_approval(self, call: RuntimeToolCall) -> RuntimeToolOutcome:
        found, result = await self._replay_tool_result(
            call.run_id, call.fence, call.tool_call_id, call.definition.name, call.arguments
        )
        if not found:
            result = await self.tool_executor.execute_tool(
                call.definition.name,
                call.arguments,
                context=call.context,
            )
        messages = [
            *call.provider_messages,
            self._assistant_tool_call_message(
                round_content=call.round_content,
                round_reasoning=call.round_reasoning,
                tool_calls=call.normalized_calls,
            ),
        ]
        pending = {
            "tool_name": call.definition.name,
            "tool_call": call.normalized_calls[0],
            "arguments": call.arguments,
            "replay_safe": call.definition.approval_replay_safe,
        }
        if isinstance(result, ToolApproval):
            await self._pause_tool_approval(
                call.run_id, call.fence, pending, result, messages, call.context, call.usage
            )
            return RuntimeToolOutcome("waiting_for_user")
        completed = await self._complete_tool_approval(
            call.run_id,
            call.fence,
            pending,
            result,
            messages,
            usage=call.usage,
        )
        return RuntimeToolOutcome("continue", completed)

    async def _pause_tool_approval(
        self,
        run_id: str,
        fence: int,
        pending: dict[str, Any],
        approval: ToolApproval,
        messages: list[dict[str, Any]],
        context: ToolExecutionContext,
        usage: dict[str, Any] | None = None,
    ) -> None:
        event, _ = await self._db(
            lambda repo: repo.pause_for_question(
                run_id,
                self.worker_id,
                fence,
                tool_call_id=pending["tool_call"]["id"],
                arguments={"query": approval.query, "options": approval.options},
                provider_messages=messages,
                usage=usage or {},
                tool_context_state=context.checkpoint_state,
                approval={**pending, "payload": approval.payload},
            )
        )
        await self._publish(run_id, event)

    async def _resume_tool_approval(
        self,
        run_id: str,
        fence: int,
        pending: dict[str, Any],
        messages: list[dict[str, Any]],
        context: ToolExecutionContext,
    ) -> list[dict[str, Any]] | None:
        definition = self.tool_catalog.get(pending["tool_name"])
        if definition is None or definition.approval_handler is None:
            raise DomainError("agent_approval_unavailable", "待执行的工具已不可用。")
        call_context = context.for_tool(
            tool_call_id=pending["tool_call"]["id"],
            batch_id=f"approval-{pending['tool_call']['id']}",
        )
        # Persisted policy may only become more restrictive after a restart.
        replay_safe = definition.approval_replay_safe and pending.get("replay_safe", True)
        pending = {**pending, "replay_safe": replay_safe}
        if pending["decision"] == "rejected":
            result = {
                "ok": True,
                "outcome": "cancelled",
                "message": "用户取消了本次操作，请勿再次请求执行同一操作。",
            }
        elif pending["decision"] == "approved":
            title = definition.build_status(pending["arguments"]).get("status") or "正在执行操作"
            part = self._tool_call_part(
                call=pending["tool_call"],
                title=title,
                content=title,
                status="running",
                arguments=pending["arguments"],
            )
            part["metadata"].update(operation_metadata(definition, None))
            if replay_safe:
                events = await self._db(
                    lambda repo: repo.persist_tool_call_parts(
                        run_id, self.worker_id, fence, parts=[part]
                    )
                )
            else:
                # Commit the existing no-replay boundary before any external IO.
                # Recovery fails the Run if no receipt commits after this marker.
                events = await self._db(
                    lambda repo: repo.persist_ordinary_tool_batch(
                        run_id,
                        self.worker_id,
                        fence,
                        batch_id=call_context.batch_id,
                        phase="executing",
                        tool_calls=[pending["tool_call"]],
                        parts=[part],
                        tool_context_state=context.checkpoint_state,
                    )
                )
            for event in events:
                await self._publish(run_id, event)
            attempts = 3 if replay_safe else 1
            for attempt in range(attempts):
                call_context.raise_if_cancelled()
                try:
                    result = definition.validate_result(
                        await self.tool_executor.invoke_approval(
                            definition, pending["payload"], call_context
                        )
                    )
                except (TimeoutError, ConnectionError, OSError):
                    result = {
                        "ok": False,
                        "retryable": replay_safe,
                        "write_state": "unknown",
                        "message": "操作暂未完成，请稍后重试。",
                    }
                except Exception as exc:  # A tool failure must not become a provider error.
                    result = {
                        "ok": False,
                        "write_state": "unknown",
                        "error_code": type(exc).__name__,
                        "message": "操作未完成。",
                    }
                if isinstance(result, ToolApproval):
                    if not replay_safe:
                        raise DomainError(
                            "agent_approval_indeterminate",
                            "不可重放的写工具执行后不能再次请求审批，请核实远端结果。",
                        )
                    await self._pause_tool_approval(
                        run_id, fence, pending, result, messages, context
                    )
                    return None
                if (
                    not isinstance(result, Mapping)
                    or not result.get("retryable")
                    or attempt == attempts - 1
                ):
                    break
                await asyncio.sleep(0.25 * (attempt + 1))
        else:
            raise DomainError("agent_approval_missing", "此操作尚未获得确认。")
        return await self._complete_tool_approval(run_id, fence, pending, result, messages)

    async def _complete_tool_approval(
        self,
        run_id: str,
        fence: int,
        pending: dict[str, Any],
        result: Any,
        messages: list[dict[str, Any]],
        *,
        usage: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        definition = self.tool_catalog.get(pending["tool_name"])
        assert definition is not None
        failed = isinstance(result, Mapping) and result.get("ok") is False
        cancelled = isinstance(result, Mapping) and result.get("outcome") == "cancelled"
        title = (
            "已取消操作"
            if cancelled
            else self._finalize_tool_title(
                definition.build_status(pending["arguments"]).get("status") or "操作",
                failed=failed,
            )
        )
        public_result = definition.project_result(result)
        part = self._tool_call_part(
            call=pending["tool_call"],
            title=title,
            content=definition.present_result(
                result, self._summarize_tool_result(self._serialize_tool_result(public_result))
            ),
            status="failed" if failed else "completed",
            arguments=pending["arguments"],
            result=public_result,
            failed=failed,
        )
        part["metadata"].update(operation_metadata(definition, result))
        next_messages = [
            *messages,
            {
                "role": "tool",
                "name": definition.name,
                "tool_call_id": pending["tool_call"]["id"],
                "content": self._serialize_tool_result(result),
            },
        ]
        no_replay_execution = (
            pending.get("decision") == "approved" and pending.get("replay_safe") is False
        )
        persist_options = dict(
            parts=[part],
            usage=usage,
            provider_messages=next_messages,
            complete_approval=True,
            receipts=[
                {
                    "call_id": pending["tool_call"]["id"],
                    "tool_name": definition.name,
                    "arguments": pending["arguments"],
                    "result": result,
                    "read_only": definition.read_only,
                    "private_result": definition.private_result,
                    "public_result": public_result,
                }
            ],
        )
        if no_replay_execution:
            events = await self._db(
                lambda repo: repo.persist_ordinary_tool_batch(
                    run_id,
                    self.worker_id,
                    fence,
                    batch_id=f"approval-{pending['tool_call']['id']}",
                    phase="completed",
                    tool_calls=[pending["tool_call"]],
                    tool_context_state=dict(
                        repo.runtime_state(run_id, self.worker_id, fence)["checkpoint"].get(
                            "tool_context_state"
                        )
                        or {}
                    ),
                    **persist_options,
                )
            )
        else:
            events = await self._db(
                lambda repo: repo.persist_tool_call_parts(
                    run_id,
                    self.worker_id,
                    fence,
                    advance_safe_checkpoint=True,
                    **persist_options,
                )
            )
        for event in events:
            await self._publish(run_id, event)
        return next_messages
