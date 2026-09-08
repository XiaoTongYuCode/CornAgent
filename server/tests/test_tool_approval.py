import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent.model import ModelStreamEvent
from app.agent.runtime import AgentRuntime
from app.agent.tools import ToolApproval, ToolDefinition, build_default_tool_catalog
from app.main import create_app
from app.persistence.models import AgentRun
from tests.test_runtime import FakeAgentEventStream, FinalAgentModel

"""Approval is a durable tool continuation, independent of attachment semantics."""


@pytest.fixture
def client(settings):
    with TestClient(
        create_app(settings, model_client=FinalAgentModel(), event_stream=FakeAgentEventStream())
    ) as client:
        client.portal.call(client.app.state.agent_runtime.close)
        yield client


def _wait_for_snapshot_status(client, runtime, run_id, status):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snapshot = client.portal.call(runtime.snapshot, run_id)
        if snapshot and snapshot.run.status == status:
            return snapshot
        time.sleep(0.01)
    pytest.fail(f"Did not reach {status}: {snapshot}")


@pytest.mark.parametrize(
    "case", ["approve", "cancel", "ignore", "restart", "crash", "retry", "changed"]
)
def test_generic_tool_approval_resumes_original_call_before_model(client, case):
    effects = {}
    executions = []
    crashed_after_write = asyncio.Event()

    class Model:
        def __init__(self):
            self.requests = []

        async def stream(self, messages):
            self.requests.append(messages)
            if len(self.requests) == 1:
                yield ModelStreamEvent(
                    kind="tool_calls",
                    tool_calls=[
                        {
                            "id": "change-1",
                            "name": "apply_change",
                            "arguments": '{"target":"draft-1"}',
                        }
                    ],
                )
                return
            result = json.loads(messages[-1]["content"])
            assert messages[-1]["name"] == "apply_change"
            assert messages[-1]["tool_call_id"] == "change-1"
            assert all(item.get("name") != "ask_user" for item in messages)
            assert "private-plan" not in json.dumps(messages)
            assert bool(effects) == (case not in {"cancel", "ignore"})
            assert result["outcome"] == ("cancelled" if case in {"cancel", "ignore"} else "updated")
            yield ModelStreamEvent(kind="content", content="操作已处理。")

    model = Model()

    async def prepare(arguments, context):
        return ToolApproval(
            query="将草稿标为完成？",
            approve_label="应用变更",
            payload={"target": arguments["target"], "revision": 1, "private-plan": "server-only"},
        )

    async def execute(payload, context):
        assert len(model.requests) == 1
        assert context.tool_call_id == "change-1"
        executions.append(dict(payload))
        if case == "changed" and payload["revision"] == 1:
            return ToolApproval(
                query="草稿已变化，应用更新后的变更？", payload={**payload, "revision": 2}
            )
        effects.setdefault(context.tool_call_id, payload["target"])
        if len(executions) == 1:
            if case == "retry":
                raise TimeoutError("response lost after write")
            if case == "crash":
                crashed_after_write.set()
                raise asyncio.CancelledError
        return {"ok": True, "outcome": "updated"}

    tool = ToolDefinition(
        name="apply_change",
        description="Apply a requested draft change.",
        parameters={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
        handler=prepare,
        approval_handler=execute,
        status_label="正在应用变更",
    )
    catalog = build_default_tool_catalog([tool])

    def new_runtime():
        runtime = AgentRuntime(
            session_factory=client.app.state.database.session_factory,
            redis_url=None,
            model="fake",
            api_key="test",
            api_base=None,
            model_timeout_seconds=30,
            reconcile_seconds=60,
            stream_max_events=100,
            model_client=model,
            event_stream=FakeAgentEventStream(),
            tool_catalog=catalog,
        )
        client.app.state.agent_runtime = runtime
        client.portal.call(runtime.start)
        return runtime

    runtime = new_runtime()
    headers = {}
    try:
        created = client.post(
            "/api/v1/agent/sessions",
            headers={**headers, "Idempotency-Key": "create"},
            json={"content": "应用草稿变更"},
        )
        assert created.status_code == 200, created.text
        run_id = created.json()["run"]["id"]
        waiting = _wait_for_snapshot_status(client, runtime, run_id, "waiting_for_user")
        assert len(model.requests) == 1 and not executions
        assert not any(part.kind == "tool_call" for part in waiting.content_parts)
        question = next(part for part in waiting.content_parts if part.kind == "user_question")
        assert question.metadata["interaction"] == "tool_approval"
        assert "private-plan" not in waiting.model_dump_json()
        question_id = question.metadata["question_id"]
        if case == "restart":
            client.portal.call(runtime.close)
            runtime = new_runtime()
        path = f"/api/v1/agent/questions/{question_id}/respond"
        invalid = client.post(
            path,
            headers={**headers, "Idempotency-Key": "free-text"},
            json={"action": "answer", "content": "同意"},
        )
        assert invalid.status_code == 422
        decision = (
            {"action": "cancel"}
            if case == "ignore"
            else {
                "action": "answer",
                "option_id": "option-2" if case == "cancel" else "option-1",
            }
        )
        answer_headers = {**headers, "Idempotency-Key": "approve"}
        response = client.post(path, headers=answer_headers, json=decision)
        assert response.status_code == 200, response.text
        replay = client.post(path, headers=answer_headers, json=decision)
        assert replay.status_code == 200
        assert replay.json()["question_id"] == response.json()["question_id"]
        assert replay.json()["selected_option_id"] == response.json()["selected_option_id"]
        if case == "crash":
            # The callback wrote, then disappeared before persisting its result.
            client.portal.call(asyncio.wait_for, crashed_after_write.wait(), 5)
            client.portal.call(runtime.close)
            with client.app.state.database.session_factory() as db:
                db.get(AgentRun, run_id).lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
            runtime = new_runtime()
        if case == "changed":
            revised = _wait_for_snapshot_status(client, runtime, run_id, "waiting_for_user")
            pending = [
                p
                for p in revised.content_parts
                if p.kind == "user_question" and p.metadata["status"] == "pending"
            ]
            assert len(pending) == 1 and len(model.requests) == 1 and not effects
            assert pending[0].metadata["question_id"] != question_id
            assert (
                client.post(
                    f"/api/v1/agent/questions/{pending[0].metadata['question_id']}/respond",
                    headers={**headers, "Idempotency-Key": "approve-revision"},
                    json={"action": "answer", "option_id": "option-1"},
                ).status_code
                == 200
            )
        final = _wait_for_snapshot_status(client, runtime, run_id, "completed")
        assert len(model.requests) == 2
        assert len(effects) == (0 if case in {"cancel", "ignore"} else 1)
        assert len(executions) == (
            0 if case in {"cancel", "ignore"} else 2 if case in {"crash", "retry", "changed"} else 1
        )
        parts = [part for part in final.content_parts if part.kind == "tool_call"]
        assert len(parts) == 1
        assert parts[0].title == ("已取消操作" if case in {"cancel", "ignore"} else "已应用变更")
        with client.app.state.database.session_factory() as db:
            assert "pending_tool_approval" not in db.get(AgentRun, run_id).checkpoint
    finally:
        client.portal.call(runtime.close)


def test_approval_migration_preserves_a_pending_question(settings, tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session

    from app.persistence.agent_runtime import AgentRepository
    from app.persistence.models import AgentQuestion
    from app.persistence.scope import LOCAL_SCOPE

    url = f"sqlite+pysqlite:///{tmp_path / 'approval-upgrade.db'}"
    monkeypatch.setenv("CORNAGENT_DATABASE_URL", url)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    command.upgrade(config, "0003_source_history")
    engine = create_engine(url)
    with Session(engine) as db:
        repo = AgentRepository(db)
        _, run = repo.create_session_run(
            LOCAL_SCOPE, content="before upgrade", idempotency_key="create"
        )
        claim, fence, _ = repo.claim_run(run.id, "worker")
        _, question_id = repo.pause_for_question(
            run.id,
            "worker",
            fence,
            tool_call_id="ordinary",
            arguments={
                "query": "Keep this question?",
                "options": [{"content": "yes", "description": ""}],
            },
            provider_messages=[],
            usage={},
        )
    command.upgrade(config, "head")
    with Session(engine) as db:
        question = db.get(AgentQuestion, question_id)
        assert question.status == "pending" and question.tool_name == "ask_user"
        assert question.query == "Keep this question?"
    indexes = inspect(engine).get_indexes("cornagent_agent_questions")
    assert any(
        i["name"] == "uq_cornagent_agent_question_tool_call" and i["unique"] for i in indexes
    )
    command.downgrade(config, "0003_source_history")
    with Session(engine) as db:
        assert db.get(AgentQuestion, question_id).status == "pending"
    command.upgrade(config, "head")
    engine.dispose()
