"""Scoped tool discovery with server-owned, checkpointed loading state."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.prompt import AgentSkillCatalog, AgentSkillDefinition
from app.agent.tools.base import ToolDefinition, ToolExecutionContext
from app.agent.tools.catalog import AgentToolCatalog

RESIDENT_TOOLS = frozenset(
    {
        "search_tools",
        "read_skill",
        "ask_user",
        "read_file",
        "read_tool_result",
        "list_materials",
        "search_materials",
        "read_material",
    }
)
_STATE_KEY = "tool_loading"
_SYNONYMS = (
    ("修改", "更新", "编辑", "更改", "update", "edit"),
    ("新建", "创建", "新增", "添加", "create", "add"),
    ("删除", "移除", "delete", "remove"),
    ("查看", "读取", "获取", "查询", "列出", "read", "get", "list"),
    ("搜索", "检索", "search", "find"),
    ("网页", "联网", "网络", "web", "url"),
    ("任务", "子任务", "并行", "委派", "task", "subagent", "parallel"),
)


def _singular(word: str) -> str:
    if len(word) <= 3 or word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if re.search(r"(?:s|x|z|ch|sh)es$", word):
        return word[:-2]
    return word[:-1] if word.endswith("s") else word


def _tokens(text: str) -> set[str]:
    result: set[str] = set()
    for word in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.lower()):
        if word.isascii():
            result.add(_singular(word))
        elif len(word) == 1:
            result.add(word)
        else:
            result.update(word[index : index + 2] for index in range(len(word) - 1))
    return result


def _query_tokens(query: str) -> set[str]:
    words = _tokens(query)
    for synonyms in _SYNONYMS:
        if words.intersection(synonyms):
            words.update(synonyms)
    return words


def _score(query: str, name: str, description: str) -> float:
    if query.strip().lower() in {"*", "tools", "工具", "skills", "技能"}:
        return 1
    words, name_words, text_words = _query_tokens(query), _tokens(name), _tokens(description)
    exact = 20 if query.strip().casefold() == name.casefold() else 0
    return (
        exact
        + 8 * len(words.intersection(name_words)) / max(1, len(name_words))
        + 2 * len(words.intersection(text_words)) / max(1, len(words))
    )


def rank_tools(query: str, tools: tuple[ToolDefinition, ...]) -> list[ToolDefinition]:
    ranked = []
    for index, tool in enumerate(tools):
        properties = tool.parameters.get("properties", {})
        argument_text = (
            " ".join(
                f"{name} {value.get('description', '')}"
                for name, value in properties.items()
                if isinstance(value, Mapping)
            )
            if isinstance(properties, Mapping)
            else ""
        )
        score = _score(
            query,
            tool.name,
            " ".join((tool.description, tool.group, *tool.keywords, argument_text)),
        )
        if score > 0:
            ranked.append((score, tool.effect == "write", index, tool))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[3] for item in ranked if item[0] >= ranked[0][0] / 2] if ranked else []


class SearchToolsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=5, ge=1, le=8)


class ReadSkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)


class ToolLoader:
    """The catalog and checkpoint are trusted; message/result text never grants tools."""

    def __init__(self, catalog: AgentToolCatalog, skills: AgentSkillCatalog | None = None) -> None:
        self.catalog = catalog
        self.skills = skills or AgentSkillCatalog()

    def _eligible(self, context: ToolExecutionContext) -> AgentToolCatalog:
        return self.catalog.for_scope(context.execution_scope)

    def _state(self, context: ToolExecutionContext) -> dict[str, Any]:
        value = context.checkpoint_state.get(_STATE_KEY)
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or value.get("scope") != context.execution_scope
        ):
            return {
                "version": 1,
                "scope": context.execution_scope,
                "loaded_tools": [],
                "loaded_skills": [],
            }
        return value

    @staticmethod
    def _names(state: dict[str, Any], key: str) -> list[str]:
        values = state.get(key)
        return (
            list(dict.fromkeys(item for item in values if isinstance(item, str)))
            if isinstance(values, list)
            else []
        )

    def request_catalog(self, context: ToolExecutionContext) -> AgentToolCatalog:
        eligible = self._eligible(context)
        selected = [
            tool for tool in eligible.definitions() if tool.resident or tool.name in RESIDENT_TOOLS
        ]
        selected_names = {tool.name for tool in selected}
        for name in self._names(self._state(context), "loaded_tools"):
            tool = eligible.get(name)
            if tool is not None and name not in selected_names:
                selected.append(tool)
                selected_names.add(name)
        return AgentToolCatalog(selected)

    def request_tools(self, context: ToolExecutionContext) -> list[dict[str, object]]:
        return self.request_catalog(context).provider_tools()

    def _eligible_skills(self, context: ToolExecutionContext) -> tuple[AgentSkillDefinition, ...]:
        names = set(self._eligible(context).names())
        flags = context.extra.get("feature_flags", {})
        flags = (
            {name for name, enabled in flags.items() if enabled is True}
            if isinstance(flags, Mapping)
            else set()
        )
        return tuple(
            skill
            for skill in self.skills.definitions()
            if context.execution_scope in skill.execution_scopes
            and skill.required_tools.issubset(names)
            and skill.required_flags.issubset(flags)
        )

    def skill_prompt_blocks(self, context: ToolExecutionContext) -> list[str]:
        loaded = set(self._names(self._state(context), "loaded_skills"))
        return [
            f"Skill {skill.name}:\n{skill.instructions.strip()}"
            for skill in self._eligible_skills(context)
            if skill.name in loaded
        ]

    def _load(
        self, context: ToolExecutionContext, names: list[str], *, skill_name: str | None = None
    ) -> list[str]:
        eligible = self._eligible(context)
        loaded = [name for name in names if eligible.get(name) is not None]
        state = self._state(context)
        state = {
            "version": 1,
            "scope": context.execution_scope,
            "loaded_tools": list(
                dict.fromkeys(
                    [
                        *(
                            name
                            for name in self._names(state, "loaded_tools")
                            if eligible.get(name)
                        ),
                        *loaded,
                    ]
                )
            ),
            "loaded_skills": list(
                dict.fromkeys(
                    [
                        *self._names(state, "loaded_skills"),
                        *([skill_name] if skill_name else []),
                    ]
                )
            ),
        }
        context.checkpoint_state[_STATE_KEY] = state
        return loaded

    def discovery_tools(self) -> tuple[ToolDefinition, ...]:
        async def search(arguments: dict[str, Any], context: ToolExecutionContext) -> dict:
            context.raise_if_cancelled()
            query, limit = arguments["query"], arguments["max_results"]
            tools = rank_tools(query, self._eligible(context).definitions())[:limit]
            skills = sorted(
                (
                    (score, index, skill)
                    for index, skill in enumerate(self._eligible_skills(context))
                    if (
                        score := _score(
                            query, skill.name, " ".join((skill.description, *skill.keywords))
                        )
                    )
                    > 0
                ),
                key=lambda item: (-item[0], item[1]),
            )[:limit]
            names = self._load(context, [tool.name for tool in tools]) if tools else []
            return {
                "ok": True,
                "tools": [{"name": tool.name, "description": tool.description} for tool in tools],
                "skills": [
                    {"name": skill.name, "description": skill.description} for _, _, skill in skills
                ],
                "loaded_tools": names,
                "available_next_request": True,
            }

        async def read_skill(arguments: dict[str, Any], context: ToolExecutionContext) -> dict:
            context.raise_if_cancelled()
            skill = next(
                (item for item in self._eligible_skills(context) if item.name == arguments["name"]),
                None,
            )
            if skill is None:
                return {
                    "ok": False,
                    "error": {
                        "type": "SkillUnavailable",
                        "message": "该技能未注册或当前 Agent 不可用。",
                    },
                }
            # Registration order, rather than set iteration, keeps provider prefixes stable.
            names = [
                name for name in self._eligible(context).names() if name in skill.required_tools
            ]
            return {
                "ok": True,
                "name": skill.name,
                "instructions": skill.instructions,
                "loaded_tools": self._load(context, names, skill_name=skill.name),
                "available_next_request": True,
            }

        return (
            ToolDefinition(
                name="search_tools",
                description="按能力、名称或中英文关键词搜索当前可用工具和技能。匹配工具的完整参数"
                "将在下一轮请求加载；本轮不能同时调用刚加载的工具。返回的技能需 read_skill 读取。"
                "query 为 * 时浏览工具目录，每次最多 8 项。",
                parameters=SearchToolsArguments.model_json_schema(),
                arguments_model=SearchToolsArguments,
                handler=search,
                resident=True,
                read_only=True,
                effect="control",
                execution_scopes=frozenset({"root", "child"}),
                status_label="正在查找工具",
                status_detail=lambda args: args.get("query"),
            ),
            ToolDefinition(
                name="read_skill",
                description="按 search_tools 返回的技能名称读取服务端注册的操作指南，"
                "并在下一轮加载该技能声明的工具。不会读取任意本地路径或执行指南中的代码。",
                parameters=ReadSkillArguments.model_json_schema(),
                arguments_model=ReadSkillArguments,
                handler=read_skill,
                resident=True,
                read_only=True,
                effect="control",
                execution_scopes=frozenset({"root", "child"}),
                status_label="正在读取技能",
                status_detail=lambda args: args.get("name"),
            ),
        )


__all__ = ["RESIDENT_TOOLS", "ToolLoader", "rank_tools"]
