"""Read-only site-wide aggregates of retained runs and telemetry."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.api.deps import CurrentIdentity, Db
from app.persistence.models import AgentRun, UsageEvent

router = APIRouter(prefix="/agent")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _tokens(usage: dict, key: str) -> int:
    value = usage.get(key)
    return (
        max(0, int(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
    )


@router.get("/usage")
def usage_statistics(
    request: Request, db: Db, _identity: CurrentIdentity, days: int = Query(30, ge=7, le=90)
):
    if days not in (7, 30, 90):
        raise HTTPException(status_code=422, detail="days must be 7, 30 or 90")
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    buckets = {
        (start + timedelta(days=i)).date().isoformat(): {
            "date": (start + timedelta(days=i)).date().isoformat(),
            "runs": 0,
            "inputTokens": 0,
            "outputTokens": 0,
            "durationSeconds": None,
        }
        for i in range(days)
    }
    statuses = dict.fromkeys(("completed", "failed", "cancelled", "active"), 0)
    hours = [[0] * 24 for _ in range(7)]
    durations: dict[str, list[float]] = {day: [] for day in buckets}
    sessions: set[str] = set()
    session_spans = {}
    reported = 0
    query = (
        select(
            AgentRun.session_id,
            AgentRun.status,
            AgentRun.created_at,
            AgentRun.started_at,
            AgentRun.completed_at,
            AgentRun.provider_usage,
        )
        .where(
            AgentRun.created_at >= start,
            AgentRun.created_at <= now,
        )
        .execution_options(yield_per=500)
    )
    for row in db.execute(query):
        created = _utc(row.created_at)
        day = created.date().isoformat()
        bucket = buckets[day]
        bucket["runs"] += 1
        sessions.add(row.session_id)
        end = _utc(row.completed_at) if row.completed_at else created
        previous = session_spans.get(row.session_id, (created, end))
        session_spans[row.session_id] = (min(previous[0], created), max(previous[1], end))
        statuses[row.status if row.status in statuses else "active"] += 1
        hours[created.weekday()][created.hour] += 1
        provider = row.provider_usage or {}
        reported += int(
            any(
                isinstance(provider.get(k), (int, float))
                for k in ("prompt_tokens", "completion_tokens")
            )
        )
        bucket["inputTokens"] += _tokens(provider, "prompt_tokens")
        bucket["outputTokens"] += _tokens(provider, "completion_tokens")
        if row.status == "completed" and row.started_at and row.completed_at:
            durations[day].append(
                max(0, (_utc(row.completed_at) - _utc(row.started_at)).total_seconds())
            )
    elapsed = []
    for day, values in durations.items():
        if values:
            buckets[day]["durationSeconds"] = round(sum(values) / len(values), 2)
            elapsed.extend(values)
    terminal = sum(statuses[key] for key in ("completed", "failed", "cancelled"))
    groups = {"tool": {}, "model": {}}
    if request.app.state.telemetry_local:
        events = db.scalars(
            select(UsageEvent)
            .where(
                UsageEvent.created_at >= start,
                UsageEvent.created_at <= now,
            )
            .execution_options(yield_per=500)
        )
        for event in events:
            group = groups[event.kind]
            item = group.setdefault(
                event.name,
                {
                    "name": event.name,
                    "calls": 0,
                    "failures": 0,
                    "durationSeconds": 0,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "reportedCalls": 0,
                    "childCalls": 0,
                },
            )
            item["calls"] += 1
            item["failures"] += int(event.status != "completed")
            item["durationSeconds"] += event.duration_seconds
            item["inputTokens"] += event.input_tokens or 0
            item["outputTokens"] += event.output_tokens or 0
            item["reportedCalls"] += int(
                event.input_tokens is not None or event.output_tokens is not None
            )
            item["childCalls"] += int(event.execution_scope == "child")
        for group in groups.values():
            for item in group.values():
                item["durationSeconds"] = round(item["durationSeconds"] / item["calls"], 2)
    return {
        "telemetryEnabled": request.app.state.settings.telemetry_enabled,
        "telemetryLocal": request.app.state.telemetry_local,
        "tools": sorted(groups["tool"].values(), key=lambda item: -item["calls"]),
        "models": sorted(groups["model"].values(), key=lambda item: -item["calls"]),
        "activeDays": sum(int(b["runs"] > 0) for b in buckets.values()),
        "averageSessionSeconds": round(
            sum((end - begin).total_seconds() for begin, end in session_spans.values())
            / len(sessions),
            2,
        )
        if sessions
        else None,
        "days": days,
        "from": start.isoformat(),
        "to": now.isoformat(),
        "timezone": "UTC",
        "totalRuns": sum(statuses.values()),
        "sessions": len(sessions),
        "inputTokens": sum(b["inputTokens"] for b in buckets.values()),
        "outputTokens": sum(b["outputTokens"] for b in buckets.values()),
        "reportedRuns": reported,
        "successRate": round(statuses["completed"] / terminal * 100, 1) if terminal else None,
        "averageDurationSeconds": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "statuses": statuses,
        "daily": list(buckets.values()),
        "hours": hours,
    }
