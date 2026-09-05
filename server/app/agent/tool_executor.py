"""Generic fail-closed executor for registered Agent tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.tools import AgentToolCatalog, ToolContractError, ToolExecutionContext


class AgentToolExecutor:
    def __init__(self, catalog: AgentToolCatalog) -> None:
        self.catalog = catalog

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


__all__ = ["AgentToolExecutor"]
