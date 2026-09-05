"""JSON contracts adapted from agent_server archive 1c934f0d6ed2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

SubagentReturnWhen = Literal["any", "all"]
TERMINAL_TASK_STATUSES = ("completed", "failed", "needs_input", "cancelled", "timed_out")


@dataclass(frozen=True, slots=True)
class SubagentOptions:
    enabled: bool = True
    spawn_max_tasks: int = 10
    run_max_tasks: int = 10
    run_max_concurrency: int = 5
    timeout_seconds: float = 600
    wait_default_seconds: int = 300
    result_batch_max_bytes: int = 64 * 1024
    result_projection_max_chars: int = 8000
    final_candidate_max_bytes: int = 256 * 1024
    reconcile_seconds: float = 1


@dataclass(frozen=True, slots=True)
class SubagentTaskSpec:
    task_key: str
    title: str
    instruction: str
    expected_output: str
    ordinal: int
    profile: Literal["researcher", "analyst", "verifier"] = "researcher"
    required: bool = True

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SpawnSubagentsRequest:
    tasks: tuple[SubagentTaskSpec, ...]
    max_concurrency: int


@dataclass(frozen=True, slots=True)
class SubagentToolContext:
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class OperationRequest:
    name: str
    tasks: tuple[SubagentTaskSpec, ...] = ()
    max_concurrency: int = 5
    task_ids: tuple[str, ...] = ()
    group_id: str | None = None
    return_when: SubagentReturnWhen = "all"
    timeout_seconds: int = 300
