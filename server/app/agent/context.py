"""Durable byte preflight and structured conversation compaction."""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.agent.metrics import AgentMetrics
from app.agent.model import AgentContextWindowExceededError, AgentModelClient
from app.agent.model_context import checkpoint_byte_limit
from app.persistence.agent_runtime import (
    DURABLE_CHECKPOINT_RESULT_RESERVE_BYTES,
    checkpoint_json_size_bytes,
)
from app.persistence.errors import DomainError

Compactor = Callable[..., Awaitable[Mapping[str, Any] | str]]
PRIVATE_TOOL_RESULT_REF_TYPE = "cintel_private_tool_result_ref"


def estimate_tokens(value: Any) -> int:
    # Do not count base64 as prose. Image usage is calibrated with actual provider usage.
    def project(item):
        if isinstance(item, dict):
            if item.get("type") == "image_url":
                return "x" * 3072
            return {k: project(v) for k, v in item.items()}
        if isinstance(item, list):
            return [project(v) for v in item]
        return item

    text = json.dumps(project(value), ensure_ascii=False, separators=(",", ":"))
    ascii_count = sum(ord(c) < 128 for c in text)
    return math.ceil(ascii_count / 3 + (len(text) - ascii_count) * 1.5)


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
        context_window_tokens: int = 64_000,
        output_tokens: int = 16_384,
        read_only_tools: set[str] | None = None,
    ) -> None:
        self._model_client = model_client
        self.input_budget = int(context_window_tokens * 0.8) - output_tokens
        if self.input_budget < 1024:
            raise ValueError("Context window must leave at least 1024 input tokens")
        self._read_only_tools = read_only_tools
        self.overhead_tokens = estimate_tokens(
            {
                "system": getattr(model_client, "system_prompt", ""),
                "tools": getattr(model_client, "tools", []),
            }
        )
        self._trigger_bytes = int(
            (checkpoint_byte_limit(context_window_tokens) - DURABLE_CHECKPOINT_RESULT_RESERVE_BYTES)
            * trigger_ratio
        )
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
        overhead_tokens: int = 0,
        model_overhead_tokens: int | None = None,
        prepare: Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]] | None = None,
        on_start: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        candidate = [dict(message) for message in messages]
        initial_bytes = self._probe_size(checkpoint, candidate, tool_context_state)
        ratio = max(0.5, min(4.0, float(tool_context_state.get("context_token_ratio", 1))))
        overhead = (
            self.overhead_tokens if model_overhead_tokens is None else model_overhead_tokens
        ) + overhead_tokens

        async def cost(value):
            hydrated = await prepare(value) if prepare else value
            return (estimate_tokens(hydrated) + overhead) * ratio

        initial_tokens = await cost(candidate)
        target_tokens = (overhead + max(0, self.input_budget / ratio - overhead) * 0.6) * ratio
        if not force and initial_bytes < self._trigger_bytes and initial_tokens < self.input_budget:
            return candidate, None
        compact = getattr(self._model_client, "compact", None)
        if not callable(compact):
            raise DomainError(
                "agent_context_compaction_unavailable",
                "The model adapter cannot compact an oversized Agent context.",
            )
        if on_start:
            await on_start()
        passes = 0
        previous_tokens = initial_tokens
        previous_bytes = initial_bytes
        while passes < self._MAX_PASSES:
            selected = self._select_units(candidate, include_private=prepare is not None)
            if not selected:
                raise DomainError(
                    "agent_context_compaction_failed",
                    "Agent context is too large and has no safe compaction boundary.",
                )
            compactable_prefix = [candidate[i] for i in sorted(selected)]
            before_candidate = candidate
            summary_input = await prepare(compactable_prefix) if prepare else compactable_prefix
            # Summarization sees read text, never base64 or a raw private reference.
            summary_input = [
                {**m, "content": [p for p in m["content"] if p.get("type") != "image_url"]}
                if isinstance(m.get("content"), list)
                else m
                for m in summary_input
            ]
            summary_payload = await self._compact_prefix(
                summary_input,
                compact,
                max_tokens=min(self._summary_max_tokens, max(256, self.input_budget // 8)),
            )
            facts = []
            receipts = []
            for message in compactable_prefix:
                if isinstance(message.get("cornagent_receipt"), dict):
                    receipts.append(message["cornagent_receipt"])
                if self._is_private_tool_result(message):
                    facts.append(json.loads(message["content"]))
                if message.get("role") == "system" and str(message.get("content", "")).startswith(
                    "Context checkpoint v1."
                ):
                    try:
                        prior = json.loads(message["content"].split("\n", 1)[1])
                        facts.extend(prior.get("file_reads", []))
                        receipts.extend(prior.get("tool_receipts", []))
                    except (ValueError, IndexError):
                        pass
            # These reference identities are server-owned and survive re-compaction.
            summary_payload["file_reads"] = list(
                {json.dumps(f, sort_keys=True): f for f in facts}.values()
            )
            if receipts:
                summary_payload["tool_receipts"] = list(
                    {json.dumps(r, sort_keys=True): r for r in receipts}.values()
                )
            else:
                summary_payload.pop("tool_receipts", None)
            first = min(selected)
            candidate = [
                replacement
                for i, message in enumerate(candidate)
                for replacement in (
                    [self._summary_message(summary_payload)]
                    if i == first
                    else []
                    if i in selected
                    else [message]
                )
            ]
            passes += 1
            current_bytes = self._probe_size(checkpoint, candidate, tool_context_state)
            current_tokens = await cost(candidate)
            if current_bytes >= previous_bytes and current_tokens >= previous_tokens:
                if (
                    passes > 1
                    and previous_bytes < self._trigger_bytes
                    and previous_tokens < self.input_budget
                ):
                    return before_candidate, {
                        "trigger": trigger,
                        "passes": passes - 1,
                        "before_bytes": initial_bytes,
                        "after_bytes": previous_bytes,
                    }
                raise DomainError(
                    "agent_context_compaction_failed",
                    "Structured context compaction did not reduce the durable checkpoint.",
                )
            if current_bytes < self._trigger_bytes * 0.6 and current_tokens < target_tokens:
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
                    "before_tokens": initial_tokens,
                    "after_tokens": current_tokens,
                    "input_budget_tokens": self.input_budget,
                    "token_ratio": ratio,
                }
            previous_bytes = current_bytes
            previous_tokens = current_tokens
        if previous_bytes < self._trigger_bytes and previous_tokens < self.input_budget:
            return candidate, {
                "schema_version": 1,
                "trigger": trigger,
                "passes": passes,
                "before_bytes": initial_bytes,
                "after_bytes": previous_bytes,
            }
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
            if estimate_tokens(messages) > self.input_budget * 0.6:
                raise AgentContextWindowExceededError("compaction_preflight")
            result = self._validate_summary(await compact(messages, max_tokens=max_tokens))
            for _ in range(3):
                if estimate_tokens(result) <= max_tokens:
                    return result
                before = estimate_tokens(result)
                result = self._validate_summary(
                    await compact(
                        [self._summary_message(result)], max_tokens=max(256, max_tokens // 2)
                    )
                )
                if estimate_tokens(result) >= before:
                    raise DomainError("agent_context_compaction_failed", "Summary did not shrink.")
            if estimate_tokens(result) > max_tokens:
                raise DomainError("agent_context_compaction_failed", "Summary remained oversized.")
            return result
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

    def _select_units(self, messages, *, include_private=False):
        latest_user = max(
            (i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1
        )
        selected = []
        offset = 0
        for unit in self._message_units(messages):
            indexes = list(range(offset, offset + len(unit)))
            offset += len(unit)
            first = unit[0]
            if latest_user in indexes or (
                not include_private and any(self._is_private_tool_result(m) for m in unit)
            ):
                continue
            if any(
                isinstance(m.get("content"), list)
                and any(
                    isinstance(p, dict) and p.get("type") == "cintel_file_ref" for p in m["content"]
                )
                for m in unit
            ):
                continue
            if first.get("role") == "system" and not str(first.get("content", "")).startswith(
                "Context checkpoint v1."
            ):
                continue
            calls = first.get("tool_calls", [])
            if calls:
                ids = {c.get("id") for c in calls}
                if len(unit) != len(calls) + 1 or {m.get("tool_call_id") for m in unit[1:]} != ids:
                    continue
                receipts_by_call = {
                    m.get("tool_call_id"): m.get("cornagent_receipt") for m in unit[1:]
                }
                if self._read_only_tools is not None and any(
                    c.get("function", {}).get("name") not in self._read_only_tools
                    and not isinstance(receipts_by_call.get(c.get("id")), dict)
                    for c in calls
                ):
                    continue
            elif first.get("role") == "tool":
                continue
            selected.append(indexes)
        # Keep recent completed groups when meaningful earlier history exists.
        older = selected[:-2]
        if older and estimate_tokens([messages[i] for u in older for i in u]) > min(
            2048, self.input_budget // 4
        ):
            selected = older
        return {i for unit in selected for i in unit}

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
