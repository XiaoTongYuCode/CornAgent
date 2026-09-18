"""Queue persistence, safe steering boundaries, idempotency and session isolation."""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.agent.model import ModelStreamEvent
from app.database import Database
from app.persistence import inputs
from app.persistence.agent_runtime import AgentRepository
from app.persistence.agent_schemas import AgentInputChange, AgentInputCreate
from app.persistence.errors import DomainError
from app.persistence.models import AgentInput, AgentMessage, AgentRun, AgentSession
from app.persistence.scope import LOCAL_SCOPE, Identity
from tests.test_lifecycle import post, start, wait_run
from tests.test_runtime import FakeAgentModel


def test_steering_session_lock_allows_telemetry_foreign_key_lock(settings):
    """Completion must not wait on a metric insert that is waiting on its Run."""
    from tests.test_usage import seed

    database = Database(settings)
    try:
        if database.engine.dialect.name != "postgresql":
            pytest.skip("PostgreSQL row-lock compatibility")
        with database.session_factory() as db:
            run = seed(db)
            run_id, session_id = run.id, run.session_id
        with database.session_factory() as metric, database.session_factory() as worker:
            metric.scalar(
                select(AgentSession)
                .where(AgentSession.id == session_id)
                .with_for_update(read=True, key_share=True)
            )
            worker.execute(text("SET LOCAL lock_timeout = '500ms'"))
            run = worker.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            assert inputs.consume(AgentRepository(worker), run, []) is None
    finally:
        database.close()


class GatedModel:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.requests = []

    async def stream(self, messages):
        self.requests.append(messages)
        if len(self.requests) == 1:
            self.started.set()
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        yield ModelStreamEvent(kind="content", content=f"answer-{len(self.requests)}")


def test_queue_and_steer_at_final_boundary(client_factory):
    model = GatedModel()
    with client_factory(model) as client:
        created = start(client)
        sid = created["session"]["id"]
        rid = created["run"]["id"]
        assert model.started.wait(2)
        key = str(uuid4())
        body = {"content": "second task", "mode": "queue"}
        queued = post(client, f"/sessions/{sid}/inputs", body, key)
        assert queued.status_code == 200, queued.text
        assert (
            post(client, f"/sessions/{sid}/inputs", body, key).json()["id"] == queued.json()["id"]
        )
        steer = post(client, f"/sessions/{sid}/inputs", {"content": "use Chinese", "mode": "steer"})
        assert steer.status_code == 200, steer.text
        assert len(model.requests) == 1
        detail = client.get(f"/api/v1/agent/sessions/{sid}").json()
        assert len(detail["inputs"]) == 2
        model.release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            detail = client.get(f"/api/v1/agent/sessions/{sid}").json()
            if not detail["inputs"] and not detail["active_run"]:
                break
            time.sleep(0.02)
        assert not detail["inputs"] and not detail["active_run"]
        assert len(model.requests) == 3
        assert model.requests[1][-1] == {"role": "user", "content": "use Chinese"}
        assert model.requests[2][-1] == {"role": "user", "content": "second task"}
        with client.app.state.database.session_factory() as db:
            rows = list(db.scalars(select(AgentInput).order_by(AgentInput.created_at)))
            assert [r.status for r in rows] == ["applied", "applied"]
            assert rows[1].run_id == rid and rows[0].run_id != rid
            assistant = db.get(AgentMessage, created["run"]["assistant_message_id"])
            assert assistant.parent_message_id == rows[1].message_id
            original = db.get(AgentRun, rid)
            assert json.dumps(original.checkpoint).count("use Chinese") == 2  # current + safe
        replay = post(client, f"/inputs/{steer.json()['id']}", {"version": 1, "cancel": True})
        assert replay.status_code == 409


def test_queue_change_idempotency_ownership_and_recovery(settings):
    database = Database(settings)
    with database.session_factory() as db:
        repo = AgentRepository(db)
        session, run = repo.create_session_run(LOCAL_SCOPE, content="first", idempotency_key="seed")
        first = inputs.create(repo, LOCAL_SCOPE, session.id, AgentInputCreate(content="one"), "one")
        with pytest.raises(DomainError) as exc:
            inputs.change(
                repo,
                Identity("foreign", "foreign", "foreign"),
                first["id"],
                AgentInputChange(version=1, cancel=True),
                "bad",
            )
        assert exc.value.status_code == 404
        db.rollback()
        changed = inputs.change(
            repo, LOCAL_SCOPE, first["id"], AgentInputChange(version=1, content="edited"), "edit"
        )
        assert changed["version"] == 2
        assert (
            inputs.change(
                repo,
                LOCAL_SCOPE,
                first["id"],
                AgentInputChange(version=1, content="edited"),
                "edit",
            )
            == changed
        )
        with pytest.raises(DomainError):
            inputs.change(
                repo, LOCAL_SCOPE, first["id"], AgentInputChange(version=1, cancel=True), "stale"
            )
        db.rollback()
        repo.cancel_run(LOCAL_SCOPE, run.id, "stop")
    # Fresh repository after a process restart dispatches exactly once.
    with database.session_factory() as db:
        repo = AgentRepository(db)
        dispatched = inputs.dispatch(repo)
        assert len(dispatched) == 1
        assert inputs.dispatch(repo) == []
        row = db.get(AgentInput, first["id"])
        assert row.status == "applied"
        assert db.get(AgentMessage, row.message_id).markdown == "edited"
    database.close()


def test_session_read_serializes_queue_handoff(settings):
    database = Database(settings)
    if database.engine.dialect.name != "postgresql":
        database.close()
        pytest.skip("PostgreSQL row locks required")
    try:
        with database.session_factory() as db:
            repo = AgentRepository(db)
            session, run = repo.create_session_run(
                LOCAL_SCOPE, content="first", idempotency_key="seed"
            )
            inputs.create(repo, LOCAL_SCOPE, session.id, AgentInputCreate(content="next"), "next")
            repo.cancel_run(LOCAL_SCOPE, run.id, "stop")

        def dispatch():
            with database.session_factory() as db:
                return inputs.dispatch(AgentRepository(db))

        with database.session_factory() as reader, ThreadPoolExecutor() as executor:
            detail = AgentRepository(reader).session_detail(LOCAL_SCOPE, session.id)
            assert detail.active_run is None and len(detail.inputs) == 1
            # Dispatch must not drain inputs between the reader's separate SELECTs.
            assert executor.submit(dispatch).result(timeout=3) == []
        assert len(dispatch()) == 1
        with database.session_factory() as reader:
            detail = AgentRepository(reader).session_detail(LOCAL_SCOPE, session.id)
            assert detail.active_run is not None and not detail.inputs
    finally:
        database.close()


def test_steering_cancels_question_and_resumes_same_run(client_factory):
    class SteeringQuestionModel(FakeAgentModel):
        async def stream(self, messages):
            if any(m.get("role") == "tool" for m in messages):
                yield ModelStreamEvent(kind="content", content="Continued with steering.")
                return
            async for event in super().stream(messages):
                yield event

    model = SteeringQuestionModel()
    with client_factory(model) as client:
        created = start(client)
        sid = created["session"]["id"]
        wait_run(client, sid, "waiting_for_user")
        result = post(
            client,
            f"/sessions/{sid}/inputs",
            {"content": "continue with defaults", "mode": "steer"},
        )
        assert result.status_code == 200, result.text
        detail = wait_run(client, sid)
        assert any(m["markdown"] == "continue with defaults" for m in detail["messages"])
        with client.app.state.database.session_factory() as db:
            item = db.get(AgentInput, result.json()["id"])
            assert item.run_id == created["run"]["id"]


def test_queued_attachment_reserved_and_cancelled_item_never_runs(client_factory):
    from tests.test_files import upload

    model = GatedModel()
    with client_factory(model) as client:
        created = start(client)
        sid = created["session"]["id"]
        assert model.started.wait(2)
        fid = upload(client, b"queued attachment evidence", "text/plain", "queued.txt")
        assert client.post(f"/api/v1/files/{fid}/extract").status_code == 200
        queued = post(client, f"/sessions/{sid}/inputs", {"attachments": [{"file_id": fid}]}).json()
        assert client.delete(f"/api/v1/files/{fid}").status_code == 409
        assert client.get(f"/api/v1/agent/sessions/{sid}").json()["inputs"][0]["file_ids"] == [fid]
        removed = post(
            client, f"/inputs/{queued['id']}", {"version": 1, "cancel": True}, "cancel-file"
        )
        assert removed.status_code == 200
        assert (
            post(
                client, f"/inputs/{queued['id']}", {"version": 1, "cancel": True}, "cancel-file"
            ).json()
            == removed.json()
        )
        model.release.set()
        wait_run(client, sid)
        assert len(model.requests) == 1
        assert client.delete(f"/api/v1/agent/sessions/{sid}").status_code == 200
        assert client.get(f"/api/v1/files/{fid}/content").status_code == 404
