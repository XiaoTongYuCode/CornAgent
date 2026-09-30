"""Run state edges shared by the HTTP, reconciler and subagent transactions.

Call only while holding the Run row lock. This validates an edge; the caller
remains responsible for updating the lease, checkpoint and event atomically.
"""

from __future__ import annotations

from typing import Literal, Protocol

RunStatus = Literal[
    "pending",
    "running",
    "waiting_for_user",
    "waiting_for_subagents",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
]

TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled")
ACTIVE_RUN_STATUSES = (
    "pending",
    "running",
    "waiting_for_user",
    "waiting_for_subagents",
    "cancelling",
)

_EDGES: dict[str, frozenset[str]] = {
    "pending": frozenset(
        {"running", "waiting_for_user", "waiting_for_subagents", "failed", "cancelled"}
    ),
    "running": frozenset(
        {"pending", "waiting_for_user", "waiting_for_subagents", "completed", "failed", "cancelled"}
    ),
    "waiting_for_user": frozenset({"pending", "failed", "cancelled"}),
    "waiting_for_subagents": frozenset({"pending", "failed", "cancelled"}),
    "cancelling": frozenset({"cancelled", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class MutableRun(Protocol):
    status: str


def transition_run(run: MutableRun, target: RunStatus) -> None:
    """Reject an impossible transition before mutating a locked Run row."""

    if target not in _EDGES.get(run.status, ()):
        raise ValueError(f"Invalid Agent Run transition: {run.status} -> {target}")
    run.status = target
