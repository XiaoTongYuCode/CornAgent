"""Conservative, server-owned operation evidence for a single agent turn.

Only an explicitly declared write tool can confirm a business change. A transport
acknowledgement, model prose, arguments and draft objects are never write evidence.
Integrations may return ``operation_receipt`` or supply an ``outcome_projector``.
The projector must return a public, structured receipt, not private result content.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from urllib.parse import unquote

from app.agent.tools.base import ToolDefinition

OperationState = Literal["committed", "partial", "draft", "noop", "failed", "unknown"]
STATES: tuple[OperationState, ...] = ("committed", "partial", "draft", "noop", "failed", "unknown")
_STATE_ALIASES: dict[str, OperationState] = {
    **{
        key: "committed"
        for key in ("committed", "applied", "saved", "created", "updated", "deleted")
    },
    **{key: "partial" for key in ("partial", "partially_committed", "partial_failure")},
    **{
        key: "draft"
        for key in ("draft", "prepared", "pending", "queued", "running", "confirm_required")
    },
    **{
        key: "noop"
        for key in (
            "noop",
            "unchanged",
            "existing",
            "not_found",
            "cancelled",
            "not_run",
            "not_written",
        )
    },
    **{key: "failed" for key in ("failed", "rejected", "error")},
    **{key: "unknown" for key in ("unknown", "incomplete", "ambiguous")},
}
_MAX_ITEMS = 1000
_MAX_CHANGES = 100
OPERATION_METADATA_MAX_BYTES = 32 * 1024
TURN_OPERATION_DETAILS_MAX_BYTES = 128 * 1024


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, limit: int = 300) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _state(row: Mapping[str, Any]) -> OperationState:
    states = {
        _STATE_ALIASES[value]
        for key in ("state", "write_state", "outcome", "status")
        if isinstance(value := row.get(key), str) and value in _STATE_ALIASES
    }
    if row.get("committed") is True:
        states.add("committed")
    if row.get("executed") is False:
        states.add("noop")
    # An explicit unknown result takes priority over a success flag. Conflicting
    # commit/failure evidence must be recovered, never silently presented as saved.
    if "unknown" in states or ("committed" in states and len(states) > 1):
        return "unknown"
    if "partial" in states:
        return "partial"
    if row.get("ok") is False and "committed" in states:
        return "unknown"
    if states:
        for state in ("failed", "draft", "noop", "committed"):
            if state in states:
                return state
    error = _object(row.get("error"))
    if (
        not states
        and row.get("ok") is False
        and (
            row.get("retryable") is True
            or (
                error.get("type")
                and error.get("type")
                not in {
                    "UnknownTool",
                    "ToolScopeDenied",
                    "ToolNotLoaded",
                    "InvalidToolArguments",
                    "ExclusiveToolBatch",
                    "InvalidToolBatch",
                }
            )
        )
    ):
        # Exceptions can arrive after an external write. Missing/invalid results
        # do not establish that the external operation was rolled back.
        return "unknown"
    return "failed" if row.get("ok") is False else "unknown"


def _receipt(value: Any) -> Mapping[str, Any]:
    row = _object(value)
    receipt = row.get("operation_receipt")
    return _object(receipt) if receipt is not None else row


def _has_state_signal(*layers: Mapping[str, Any]) -> bool:
    return any(
        row.get("ok") is False
        or row.get("committed") is True
        or row.get("executed") is False
        or any(
            isinstance(row.get(key), str) and row[key] in _STATE_ALIASES
            for key in ("state", "write_state", "outcome", "status")
        )
        for row in layers
    )


def _combined_state(value: Any) -> OperationState:
    raw, receipt = _object(value), _receipt(value)
    if raw is receipt:
        return _state(raw)
    states = {_state(row) for row in (raw, receipt) if _has_state_signal(row)}
    if "unknown" in states or ("committed" in states and len(states) > 1):
        return "unknown"
    for state in ("partial", "failed", "draft", "noop", "committed"):
        if state in states:
            return state
    return "unknown"


def normalize_outcome(result: Any) -> dict[str, Any]:
    """Summarize structured execution evidence without modifying the tool result.

    Counts retain leaf operations and otherwise unrepresented aggregate failures.
    Batches retain committed children even when siblings failed. More than 1000 leaves
    or 8 nested batches fail closed.
    """
    counts = dict.fromkeys(STATES, 0)
    leaves: list[tuple[Mapping[str, Any], OperationState]] = []
    truncated = False

    def visit(value: Any, depth: int = 0, ancestor_guard: OperationState | None = None) -> None:
        nonlocal truncated
        if len(leaves) >= _MAX_ITEMS or depth > 8:
            truncated = True
            return
        row = _receipt(value)
        state = _combined_state(value)
        items = row.get("items")
        if isinstance(items, list) and items:
            first_child = len(leaves)
            guard = ancestor_guard or (
                state
                if state in {"unknown", "draft", "noop"} and _has_state_signal(_object(value), row)
                else None
            )
            for item in items:
                visit(item, depth + 1, guard)
                if truncated:
                    break
            child_states = {state for _, state in leaves[first_child:]}
            # Failed batches may have successful children, but an unexplained
            # aggregate failure must never disappear from the model's fact counts.
            if state in {"failed", "partial"} and state not in child_states:
                counts[state] += 1
            elif (
                state == "unknown"
                and _has_state_signal(_object(value), row)
                and "unknown" not in child_states
            ):
                counts["unknown"] += 1
            return
        if ancestor_guard is not None and state in {"committed", "partial"}:
            state = "unknown"
        counts[state] += 1
        leaves.append((row, state))

    visit(result)
    if truncated:
        counts["unknown"] += 1
    populated = [state for state in STATES if counts[state]]
    if "unknown" in populated:
        state: OperationState = "partial" if counts["committed"] else "unknown"
    elif len(populated) == 1:
        state = populated[0]
    elif counts["committed"] or counts["partial"]:
        state = "partial"
    elif counts["failed"]:
        state = "failed"
    elif counts["draft"]:
        state = "draft"
    else:
        state = "noop"
    changes: list[dict[str, Any]] = []
    for row, leaf_state in leaves:
        if leaf_state not in {"committed", "partial"}:
            continue
        source = row.get("changes")
        if not isinstance(source, list):
            source = [row] if row.get("resource_id") else []
        for value in source:
            change = _object(value)
            # A partial operation needs evidence for each committed resource.
            if leaf_state == "partial" and _state(change) != "committed":
                continue
            if (
                any(
                    key in change
                    for key in ("state", "status", "outcome", "write_state", "committed")
                )
                and _state(change) != "committed"
            ):
                continue
            projected = _change(change)
            if projected and _change_was_truncated(change):
                truncated = True
            if projected and len(changes) < _MAX_CHANGES:
                changes.append(projected)
    normalized: dict[str, Any] = {"state": state, "counts": counts, "changes": changes}
    if truncated or len(changes) == _MAX_CHANGES:
        normalized["truncated"] = True
    # Human result messages are not facts and deliberately never enter the system notice.
    error_code = _text(_object(result).get("error_code"), 100)
    if error_code:
        normalized["error_code"] = error_code
    return normalized


def _href(value: Any) -> str:
    href = _text(value, 2048)
    decoded = unquote(href)
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(char) < 32 for char in decoded)
    ):
        return ""
    return href


def _display(value: Any) -> str | None:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, (int, float, bool)):
        return json.dumps(value, ensure_ascii=False)
    return None


def _change(row: Mapping[str, Any]) -> dict[str, Any] | None:
    resource_id = _text(row.get("resource_id"), 200)
    resource_type = _text(row.get("resource_type"), 100)
    action = row.get("action")
    if (
        not resource_id
        or not resource_type
        or not isinstance(action, str)
        or action not in {"create", "update", "delete", "attach"}
    ):
        return None
    change: dict[str, Any] = {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "title": _text(row.get("title")),
        "action": action,
    }
    href = _href(row.get("href"))
    if href and action != "delete":
        change["href"] = href
    fields: list[dict[str, str]] = []
    raw_fields = row.get("fields")
    if isinstance(raw_fields, list):
        for value in raw_fields[:40]:
            field = _object(value)
            label = _text(field.get("label"), 100)
            after = _display(field.get("value")) if "value" in field else None
            if label and after is not None:
                saved = {"label": label, "value": after}
                before = _display(field.get("before")) if "before" in field else None
                if before is not None:
                    saved["before"] = before
                fields.append(saved)
    if fields:
        change["fields"] = fields
    return change


def _change_was_truncated(row: Mapping[str, Any]) -> bool:
    for key, limit in (
        ("resource_id", 200),
        ("resource_type", 100),
        ("title", 300),
        ("href", 2048),
    ):
        if isinstance(row.get(key), str) and len(row[key].strip()) > limit:
            return True
    fields = row.get("fields")
    if not isinstance(fields, list):
        return False
    if len(fields) > 40:
        return True
    return any(
        isinstance(_object(field).get(key), str) and len(_object(field)[key]) > limit
        for field in fields
        for key, limit in (("label", 100), ("before", 4000), ("value", 4000))
    )


def operation_metadata(definition: ToolDefinition | None, result: Any) -> dict[str, Any]:
    """Return a safe addition to an existing durable tool_call part's metadata."""
    if definition is None or definition.read_only or definition.effect in {"read", "control"}:
        return {}
    if definition.effect != "write":
        # Legacy ordinary tools remain usable, but are not upgraded to confirmed
        # writes merely because read_only was omitted. Runtime controls are ignored.
        if definition.runtime_handler is not None:
            return {}
        normalized = normalize_outcome(None)
    else:
        raw = _object(result)
        cancelled = raw.get("outcome") == "cancelled" or raw.get("executed") is False
        receipt = raw if cancelled else definition.project_result(result)
        if not cancelled and definition.outcome_projector is not None:
            try:
                receipt = definition.outcome_projector(result)
            except Exception:  # noqa: BLE001 - evidence failure must not alter execution
                receipt = None
        normalized = normalize_outcome(receipt)
    changes = normalized.pop("changes")
    return bound_operation_metadata({"operation_outcome": normalized, "changes": changes})


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def bound_operation_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Bound the entire public operation envelope; immutable full receipts stay untouched.

    Preserve outcome counts and resource headers before adding saved fields in
    their original order. Omitted details are explicit and can be reread by receipt.
    """
    outcome = dict(_object(metadata.get("operation_outcome")))
    source = metadata.get("changes")
    changes = list(source) if isinstance(source, list) else []
    result = {"operation_outcome": outcome, "changes": changes}
    if _json_bytes(result) <= OPERATION_METADATA_MAX_BYTES:
        return result
    outcome["truncated"] = True
    previews: list[dict[str, Any]] = []
    result["changes"] = previews
    # Headers provide a useful resource inventory even when early fields are huge.
    for value in changes:
        header = {key: item for key, item in _object(value).items() if key != "fields"}
        previews.append(header)
        if _json_bytes(result) > OPERATION_METADATA_MAX_BYTES:
            previews.pop()
            break
    exhausted = False
    for preview, original in zip(previews, changes, strict=False):
        fields = _object(original).get("fields")
        if not isinstance(fields, list):
            continue
        selected: list[Any] = []
        preview["fields"] = selected
        for field in fields:
            selected.append(field)
            if _json_bytes(result) > OPERATION_METADATA_MAX_BYTES:
                selected.pop()
                exhausted = True
                break
        if not selected:
            del preview["fields"]
        if exhausted:
            break
    return result


def trim_turn_operation_details(
    parts: Sequence[Mapping[str, Any]],
    *,
    max_detail_bytes: int = TURN_OPERATION_DETAILS_MAX_BYTES,
) -> list[dict[str, Any]]:
    """Return copied parts with at most 128 KiB of aggregate operation details.

    Keep newest details first, and retain every operation's state/counts even when
    its resource details are removed. Counts/other content are not this budget.
    Call at a common checkpoint boundary for both live and safe content parts.
    """
    # Empty changes arrays still occupy two bytes per operation in JSON.
    baseline = 2 * sum(
        bool(_object(_object(part.get("metadata")).get("operation_outcome")))
        for part in parts
        if part.get("kind") == "tool_call"
    )
    remaining = max(0, max_detail_bytes - baseline)
    result: list[dict[str, Any]] = []
    for part in reversed(parts):
        copied = dict(part)
        metadata = _object(part.get("metadata"))
        if part.get("kind") == "tool_call" and _object(metadata.get("operation_outcome")):
            bounded = bound_operation_metadata(metadata)
            cost = max(0, _json_bytes(bounded["changes"]) - 2)
            if cost > remaining:
                bounded["changes"] = []
                bounded["operation_outcome"]["truncated"] = True
            else:
                remaining -= cost
            copied["metadata"] = {**metadata, **bounded}
        result.append(copied)
    return list(reversed(result))


def summarize_turn(parts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Deterministic summary from persisted server metadata, excluding model text."""
    operations: dict[str, Mapping[str, Any]] = {}
    changes: list[dict[str, Any]] = []
    for part in parts:
        if part.get("kind") != "tool_call":
            continue
        metadata = _object(part.get("metadata"))
        outcome = _object(metadata.get("operation_outcome"))
        if outcome.get("state") not in STATES:
            continue
        operations[str(part.get("id", ""))] = metadata
    counts = dict.fromkeys(STATES, 0)
    for metadata in operations.values():
        outcome = _object(metadata.get("operation_outcome"))
        row_counts = _object(outcome.get("counts"))
        for state in STATES:
            value = row_counts.get(state)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                counts[state] += value
        raw_changes = metadata.get("changes")
        if outcome.get("state") in {"committed", "partial"} and isinstance(raw_changes, list):
            for change in raw_changes:
                projected = _change(_object(change))
                if projected:
                    changes.append(projected)
    return {
        "operation_count": len(operations),
        "counts": counts,
        "changes": changes,
        "has_unresolved": any(counts[state] for state in ("partial", "draft", "failed", "unknown")),
    }


def facts_notice(parts: Sequence[Mapping[str, Any]]) -> str:
    """System instruction plus data-only counts; never elevate tool prose to policy."""
    summary = summarize_turn(parts)
    if not summary["operation_count"]:
        return ""
    return (
        "Server execution evidence for this turn (authoritative for operation status): "
        + json.dumps(
            {"operation_count": summary["operation_count"], "counts": summary["counts"]},
            separators=(",", ":"),
        )
        + ". Only claim a saved/applied/deleted business change when its structured tool receipt "
        "explicitly confirms committed state. Transport ok:true, generated text, "
        "submitted arguments, "
        "drafts and prepared plans are not committed writes. A failed batch may contain committed "
        "children: preserve those successes and report unresolved siblings separately. Unknown "
        "means the operation may already have happened: read its original receipt or verify the "
        "target before retrying; never duplicate a write to resolve uncertainty. Ground factual "
        "claims in the actual tool result/material evidence; if the full result was truncated, "
        "read_tool_result before citing missing details. Do not turn unverified claims into facts."
    )
