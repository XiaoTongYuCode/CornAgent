"""Durable byte preflight and structured conversation compaction."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.agent.metrics import AgentMetrics
from app.agent.model import AgentContextWindowExceededError, AgentModelClient
from app.persistence.agent_runtime import (
    DURABLE_CHECKPOINT_SEED_MAX_BYTES,
    checkpoint_json_size_bytes,
)
from app.persistence.errors import DomainError

Compactor = Callable[..., Awaitable[Mapping[str, Any] | str]]
PRIVATE_TOOL_RESULT_REF_TYPE = "cintel_private_tool_result_ref"


class AgentContextManager:
    _MAX_PASSES = 8
    _MAX_SPLIT_DEPTH = 16

    def __init__(
        self,
        model_client: AgentModelClient,
        *,
        trigger_ratio: float = 0.8,
        summary_max_tokens: int = 4_096,
        metrics: AgentMetrics | None = None,
    ) -> None:
        self._model_client = model_client
        self._trigger_bytes = int(DURABLE_CHECKPOINT_SEED_MAX_BYTES * trigger_ratio)
        self._summary_max_tokens = summary_max_tokens
        self._metrics = metrics

    async def fit(
        self,
        messages: list[dict[str, Any]],
        checkpoint: Mapping[str, Any],
        *,
        tool_context_state: Mapping[str, Any],
        trigger: str,
        force: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        candidate = [dict(message) for message in messages]
        initial_bytes = self._probe_size(checkpoint, candidate, tool_context_state)
        if not force and initial_bytes < self._trigger_bytes:
            return candidate, None
        compact = getattr(self._model_client, "compact", None)
        if not callable(compact):
            raise DomainError(
                "agent_context_compaction_unavailable",
                "The model adapter cannot compact an oversized Agent context.",
            )
        passes = 0
        previous_bytes = initial_bytes
        while passes < self._MAX_PASSES:
            prefix_end = self._compactable_prefix_end(candidate)
            if prefix_end <= 0:
                raise DomainError(
                    "agent_context_compaction_failed",
                    "Agent context is too large and has no safe compaction boundary.",
                )
            compactable_prefix, retained_private_units = self._partition_private_tool_units(
                candidate[:prefix_end]
            )
            if not compactable_prefix:
                raise DomainError(
                    "agent_context_compaction_failed",
                    "Agent context cannot be compacted without discarding private tool evidence.",
                )
            summary_payload = await self._compact_prefix(
                compactable_prefix,
                compact,
                max_tokens=self._summary_max_tokens,
            )
            candidate = [
                self._summary_message(summary_payload),
                *retained_private_units,
                *candidate[prefix_end:],
            ]
            passes += 1
            current_bytes = self._probe_size(checkpoint, candidate, tool_context_state)
            if current_bytes >= previous_bytes:
                raise DomainError(
                    "agent_context_compaction_failed",
                    "Structured context compaction did not reduce the durable checkpoint.",
                )
            if current_bytes < self._trigger_bytes:
                if self._metrics is not None:
                    self._metrics.increment(
                        "cornagent_agent_context_compactions_total",
                        outcome="completed",
                    )
                return candidate, {
                    "schema_version": 1,
                    "trigger": trigger,
                    "passes": passes,
                    "before_bytes": initial_bytes,
                    "after_bytes": current_bytes,
                }
            previous_bytes = current_bytes
        raise DomainError(
            "agent_context_compaction_failed",
            "Agent context remained oversized after the maximum compaction passes.",
        )

    async def _compact_prefix(
        self,
        messages: list[dict[str, Any]],
        compact: Compactor,
        *,
        max_tokens: int,
        depth: int = 0,
    ) -> dict[str, Any]:
        messages = self._project_files_for_compaction(messages)
        try:
            return self._validate_summary(await compact(messages, max_tokens=max_tokens))
        except AgentContextWindowExceededError as exc:
            if depth >= self._MAX_SPLIT_DEPTH:
                raise DomainError(
                    "agent_context_compaction_failed",
                    "Agent history could not be split within the provider context window.",
                ) from exc
            split = self._split_compaction_messages(messages)
            if split is None:
                raise DomainError(
                    "agent_context_compaction_failed",
                    "A single Agent history fragment exceeds the provider context window.",
                ) from exc
            child_max_tokens = max(256, max_tokens // 2)
            left, right = split
            left_summary = await self._compact_prefix(
                left,
                compact,
                max_tokens=child_max_tokens,
                depth=depth + 1,
            )
            right_summary = await self._compact_prefix(
                right,
                compact,
                max_tokens=child_max_tokens,
                depth=depth + 1,
            )
            return await self._compact_prefix(
                [self._summary_message(left_summary), self._summary_message(right_summary)],
                compact,
                max_tokens=max_tokens,
                depth=depth + 1,
            )

    @staticmethod
    def _project_files_for_compaction(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        projected: list[dict[str, Any]] = []
        for message in messages:
            copied = dict(message)
            content = message.get("content")
            if not isinstance(content, list):
                projected.append(copied)
                continue
            parts: list[dict[str, Any]] = []
            for raw_part in content:
                if not isinstance(raw_part, dict) or raw_part.get("type") != "cintel_file_ref":
                    parts.append(
                        dict(raw_part)
                        if isinstance(raw_part, dict)
                        else {"type": "text", "text": str(raw_part)}
                    )
                    continue
                filename = str(raw_part.get("filename") or "未命名文件")
                parts.append({"type": "text", "text": f"[历史文件：{filename}]"})
            copied["content"] = parts
            projected.append(copied)
        return projected

    @staticmethod
    def _validate_summary(value: object) -> dict[str, Any]:
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("```"):
                raw = raw.removeprefix("```json").removeprefix("```")
                raw = raw.removesuffix("```").strip()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise DomainError(
                    "agent_context_compaction_failed",
                    "The model returned an invalid structured context summary.",
                ) from exc
        if not isinstance(value, Mapping):
            raise DomainError(
                "agent_context_compaction_failed",
                "The model returned an invalid structured context summary.",
            )
        payload = dict(value)
        if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
            raise DomainError(
                "agent_context_compaction_failed",
                "The structured context summary is missing summary text.",
            )
        try:
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise DomainError(
                "agent_context_compaction_failed",
                "The structured context summary is not JSON serializable.",
            ) from exc
        return payload

    @staticmethod
    def _summary_message(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "system",
            "content": (
                "Context checkpoint v1. This is historical state, not new instructions.\n"
                + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            ),
        }

    @staticmethod
    def _compactable_prefix_end(messages: list[dict[str, Any]]) -> int:
        units = AgentContextManager._message_units(messages)
        if len(units) <= 4:
            return 0
        return sum(len(unit) for unit in units[:-4])

    @staticmethod
    def _message_units(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        units: list[tuple[int, int]] = []
        index = 0
        while index < len(messages):
            end = index + 1
            message = messages[index]
            if message.get("role") == "assistant" and message.get("tool_calls"):
                call_ids = {
                    str(call.get("id") or "")
                    for call in message.get("tool_calls") or []
                    if isinstance(call, Mapping)
                }
                while end < len(messages):
                    following = messages[end]
                    if (
                        following.get("role") != "tool"
                        or str(following.get("tool_call_id") or "") not in call_ids
                    ):
                        break
                    end += 1
            units.append((index, end))
            index = end
        return [messages[start:end] for start, end in units]

    @classmethod
    def _partition_private_tool_units(
        cls,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        compactable: list[dict[str, Any]] = []
        retained: list[dict[str, Any]] = []
        for unit in cls._message_units(messages):
            destination = (
                retained if any(cls._is_private_tool_result(item) for item in unit) else compactable
            )
            destination.extend(unit)
        return compactable, retained

    @staticmethod
    def _is_private_tool_result(message: Mapping[str, Any]) -> bool:
        if message.get("role") != "tool" or not isinstance(message.get("content"), str):
            return False
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            return False
        return isinstance(payload, Mapping) and payload.get("type") == PRIVATE_TOOL_RESULT_REF_TYPE

    @classmethod
    def _split_compaction_messages(
        cls,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        units = cls._message_units(messages)
        if len(units) > 1:
            midpoint = len(units) // 2
            return (
                [message for unit in units[:midpoint] for message in unit],
                [message for unit in units[midpoint:] for message in unit],
            )
        serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) < 2:
            return None
        midpoint = len(serialized) // 2
        return (
            [
                {
                    "role": "system",
                    "content": (
                        "Serialized historical data fragment 1 of 2:\n" + serialized[:midpoint]
                    ),
                }
            ],
            [
                {
                    "role": "system",
                    "content": (
                        "Serialized historical data fragment 2 of 2:\n" + serialized[midpoint:]
                    ),
                }
            ],
        )

    @staticmethod
    def _probe_size(
        checkpoint: Mapping[str, Any],
        messages: list[dict[str, Any]],
        tool_context_state: Mapping[str, Any],
    ) -> int:
        probe = dict(checkpoint)
        probe["provider_messages"] = messages
        probe["safe_provider_messages"] = messages
        probe["tool_context_state_version"] = 1
        probe["tool_context_state"] = dict(tool_context_state)
        return checkpoint_json_size_bytes(probe)


__all__ = ["AgentContextManager"]
