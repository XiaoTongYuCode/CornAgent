import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agent.model import ModelStreamEvent
from app.database import Database
from app.persistence.agent_runtime import AgentRepository
from app.persistence.errors import DomainError
from app.persistence.models import AgentMessage, AgentQuestion, AgentRun, AgentSession
from app.persistence.scope import LOCAL_SCOPE
from tests.test_runtime import (
    FailingAgentEventStream,
    FakeAgentModel,
    FinalAgentModel,
    MixedToolAgentModel,
)


def post(client, path, payload=None, key=None):
    return client.post(
        "/api/v1/agent" + path, json=payload or {}, headers={"Idempotency-Key": key or str(uuid4())}
    )


def start(client, content="hello", key=None):
    response = post(client, "/sessions", {"content": content}, key)
    assert response.status_code == 200, response.text
    return response.json()


def wait_run(client, session_id, status="completed"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/agent/sessions/{session_id}")
        assert response.status_code == 200, response.text
        detail = response.json()
        run = detail["active_run"] or next(
            (m["run"] for m in reversed(detail["messages"]) if m["run"]), None
        )
        if run and run["status"] == status:
            return detail
        time.sleep(0.015)
    pytest.fail(f"Run did not reach {status}: {detail}")


def test_atomic_idempotency_snapshot_and_redis_failure(client_factory):
    with client_factory(stream=FailingAgentEventStream()) as client:
        key = str(uuid4())
        created = start(client, key=key)
        session_id = created["session"]["id"]
        assert start(client, key=key)["run"]["id"] == created["run"]["id"]
        assert post(client, "/sessions", {"content": "different"}, key).status_code == 409
        detail = wait_run(client, session_id)
        assert len(detail["messages"]) == 2
        response = client.get(
            f"/api/v1/agent/runs/{created['run']['id']}/stream",
            headers={"Last-Event-ID": "999:999999"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: snapshot\n" in response.text
        snapshot = json.loads(
            next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        )
        assert snapshot["replace"] is True
        assert snapshot["run"]["status"] == "completed"
        assert snapshot["draft_markdown"] == "已完成。"
        with client.app.state.database.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(AgentSession)) == 1


@pytest.mark.parametrize(
    "answer",
    [
        {"action": "answer", "option_id": "option-1"},
        {"action": "answer", "content": "my answer"},
        {"action": "cancel"},
    ],
)
def test_question_survives_restart_and_resumes_original_run(client_factory, answer):
    with client_factory(FakeAgentModel()) as client:
        created = start(client)
        session_id, run_id = created["session"]["id"], created["run"]["id"]
        detail = wait_run(client, session_id, "waiting_for_user")
        with client.app.state.database.session_factory() as db:
            question_id = db.scalar(select(AgentQuestion.id))
            run = db.get(AgentRun, run_id)
            assert run.lease_owner is None
            assert (
                run.checkpoint["provider_messages"][-1]["tool_calls"][0]["id"] == "call-question-1"
            )
        assert detail["active_run"]["id"] == run_id
    model = FakeAgentModel()
    with client_factory(model) as client:
        wait_run(client, session_id, "waiting_for_user")
        key = str(uuid4())
        response = post(client, f"/questions/{question_id}/respond", answer, key)
        assert response.status_code == 200, response.text
        assert post(client, f"/questions/{question_id}/respond", answer, key).status_code == 200
        detail = wait_run(client, session_id)
        assert detail["messages"][-1]["run"]["id"] == run_id
        assert detail["messages"][-1]["run"]["stream_epoch"] == 2
        assert (
            len(
                [p for p in detail["messages"][-1]["content_parts"] if p["kind"] == "user_question"]
            )
            == 1
        )
        assert model.requests[0][-1]["tool_call_id"] == "call-question-1"
        assert (
            post(
                client,
                f"/questions/{question_id}/respond",
                {"action": "answer", "content": "different"},
            ).status_code
            == 409
        )


def test_expired_lease_recovers_safe_boundary_and_fences_old_worker(client_factory, settings):
    database = Database(settings)
    with database.session_factory() as db:
        repo = AgentRepository(db)
        session, run = repo.create_session_run(
            LOCAL_SCOPE, content="restart", idempotency_key=str(uuid4())
        )
        claimed = repo.claim_run(run.id, "dead-worker")
        fence = claimed[1]
        row = db.get(AgentRun, run.id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=60)
        db.commit()
    with client_factory() as client:
        detail = wait_run(client, session.id)
        assert detail["messages"][-1]["run"]["stream_epoch"] == 2
        with client.app.state.database.session_factory() as db:
            row = db.get(AgentRun, run.id)
            assert row.attempt == 2
            assert row.lease_fence > fence
            assert not AgentRepository(db).renew_lease(run.id, "dead-worker", fence)
            with pytest.raises(DomainError):
                AgentRepository(db).complete_run(
                    run.id, "dead-worker", fence, provider_messages=[], usage={}
                )
    database.close()


def test_message_versions_edit_search_and_delete_cascade(client_factory):
    with client_factory() as client:
        created = start(client, "version history")
        session_id = created["session"]["id"]
        detail = wait_run(client, session_id)
        first_user, first_assistant = detail["messages"]
        assert post(client, f"/messages/{first_assistant['id']}/regenerate").status_code == 200
        detail = wait_run(client, session_id)
        new_assistant = detail["messages"][-1]
        assert new_assistant["id"] != first_assistant["id"]
        assert new_assistant["version_count"] == 2
        switched = post(
            client, f"/sessions/{session_id}/active-version", {"message_id": first_assistant["id"]}
        )
        assert switched.status_code == 200
        assert switched.json()["active_leaf_message_id"] == first_assistant["id"]
        edited = post(client, f"/messages/{first_user['id']}/edit", {"content": "edited"})
        assert edited.status_code == 200, edited.text
        detail = wait_run(client, session_id)
        assert detail["messages"][-2]["markdown"] == "edited"
        listing = client.get("/api/v1/agent/sessions?query=version").json()
        assert len(listing["data"]) == 1
        assert client.delete(f"/api/v1/agent/sessions/{session_id}").status_code == 200
        with client.app.state.database.session_factory() as db:
            for model in [AgentSession, AgentRun, AgentMessage, AgentQuestion]:
                assert db.scalar(select(func.count()).select_from(model)) == 0


def test_cancel_is_idempotent_and_stops_local_execution(client_factory):
    class SlowModel:
        async def stream(self, _messages):
            yield ModelStreamEvent(kind="content", content="partial")
            await asyncio.sleep(60)

    with client_factory(SlowModel()) as client:
        created = start(client)
        session_id, run_id = created["session"]["id"], created["run"]["id"]
        wait_run(client, session_id, "running")
        assert client.delete(f"/api/v1/agent/sessions/{session_id}").status_code == 409
        key = str(uuid4())
        assert post(client, f"/runs/{run_id}/cancel", key=key).status_code == 200
        assert post(client, f"/runs/{run_id}/cancel", key=key).status_code == 200
        detail = wait_run(client, session_id, "cancelled")
        assert detail["messages"][-1]["run"]["status"] == "cancelled"


def test_exact_tool_catalog_and_no_auth_routes(client_factory):
    with client_factory(FinalAgentModel()) as client:
        assert set(client.app.state.agent_runtime.tool_catalog.names()) == {
            "ask_user",
            "read_file",
            "mock_web_search",
            "spawn_subagents",
            "list_subagents",
            "collect_subagent_results",
            "wait_subagents",
            "delegate_tasks",
        }
        assert client.get("/api/v1/auth/me").status_code == 404
        assert client.get("/api/v1/agent/status").status_code == 200
        assert client.post("/api/v1/agent/sessions", json={"content": "hello"}).status_code == 400
        assert (
            client.post(
                "/api/v1/agent/sessions",
                json={"content": "hello"},
                headers={"Origin": "https://elsewhere.invalid"},
            ).status_code
            == 403
        )


def test_mixed_exclusive_tool_batch_gets_one_safe_model_correction(client_factory):
    model = MixedToolAgentModel()
    with client_factory(model) as client:
        created = start(client, "测试工具")
        detail = wait_run(client, created["session"]["id"])

    answer = detail["messages"][-1]
    assert answer["markdown"] == "已按独占规则调整。"
    assert answer["run"]["status"] == "completed"
    assert len(model.requests) == 2
    correction_messages = [
        message for message in model.requests[1] if message.get("role") == "tool"
    ]
    assert len(correction_messages) == 2
    assert all(
        json.loads(message["content"])["error"]["type"] == "ExclusiveToolBatch"
        for message in correction_messages
    )
    assert all(
        part["metadata"].get("status") == "failed"
        for part in answer["content_parts"]
        if part["kind"] == "tool_call"
    )
