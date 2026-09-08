"""Generic fail-closed executor for registered Agent tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.agent.tools import (
    AgentToolCatalog,
    ToolContractError,
    ToolDefinition,
    ToolExecutionContext,
)


class ToolAdmission:
    """A process-local budget held until the real handler has finished."""

    def __init__(self, max_concurrency: int = 4) -> None:
        self._slots = asyncio.Semaphore(max(1, max_concurrency))
        self._inflight: set[asyncio.Task[Any]] = set()

    async def invoke(
        self, callback: Callable[[], Awaitable[Any]], context: ToolExecutionContext
    ) -> Any:
        await self._slots.acquire()
        try:
            context.raise_if_cancelled()
        except BaseException:
            self._slots.release()
            raise

        async def execute():
            context.raise_if_cancelled()
            return await callback()

        task = asyncio.create_task(execute())
        self._inflight.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self._inflight.discard(task)
        self._slots.release()
        if not task.cancelled():
            task.exception()  # Retrieve errors even when the original waiter was cancelled.

    async def close(self) -> None:
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)


class AgentToolExecutor:
    def __init__(
        self,
        catalog: AgentToolCatalog,
        *,
        max_concurrency: int = 4,
        admission: ToolAdmission | None = None,
    ) -> None:
        self.catalog = catalog
        self.admission = admission or ToolAdmission(max_concurrency)

    async def close(self) -> None:
        await self.admission.close()

    async def invoke_approval(
        self, tool: ToolDefinition, payload: dict[str, Any], context: ToolExecutionContext
    ) -> Any:
        if context.execution_scope != "root" or tool.approval_handler is None:
            raise ToolContractError("scope", "Approval execution requires a root tool.")
        return await self.admission.invoke(lambda: tool.approval_handler(payload, context), context)

    async def execute_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        context: ToolExecutionContext | None = None,
    ) -> Any:
        tool = self.catalog.get(name)
        if tool is None:
            return self._error("UnknownTool", "该工具未在 CornAgent catalog 中注册。")
        context = context or ToolExecutionContext()
        if context.execution_scope not in tool.execution_scopes or (
            context.execution_scope == "child"
            and (not tool.read_only or tool.runtime_handler is not None or tool.exclusive)
        ):
            return self._error("ToolScopeDenied", "当前 Agent 无权执行此工具。")
        context.raise_if_cancelled()
        try:
            normalized_arguments = tool.validate_arguments(dict(arguments or {}))
        except ToolContractError as exc:
            return self._error("InvalidToolArguments", str(exc), phase=exc.phase)
        return await self.admission.invoke(
            lambda: self._invoke(tool, normalized_arguments, context), context
        )

    async def _invoke(
        self,
        tool: ToolDefinition,
        normalized_arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        try:
            result = await tool.handler(
                normalized_arguments,
                context,
            )
            return tool.validate_result(result)
        except ToolContractError as exc:
            return self._error("InvalidToolResult", str(exc), phase=exc.phase)
        except Exception as exc:  # noqa: BLE001 - tool failures become provider tool results
            return self._error(type(exc).__name__, str(exc) or "工具执行失败。")

    @staticmethod
    def _error(error_type: str, message: str, *, phase: str | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {
            "type": error_type,
            "message": message,
        }
        if phase is not None:
            error["phase"] = phase
        return {"ok": False, "error": error}


__all__ = ["AgentToolExecutor", "ToolAdmission"]
