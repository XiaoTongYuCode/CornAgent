"""Orchestration contracts adapted from agent_server archive 1c934f0d6ed2.

Parsing and provider schemas retain the source tool semantics. Execution is
intercepted by CornAgent's durable runtime, never by the ordinary executor.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from app.agent.subagents.protocol import (
    OperationRequest,
    SpawnSubagentsRequest,
    SubagentReturnWhen,
    SubagentTaskSpec,
    SubagentToolContext,
)
from app.agent.tools.base import ToolDefinition, ToolExecutionContext

SPAWN_SUBAGENTS_TOOL_NAME = "spawn_subagents"
LIST_SUBAGENTS_TOOL_NAME = "list_subagents"
WAIT_SUBAGENTS_TOOL_NAME = "wait_subagents"
COLLECT_SUBAGENT_RESULTS_TOOL_NAME = "collect_subagent_results"
DELEGATE_TASKS_TOOL_NAME = "delegate_tasks"

ROOT_ONLY_ORCHESTRATION_TOOL_NAMES = frozenset(
    {
        SPAWN_SUBAGENTS_TOOL_NAME,
        LIST_SUBAGENTS_TOOL_NAME,
        WAIT_SUBAGENTS_TOOL_NAME,
        COLLECT_SUBAGENT_RESULTS_TOOL_NAME,
        DELEGATE_TASKS_TOOL_NAME,
    }
)

_TASK_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_GROUP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VALID_PROFILES = {"researcher", "analyst", "verifier"}
_VALID_RETURN_WHEN = {"any", "all"}
_MAX_TASK_COUNT = 10
_MAX_CONCURRENCY = 5
_MAX_TITLE_LENGTH = 120
_MAX_INSTRUCTION_LENGTH = 8_000
_MAX_EXPECTED_OUTPUT_LENGTH = 2_000
_MAX_TASK_ID_COUNT = 64


async def _runtime_only(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
    raise RuntimeError("Orchestration tools require durable runtime interception.")


def build_subagent_orchestration_tools() -> list[ToolDefinition]:
    task_array_schema = _task_array_schema()
    definitions = [
        ToolDefinition(
            name=SPAWN_SUBAGENTS_TOOL_NAME,
            description=(
                "仅在用户任务适合拆分时，把 1 至 4 个可独立交付、需要多轮取证和小结的"
                "研究工作流并行下派给只读子 Agent，"
                "并立即返回持久化 group_id 和 task_ids。同一研究"
                "对象的不同证据域也可以拆成不同工作流；"
                "一次性搜索由主 Agent 直接处理。完成 "
                "Root-only 共享前置后按需调用本工具；任务指令由主 Agent 编写，"
                "再按实际依赖决定何时 wait/collect。"
                "该编排工具独占一次 tool_calls。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tasks": task_array_schema,
                    "max_concurrency": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_CONCURRENCY,
                        "description": "该组最大并发数，默认取任务数与 5 的较小值。",
                    },
                },
                "required": ["tasks"],
                "additionalProperties": False,
            },
            handler=_runtime_only,
            strict=True,
            status_label="正在下派子任务",
            status_detail=_task_count_detail,
        ),
        ToolDefinition(
            name=LIST_SUBAGENTS_TOOL_NAME,
            description=(
                "仅在当前 Root run 已通过 spawn_subagents 或 delegate_tasks 创建子任务后，"
                "读取这些子 Agent 的状态；不要用本工具探测工具是否可用或演示普通工具。默认返回全部"
                "，也可按 group_id 或 task_ids 过滤。"
                "每项只返回标题、状态、耗时、结果是否可收集、稳定错误码和有限摘要；"
                "不会返回完整 evidence，完整结果必须另用 collect_"
                "subagent_results。不会等待或轮询。"
                "该编排工具必须单独调用；若还需要普通工具，先完成普通工具轮次，再单独调用本工具。"
            ),
            parameters=_filter_parameters(),
            handler=_runtime_only,
            strict=True,
            status_label="正在读取子任务状态",
        ),
        ToolDefinition(
            name=WAIT_SUBAGENTS_TOOL_NAME,
            description=(
                "按 task_ids 注册持久化等待条件，可用 group_id 做"
                "一致性校验。条件尚未满足时会保存 Root continuati"
                "on 并立即暂停当前运行，"
                "不会在请求协程中 sleep 或轮询；条件满足后由 Corn"
                "Agent runtime 恢复。return_when=all 只会在全部指"
                "定任务进入终态后恢复，"
                "但完整结果可能受批次上限影响而分多次投递：pending_task_ids 才表示仍未终态；"
                "undelivered_result_task_ids "
                "表示已终态但尚未投递，next_action=collect_subage"
                "nt_results 时应改用 collect 收取，"
                "不要再次 wait。该编排工具必须单独调用。"
            ),
            parameters=_wait_parameters(),
            handler=_runtime_only,
            strict=True,
            status_label="正在等待子任务",
        ),
        ToolDefinition(
            name=COLLECT_SUBAGENT_RESULTS_TOOL_NAME,
            description=(
                "按持久化完成顺序非阻塞收集当前 Root run 尚未投递的子 Agent 结果；默认检查全部，"
                "也可按 group_id 或 task_ids 过滤，并与当前 Root checkpoint 原子标记投递。"
                "不会等待未完成任务。结果可能按批次完整投递；next"
                "_action=collect_subagent_results 时继续 collect"
                "，"
                "next_action=wait_subagents 时才表示仍有 pending_"
                "task_ids 可等待。该编排工具必须单独调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "group_id": _group_id_schema(),
                    "task_ids": _task_ids_schema(),
                },
                "additionalProperties": False,
            },
            handler=_runtime_only,
            strict=True,
            status_label="正在汇集子任务结果",
        ),
        ToolDefinition(
            name=DELEGATE_TASKS_TOOL_NAME,
            description=(
                "便捷工具，语义严格等价于 spawn_subagents 后 wait_subagents(return_when=all)："
                "通常原子创建 1 至 4 个只读子任务并注册持久化等待"
                "。复杂编排应优先显式调用 spawn_subagents。"
                "若结果未就绪会保存 Root continuation 后立即暂停"
                "，不会阻塞轮询。该编排工具必须单独调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tasks": task_array_schema,
                    "max_concurrency": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_CONCURRENCY,
                    },
                    "timeout_seconds": _timeout_seconds_schema(),
                },
                "required": ["tasks"],
                "additionalProperties": False,
            },
            handler=_runtime_only,
            strict=True,
            status_label="正在并行下派任务",
            status_detail=_task_count_detail,
        ),
    ]

    return [replace(tool, runtime_handler=tool.name, exclusive=True) for tool in definitions]


def parse_operation(
    name: str, arguments: Mapping[str, Any], call_id: str, *, wait_default_seconds: int = 300
) -> OperationRequest:
    if name not in ROOT_ONLY_ORCHESTRATION_TOOL_NAMES:
        raise ValueError("Unknown orchestration tool.")
    allowed = {"group_id", "task_ids"}
    if name in {SPAWN_SUBAGENTS_TOOL_NAME, DELEGATE_TASKS_TOOL_NAME}:
        allowed = {"tasks", "max_concurrency"}
    if name == WAIT_SUBAGENTS_TOOL_NAME:
        allowed |= {"return_when", "timeout_seconds"}
    if name == DELEGATE_TASKS_TOOL_NAME:
        allowed.add("timeout_seconds")
    if set(arguments) - allowed:
        raise ValueError("Orchestration arguments contain unknown fields.")
    if name in {SPAWN_SUBAGENTS_TOOL_NAME, DELEGATE_TASKS_TOOL_NAME}:
        spawn = _parse_spawn_request(arguments, context=SubagentToolContext(call_id))
        request = OperationRequest(name, tasks=spawn.tasks, max_concurrency=spawn.max_concurrency)
    else:
        request = OperationRequest(
            name,
            group_id=_parse_optional_group_id(arguments),
            task_ids=_parse_task_ids(arguments, required=name == WAIT_SUBAGENTS_TOOL_NAME),
        )
    if name in {WAIT_SUBAGENTS_TOOL_NAME, DELEGATE_TASKS_TOOL_NAME}:
        request = replace(
            request,
            return_when=_parse_return_when(arguments),
            timeout_seconds=_parse_timeout_seconds(
                {"timeout_seconds": wait_default_seconds, **arguments}
            ),
        )
    return request


def _parse_spawn_request(
    arguments: Mapping[str, Any],
    *,
    context: SubagentToolContext,
) -> SpawnSubagentsRequest:
    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, Sequence) or isinstance(raw_tasks, (str, bytes, bytearray)):
        raise ValueError("tasks 必须是数组。")
    if not 1 <= len(raw_tasks) <= _MAX_TASK_COUNT:
        raise ValueError(f"tasks 数量必须在 1 到 {_MAX_TASK_COUNT} 之间。")

    tasks: list[SubagentTaskSpec] = []
    for ordinal, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, Mapping):
            raise ValueError(f"tasks[{ordinal}] 必须是 JSON object。")
        unknown_keys = set(raw_task) - {
            "title",
            "instruction",
            "expected_output",
            "profile",
            "required",
        }
        if unknown_keys:
            raise ValueError(f"tasks[{ordinal}] 包含未知字段：{sorted(unknown_keys)}")

        title = _required_text(
            raw_task.get("title"),
            field_name=f"tasks[{ordinal}].title",
            max_length=_MAX_TITLE_LENGTH,
        )
        instruction = _required_text(
            raw_task.get("instruction"),
            field_name=f"tasks[{ordinal}].instruction",
            max_length=_MAX_INSTRUCTION_LENGTH,
        )
        expected_output = _required_text(
            raw_task.get("expected_output"),
            field_name=f"tasks[{ordinal}].expected_output",
            max_length=_MAX_EXPECTED_OUTPUT_LENGTH,
        )
        profile = str(raw_task.get("profile") or "researcher").strip()
        if profile not in _VALID_PROFILES:
            raise ValueError(f"tasks[{ordinal}].profile 必须是 researcher、analyst 或 verifier。")
        required = raw_task.get("required", True)
        if not isinstance(required, bool):
            raise ValueError(f"tasks[{ordinal}].required 必须是 boolean。")
        tasks.append(
            SubagentTaskSpec(
                task_key=_internal_task_key(context.tool_call_id, ordinal),
                title=title,
                instruction=instruction,
                expected_output=expected_output,
                ordinal=ordinal,
                profile=profile,
                required=required,
            )
        )

    raw_max_concurrency = arguments.get("max_concurrency", min(len(tasks), _MAX_CONCURRENCY))
    if isinstance(raw_max_concurrency, bool) or not isinstance(raw_max_concurrency, int):
        raise ValueError("max_concurrency 必须是 integer。")
    if not 1 <= raw_max_concurrency <= min(len(tasks), _MAX_CONCURRENCY):
        raise ValueError(
            f"max_concurrency 必须在 1 与 tasks 数量之间，且不能超过 {_MAX_CONCURRENCY}。"
        )
    return SpawnSubagentsRequest(tasks=tuple(tasks), max_concurrency=raw_max_concurrency)


def _parse_optional_group_id(arguments: Mapping[str, Any]) -> str | None:
    raw_group_id = arguments.get("group_id")
    if raw_group_id in (None, ""):
        return None
    if not isinstance(raw_group_id, str):
        raise ValueError("group_id 必须是 string。")
    group_id = raw_group_id.strip()
    if not _GROUP_ID_PATTERN.fullmatch(group_id):
        raise ValueError("group_id 格式无效。")
    return group_id


def _parse_task_ids(arguments: Mapping[str, Any], *, required: bool) -> tuple[str, ...]:
    raw_task_ids = arguments.get("task_ids")
    if raw_task_ids is None and not required:
        return ()
    if not isinstance(raw_task_ids, Sequence) or isinstance(raw_task_ids, (str, bytes, bytearray)):
        raise ValueError("task_ids 必须是数组。")
    if required and not raw_task_ids:
        raise ValueError("task_ids 不能为空。")
    if len(raw_task_ids) > _MAX_TASK_ID_COUNT:
        raise ValueError(f"task_ids 最多 {_MAX_TASK_ID_COUNT} 个。")
    task_ids: list[str] = []
    for raw_task_id in raw_task_ids:
        if not isinstance(raw_task_id, str):
            raise ValueError("task_ids 只能包含 string。")
        task_id = raw_task_id.strip()
        if not _GROUP_ID_PATTERN.fullmatch(task_id):
            raise ValueError("task_ids 包含无效 id。")
        if task_id not in task_ids:
            task_ids.append(task_id)
    return tuple(task_ids)


def _parse_return_when(arguments: Mapping[str, Any]) -> SubagentReturnWhen:
    return_when = str(arguments.get("return_when") or "all").strip()
    if return_when not in _VALID_RETURN_WHEN:
        raise ValueError("return_when 必须是 any 或 all。")
    return return_when


def _parse_timeout_seconds(arguments: Mapping[str, Any]) -> int:
    timeout_seconds = arguments.get("timeout_seconds", 300)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ValueError("timeout_seconds 必须是 integer。")
    if not 1 <= timeout_seconds <= 600:
        raise ValueError("timeout_seconds 必须在 1 到 600 之间。")
    return timeout_seconds


def _internal_task_key(tool_call_id: str, ordinal: int) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", tool_call_id).strip("_")
    normalized = normalized[-40:] or "call"
    task_key = f"{normalized}_{ordinal + 1}"
    if not _TASK_KEY_PATTERN.fullmatch(task_key):
        raise ValueError("无法生成内部 task_key。")
    return task_key


def _required_text(value: object, *, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是 string。")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空。")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} 最长 {max_length} 个字符。")
    return normalized


def _task_array_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": _MAX_TASK_COUNT,
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "简短任务标题。"},
                "instruction": {
                    "type": "string",
                    "description": (
                        "自包含的研究指令；写明目标、已确认主体与稳定身份、可用数据或档案版本、"
                        "范围与时间、证据边界和交付要求。"
                    ),
                },
                "expected_output": {
                    "type": "string",
                    "description": "主 Agent 期望拿到的结果形式与验收标准。",
                },
                "profile": {
                    "type": "string",
                    "enum": ["researcher", "analyst", "verifier"],
                    "description": (
                        "子 Agent 工作模式：researcher 发现并归纳证据，an"
                        "alyst 比较和解释已知事实，"
                        "verifier 核验明确主张；默认 researcher。"
                    ),
                },
                "required": {
                    "type": "boolean",
                    "description": "Root 最终作答是否必须等待该任务，默认 true。",
                },
            },
            "required": ["title", "instruction", "expected_output"],
            "additionalProperties": False,
        },
    }


def _group_id_schema() -> dict[str, Any]:
    return {"type": "string", "description": "spawn/delegate 返回的持久化 group_id。"}


def _task_ids_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "description": "spawn/delegate 返回的一个或多个持久化 task id。",
    }


def _filter_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "group_id": _group_id_schema(),
            "task_ids": _task_ids_schema(),
        },
        "additionalProperties": False,
    }


def _return_when_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "enum": ["any", "all"],
        "description": (
            "任一或全部指定任务进入终态时恢复，默认 all。all 的判断与结果分批投递无关。"
        ),
    }


def _timeout_seconds_schema() -> dict[str, Any]:
    return {
        "type": "integer",
        "minimum": 1,
        "maximum": 600,
        "description": "持久化等待 deadline 秒数，默认 300；handler 本身不阻塞。",
    }


def _wait_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "group_id": _group_id_schema(),
            "task_ids": _task_ids_schema(),
            "return_when": _return_when_schema(),
            "timeout_seconds": _timeout_seconds_schema(),
        },
        "required": ["task_ids"],
        "additionalProperties": False,
    }


def _task_count_detail(arguments: Mapping[str, Any]) -> str | None:
    tasks = arguments.get("tasks")
    if isinstance(tasks, list):
        return f"共 {len(tasks)} 个子任务"
    return None
