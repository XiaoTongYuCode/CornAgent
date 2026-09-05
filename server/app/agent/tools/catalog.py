"""Composable registry for the CornAgent tool catalog."""

from __future__ import annotations

from collections.abc import Iterable

from app.agent.tools.ask_user import build_ask_user_tool
from app.agent.tools.base import ToolDefinition


class AgentToolCatalog:
    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Agent tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools.values())

    def provider_tools(self) -> list[dict[str, object]]:
        return [tool.to_provider_tool() for tool in self._tools.values()]

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def for_scope(self, scope: str) -> AgentToolCatalog:
        if scope not in {"root", "child"}:
            raise ValueError("Unknown Agent execution scope.")
        return AgentToolCatalog(
            tool for tool in self.definitions() if scope in tool.execution_scopes
        )


def build_default_tool_catalog(
    additional_tools: Iterable[ToolDefinition] = (),
) -> AgentToolCatalog:
    tools = [build_ask_user_tool()]
    tools.extend(additional_tools)
    return AgentToolCatalog(tools)


__all__ = [
    "AgentToolCatalog",
    "build_default_tool_catalog",
]
