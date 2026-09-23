"""Bounded, content-free evidence for completed provider requests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def fingerprint(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def count_images(messages: list[dict[str, Any]]) -> int:
    return sum(
        part.get("type") == "image_url"
        for message in messages
        if isinstance(message.get("content"), list)
        for part in message["content"]
        if isinstance(part, dict)
    )


def numeric_usage(usage: Mapping[str, Any]) -> dict[str, int]:
    allowed = (
        "prompt_tokens",
        "input_tokens",
        "completion_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    )
    return {
        name: int(usage[name])
        for name in allowed
        if isinstance(usage.get(name), (int, float))
        and not isinstance(usage[name], bool)
        and 0 <= usage[name] < 1_000_000_000
    }


def prompt_cache_tokens(usage: Mapping[str, Any]) -> tuple[int, int] | None:
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    details = usage.get("prompt_tokens_details", usage.get("input_tokens_details"))
    cached = usage.get("prompt_cache_hit_tokens")
    if cached is None and isinstance(details, Mapping):
        cached = details.get("cached_tokens")
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in (prompt, cached)
    ):
        return None
    if prompt < 0 or cached < 0 or cached > prompt:
        return None
    return int(cached), int(prompt - cached)


def prefix_change(
    previous: Mapping[str, Any] | None,
    system_hash: str,
    tool_hashes: list[str],
    *,
    compacted: bool,
) -> tuple[bool, str]:
    if previous is None:
        return False, "initial"
    system_changed = previous.get("system_hash") != system_hash
    old = previous.get("tool_hashes")
    if old == tool_hashes:
        return system_changed, "unchanged"
    if isinstance(old, list) and len(old) < len(tool_hashes) and old == tool_hashes[: len(old)]:
        return system_changed, "loading"
    return system_changed, "compaction" if compacted else "other"
