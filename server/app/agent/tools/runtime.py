"""Registry contracts for tools intercepted by the durable Agent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from app.agent.tools.base import ToolDefinition, ToolExecutionContext


@dataclass(slots=True)
class RuntimeToolCall:
    """A normalized provider call plus the state needed for durable interception."""

    definition: ToolDefinition
    run_id: str
    worker_id: str
    fence: int
    tool_call_id: str
    arguments: dict[str, Any]
    provider_messages: list[dict[str, Any]]
    round_content: str
    round_reasoning: str
    usage: dict[str, Any]
    normalized_calls: list[dict[str, Any]]
    context: ToolExecutionContext


@dataclass(slots=True)
class RuntimeToolOutcome:
    status: Literal["continue", "waiting_for_user", "waiting_for_subagents"]
    provider_messages: list[dict[str, Any]] | None = None


RuntimeToolHandler = Callable[[RuntimeToolCall], Awaitable[RuntimeToolOutcome]]


class RuntimeToolHandlerRegistry:
    """Maps stable handler keys to runtime-owned durable transitions."""

    def __init__(
        self,
        handlers: Iterable[tuple[str, RuntimeToolHandler]] = (),
    ) -> None:
        self._handlers: dict[str, RuntimeToolHandler] = {}
        for key, handler in handlers:
            self.register(key, handler)

    def register(self, key: str, handler: RuntimeToolHandler) -> None:
        normalized = key.strip()
        if not normalized:
            raise ValueError("Runtime tool handler key must not be empty.")
        if normalized in self._handlers:
            raise ValueError(f"Runtime tool handler {normalized!r} is already registered.")
        self._handlers[normalized] = handler

    def get(self, key: str | None) -> RuntimeToolHandler | None:
        return self._handlers.get(key or "")

    def keys(self) -> tuple[str, ...]:
        return tuple(self._handlers)


__all__ = [
    "RuntimeToolCall",
    "RuntimeToolHandler",
    "RuntimeToolHandlerRegistry",
    "RuntimeToolOutcome",
]
