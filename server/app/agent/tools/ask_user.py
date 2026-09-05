"""The runtime-intercepted ask_user tool."""

from __future__ import annotations

from typing import Any

from app.agent.tools.base import ToolDefinition, ToolExecutionContext
from app.persistence.agent_runtime import ASK_USER_TOOL_NAME

ASK_USER_RUNTIME_HANDLER = "pause_for_user"


async def _pause_for_user(
    _arguments: dict[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "type": "AskUserToolPaused",
            "message": "ask_user 由 Agent runtime 拦截，不能进入普通 tool executor。",
        },
    }


def build_ask_user_tool() -> ToolDefinition:
    return ToolDefinition(
        name=ASK_USER_TOOL_NAME,
        description=(
            "仅在确实无法继续判断时向用户提出一个问题。必须作为该轮唯一的 tool call；"
            "用户可以选择选项、输入自定义回答或忽略问题。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要向用户提出的单个明确问题。",
                },
                "options": {
                    "type": "array",
                    "description": "可供用户直接选择的答案列表。",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "选项展示文本及 canonical 回答内容。",
                            },
                            "description": {
                                "type": "string",
                                "description": "选择该选项的影响或适用场景。",
                            },
                        },
                        "required": ["content", "description"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["query", "options"],
            "additionalProperties": False,
        },
        handler=_pause_for_user,
        strict=True,
        status_label="等待用户确认",
        status_detail=lambda arguments: str(arguments.get("query") or "").strip() or None,
        runtime_handler=ASK_USER_RUNTIME_HANDLER,
        exclusive=True,
    )


__all__ = ["ASK_USER_RUNTIME_HANDLER", "build_ask_user_tool"]
