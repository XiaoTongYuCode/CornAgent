"""Local operator inspection and reproducible end-to-end Agent evaluations.

Run with `uv run python -m app.platform_cli inspect|eval`. Neither command
changes the schema. Evaluations create test sessions and delete them by default.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.database import Database
from app.persistence.models import AgentRun, AgentSubagentTask
from app.settings import Settings


def inspect_runtime(limit: int = 20) -> dict:
    if not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000.")
    database = Database(Settings())
    now = datetime.now(UTC)
    try:
        with database.session_factory() as db:
            runs = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit))
            recent = list(runs)
            stale_leases = list(
                db.scalars(
                    select(AgentRun.id)
                    .where(AgentRun.status == "running", AgentRun.lease_expires_at < now)
                    .order_by(AgentRun.lease_expires_at, AgentRun.id)
                )
            )
            tasks = db.scalars(
                select(AgentSubagentTask)
                .where(AgentSubagentTask.status.in_(("queued", "running")))
                .limit(1000)
            )
            active_tasks = list(tasks)
            return {
                "run_statuses": dict(Counter(run.status for run in recent)),
                "stale_leases": stale_leases,
                "recent_runs": [
                    {"id": run.id, "status": run.status, "error_code": run.error_code}
                    for run in recent
                ],
                "active_subtasks": dict(Counter(task.status for task in active_tasks)),
            }
    finally:
        database.close()


def score_case(case: dict, status: str, markdown: str) -> dict:
    required = case.get("contains", [])
    if not isinstance(required, list) or not all(isinstance(text, str) for text in required):
        raise ValueError("Each eval case must have a list of expected strings in 'contains'.")
    missing = [text for text in required if text not in markdown]
    return {
        "name": case["name"],
        "passed": status == "completed" and not missing,
        "status": status,
        "missing": missing,
        "response": markdown,
    }


def evaluate(url: str, dataset: dict, timeout: float, keep_sessions: bool) -> dict:
    if timeout <= 0:
        raise ValueError("Timeout must be positive.")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must contain a nonempty 'cases' list.")
    results = []
    headers = {"X-CornAgent-Request": "1"}
    if os.environ.get("CORNAGENT_EVAL_COOKIE"):
        headers["Cookie"] = os.environ["CORNAGENT_EVAL_COOKIE"]
    with httpx.Client(base_url=url.rstrip("/") + "/", headers=headers, timeout=15) as client:
        client.post("auth/session").raise_for_status()
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("prompt"), str):
                raise ValueError("Every case needs a prompt and name.")
            if not isinstance(case.get("name"), str):
                raise ValueError("Every case needs a name.")
            created = client.post(
                "agent/sessions",
                json={"title": "Eval: " + case["name"], "content": case["prompt"]},
                headers={"Idempotency-Key": str(uuid4())},
            )
            created.raise_for_status()
            session_id = created.json()["session"]["id"]
            run_id = created.json()["run"]["id"]
            status = "timeout"
            try:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    detail = client.get(f"agent/sessions/{session_id}")
                    detail.raise_for_status()
                    messages = detail.json()["messages"]
                    answer = next(
                        (
                            item
                            for item in messages
                            if item["role"] == "assistant"
                            and (item.get("run") or {}).get("id") == run_id
                        ),
                        None,
                    )
                    if answer and answer["run"]["status"] in (
                        "completed",
                        "failed",
                        "cancelled",
                        "waiting_for_user",
                    ):
                        status = answer["run"]["status"]
                        results.append(score_case(case, status, answer["markdown"]))
                        break
                    time.sleep(0.5)
                else:
                    results.append(score_case(case, "timeout", ""))
            finally:
                if not keep_sessions:
                    if status in ("timeout", "waiting_for_user"):
                        client.post(
                            f"agent/runs/{run_id}/cancel",
                            headers={"Idempotency-Key": str(uuid4())},
                        ).raise_for_status()
                    client.delete(f"agent/sessions/{session_id}").raise_for_status()
    return {
        "passed": sum(result["passed"] for result in results),
        "total": len(results),
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CornAgent operator tools")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Inspect recent runs and stale leases")
    inspect.add_argument("--limit", type=int, default=20)
    evaluation = commands.add_parser("eval", help="Run JSON cases against a local deployment")
    evaluation.add_argument("dataset", type=Path)
    evaluation.add_argument("--url", default="http://127.0.0.1:8000/api/v1")
    evaluation.add_argument("--timeout", type=float, default=120)
    evaluation.add_argument("--keep-sessions", action="store_true")
    evaluation.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        result = inspect_runtime(args.limit)
    else:
        result = evaluate(
            args.url,
            json.loads(args.dataset.read_text(encoding="utf-8")),
            args.timeout,
            args.keep_sessions,
        )
        if args.report:
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "eval" and result["passed"] != result["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
