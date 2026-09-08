"""An isolated, read-only child conversation using CornAgent's model adapter."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.context import AgentContextManager
from app.agent.metrics import AgentMetrics
from app.agent.model import AgentModelClient
from app.agent.subagents.prompt import CHILD_AGENT_SYSTEM_PROMPT, MOCK_EVIDENCE_RULE
from app.agent.tool_executor import AgentToolExecutor, ToolAdmission
from app.agent.tools import AgentToolCatalog, ToolExecutionContext
from app.persistence.agent_runtime import _merge_usage, checkpoint_json_size_bytes
from app.persistence.errors import DomainError


class ChildEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claim: str
    source_title: str = ""
    url: str = ""


class ChildFinalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    status: Literal["completed", "needs_input"] = "completed"
    summary: str = Field(min_length=1)
    evidence: list[ChildEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChildAgentRunner:
    def __init__(
        self,
        model: AgentModelClient | None,
        catalog: AgentToolCatalog,
        metrics: AgentMetrics,
        *,
        model_name: str,
        tool_admission: ToolAdmission | None = None,
    ):
        self.model = model
        self.catalog = catalog.for_scope("child")
        self.executor = AgentToolExecutor(self.catalog, admission=tool_admission)
        self.metrics = metrics
        self.model_name = model_name

    async def run(self, task: dict[str, Any], cancel_event: asyncio.Event) -> dict[str, Any]:
        if self.model is None:
            raise DomainError("subagent_model_unavailable", "The child model is unavailable.")
        spec = task["spec"]
        system = CHILD_AGENT_SYSTEM_PROMPT
        if self.catalog.get("mock_web_search"):
            system += "\n" + MOCK_EVIDENCE_RULE
        messages = [
            {
                "role": "user",
                "content": (
                    f"任务键：{spec['task_key']}\n任务标题：{spec['title']}\n工作模式：{spec['profile']}\n\n"
                    f"任务指令：\n{spec['instruction']}\n\n期望输出：\n{spec['expected_output']}"
                ),
            }
        ]
        context = ToolExecutionContext(
            run_id=task["root_run_id"],
            session_id=task["session_id"],
            tenant_id=task["tenant_id"],
            owner_membership_id=task["owner_membership_id"],
            execution_scope="child",
            child_task_id=task["id"],
            fence=task["fence"],
            cancel_event=cancel_event,
        )
        compactor = AgentContextManager(self.model, trigger_ratio=0.8, summary_max_tokens=4096)
        usage: dict[str, Any] = {}
        while True:
            context.raise_if_cancelled()
            messages, _ = await compactor.fit(
                messages,
                {},
                tool_context_state=context.checkpoint_state,
                trigger="child_context_preflight",
            )
            content = ""
            reasoning = ""
            calls: list[dict[str, Any]] = []
            async for event in self.model.stream(
                [{"role": "system", "content": system}, *messages]
            ):
                context.raise_if_cancelled()
                if event.kind == "content":
                    content += event.content
                elif event.kind == "reasoning":
                    reasoning += event.content
                elif event.kind == "tool_calls":
                    calls = event.tool_calls
                elif event.kind == "usage":
                    usage = _merge_usage(usage, event.payload)
                if len(content.encode()) + len(reasoning.encode()) > 3 * 1024 * 1024:
                    raise DomainError(
                        "subagent_result_too_large", "The child response exceeds 3 MiB."
                    )
            if not calls:
                result = ChildFinalResult.model_validate_json(content).model_dump(mode="json")
                if result["status"] == "needs_input" and not result["warnings"]:
                    result["warnings"] = ["子任务缺少不可替代的输入。"]
                if self.catalog.get("mock_web_search") and context.runtime_cache.get("mock_used"):
                    result["warnings"].append("本结果使用本地固定的模拟资料，未进行真实网络搜索。")
                result.update({"usage": usage, "model": self.model_name})
                return result
            normalized = [
                {
                    "id": str(call.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(call.get("name") or ""),
                        "arguments": str(call.get("arguments") or "{}"),
                    },
                }
                for call in calls
            ]
            if any(not call["id"] for call in normalized) or len(
                {call["id"] for call in normalized}
            ) != len(normalized):
                raise DomainError(
                    "invalid_subagent_tool_calls", "Child returned invalid tool call identifiers."
                )
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": normalized,
            }
            if reasoning:
                assistant["reasoning_content"] = reasoning
            messages.append(assistant)

            async def execute(call: dict[str, Any]) -> dict[str, Any]:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"])
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be an object.")
                except (ValueError, TypeError) as exc:
                    result: Any = {
                        "ok": False,
                        "error": {"type": "InvalidToolArguments", "message": str(exc)},
                    }
                else:
                    self.metrics.increment(
                        "cornagent_subagent_tool_calls_total",
                        tool=name if self.catalog.get(name) else "unknown",
                    )
                    result = await self.executor.execute_tool(
                        name,
                        arguments,
                        context=context.for_tool(tool_call_id=call["id"], batch_id=call["id"]),
                    )
                    if (
                        name == "mock_web_search"
                        and isinstance(result, dict)
                        and result.get("is_mock")
                    ):
                        context.runtime_cache["mock_used"] = True
                return {
                    "role": "tool",
                    "name": name,
                    "tool_call_id": call["id"],
                    "content": json.dumps(
                        result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ),
                }

            messages.extend(await asyncio.gather(*(execute(call) for call in normalized)))
            if checkpoint_json_size_bytes({"messages": messages}) > 3 * 1024 * 1024:
                messages, _ = await compactor.fit(
                    messages,
                    {},
                    tool_context_state=context.checkpoint_state,
                    trigger="child_tool_result",
                    force=True,
                )
