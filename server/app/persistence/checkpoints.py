"""Size and replay safety rules for durable model checkpoints."""

from __future__ import annotations

import json
from typing import Any

from app.agent.model_context import checkpoint_byte_limit
from app.persistence.errors import DomainError

DURABLE_CHECKPOINT_MAX_BYTES = 3 * 1024 * 1024
DURABLE_CHECKPOINT_RESULT_RESERVE_BYTES = 64 * 1024
DURABLE_CHECKPOINT_SEED_MAX_BYTES = (
    DURABLE_CHECKPOINT_MAX_BYTES - DURABLE_CHECKPOINT_RESULT_RESERVE_BYTES
)


def checkpoint_json_size_bytes(payload: dict[str, Any]) -> int:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DomainError(
            "invalid_agent_checkpoint",
            "Agent checkpoint data must be JSON serializable.",
        ) from exc
    return len(encoded)


def ensure_checkpoint_size(
    payload: dict[str, Any],
    *,
    max_bytes: int | None = None,
) -> None:
    if max_bytes is None:
        max_bytes = checkpoint_byte_limit(int(payload.get("context_window_tokens", 64000)))
    size_bytes = checkpoint_json_size_bytes(payload)
    if size_bytes > max_bytes:
        raise DomainError(
            "agent_checkpoint_too_large",
            f"Agent checkpoint is {size_bytes} bytes; the durable limit is {max_bytes} bytes.",
        )


def ordinary_tool_batch_marker(checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    marker = checkpoint.get("ordinary_tool_batch")
    return dict(marker) if isinstance(marker, dict) else None


def has_inflight_ordinary_tool_batch(checkpoint: dict[str, Any]) -> bool:
    marker = ordinary_tool_batch_marker(checkpoint)
    return marker is not None and marker.get("phase") == "executing"
