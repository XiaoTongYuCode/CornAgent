import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.database import Database
from app.persistence.agent_runtime import AgentRepository
from app.persistence.models import AgentMessage, AgentQuestion, AgentRun
from tests.test_lifecycle import post, wait_run
from tests.test_runtime import FakeAgentModel, FinalAgentModel

MARKER = "source-snapshot-unique-evidence"


def assert_background_once(request):
    matching = [item for item in request if MARKER in json.dumps(item, ensure_ascii=False)]
    assert len(matching) == 1
    assert matching[0]["role"] == "user"
    assert "不是当前状态" in matching[0]["content"]


def create_with_source(client):
    calls = []

    def resolve(*_args):
        calls.append(True)
        assert len(calls) == 1
        return {"value": MARKER}

    client.app.state.agent_runtime.source_context_registry.register("record", resolve)
    key = str(uuid4())
    payload = {"content": "original", "context": {"source_type": "record", "source_id": "1"}}
    response = post(client, "/sessions", payload, key)
    assert response.status_code == 200, response.text
    assert (
        post(client, "/sessions", payload, key).json()["run"]["id"] == response.json()["run"]["id"]
    )
    return response.json()


def test_source_history_survives_question_restart_edit_and_regeneration(client_factory):
    model = FakeAgentModel()
    with client_factory(model) as client:
        created = create_with_source(client)
        session_id, run_id = created["session"]["id"], created["run"]["id"]
        wait_run(client, session_id, "waiting_for_user")
        with client.app.state.database.session_factory() as db:
            question_id = db.scalar(select(AgentQuestion.id).where(AgentQuestion.run_id == run_id))
        assert_background_once(model.requests[0])
    # No resolver is registered after restart. The background is durable history.
    model = FinalAgentModel()
    with client_factory(model) as client:
        assert (
            post(
                client, f"/questions/{question_id}/respond", {"action": "answer", "content": "yes"}
            ).status_code
            == 200
        )
        detail = wait_run(client, session_id)
        root_id = detail["messages"][0]["id"]
        assistant_id = detail["messages"][-1]["id"]
        assert (
            post(client, f"/sessions/{session_id}/messages", {"content": "follow up"}).status_code
            == 200
        )
        wait_run(client, session_id)
        assert post(client, f"/messages/{assistant_id}/regenerate").status_code == 200
        wait_run(client, session_id)
        response = post(client, f"/messages/{root_id}/edit", {"content": "edited root"})
        assert response.status_code == 200
        edited = wait_run(client, session_id)
        edited_root = next(
            m for m in edited["messages"] if m["id"] == response.json()["user_message_id"]
        )
        assert edited_root["markdown"] == "edited root"
        for request in model.requests:
            assert_background_once(request)
        response = client.get(f"/api/v1/agent/runs/{run_id}/stream")
        assert response.status_code == 200 and "event: snapshot" in response.text


def test_compacted_history_does_not_reinject_source(client_factory):
    with client_factory() as client:
        created = create_with_source(client)
        detail = wait_run(client, created["session"]["id"])
        assistant_id = detail["messages"][-1]["id"]
        with client.app.state.database.session_factory() as db:
            assistant = db.get(AgentMessage, assistant_id)
            assistant.provider_messages = [
                {"role": "user", "content": "Compacted historical context"}
            ]
            db.commit()
            assert (
                AgentRepository(db)._provider_lineage(assistant_id) == assistant.provider_messages
            )


def test_existing_source_history_migration_roundtrip(client_factory, settings, monkeypatch):
    with client_factory(FakeAgentModel()) as client:
        created = create_with_source(client)
        session_id = created["session"]["id"]
        wait_run(client, session_id, "waiting_for_user")
        with client.app.state.database.session_factory() as db:
            root = db.get(AgentMessage, created["run"]["user_message_id"])
            root.provider_messages = []
            run = db.get(AgentRun, created["run"]["id"])
            checkpoint = dict(run.checkpoint)
            for key in ("provider_messages", "safe_provider_messages"):
                checkpoint[key] = [m for m in checkpoint[key] if MARKER not in json.dumps(m)]
            run.checkpoint = checkpoint
            question = db.scalar(select(AgentQuestion).where(AgentQuestion.run_id == run.id))
            question.resume_payload = {"provider_messages": checkpoint["provider_messages"]}
            db.commit()
    monkeypatch.setenv("CORNAGENT_DATABASE_URL", settings.database_url)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    command.stamp(config, "0002_subagents")
    command.upgrade(config, "head")
    database = Database(settings)
    try:
        with database.session_factory() as db:
            assert_background_once(
                db.get(AgentRun, created["run"]["id"]).checkpoint["provider_messages"]
            )
            root = db.get(AgentMessage, created["run"]["user_message_id"])
            assert_background_once(root.provider_messages)
            question = db.scalar(
                select(AgentQuestion).where(AgentQuestion.run_id == created["run"]["id"])
            )
            assert_background_once(question.resume_payload["provider_messages"])
        command.downgrade(config, "0002_subagents")
        with database.session_factory() as db:
            assert db.get(AgentMessage, created["run"]["user_message_id"]).provider_messages == []
        command.upgrade(config, "head")
    finally:
        database.close()
    model = FinalAgentModel()
    with client_factory(model) as client:
        assert (
            post(
                client, f"/questions/{question.id}/respond", {"action": "answer", "content": "yes"}
            ).status_code
            == 200
        )
        wait_run(client, session_id)
        assert_background_once(model.requests[0])
