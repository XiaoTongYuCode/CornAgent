"""CornAgent provider、运行编排与事件传输组合层。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["AgentEventStream", "AgentModelClient", "AgentRuntime", "AgentToolCatalog"]

_EXPORTS = {
    "AgentEventStream": ("app.agent.stream", "AgentEventStream"),
    "AgentModelClient": ("app.agent.model", "AgentModelClient"),
    "AgentRuntime": ("app.agent.runtime", "AgentRuntime"),
    "AgentToolCatalog": ("app.agent.tools", "AgentToolCatalog"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
