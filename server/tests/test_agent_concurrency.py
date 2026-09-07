import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.persistence.agent_runtime import AgentRepository
from app.persistence.agent_schemas import AgentQuestionResponse
from app.persistence.errors import DomainError
from app.persistence.models import AgentQuestion, AgentRun
from app.persistence.scope import LOCAL_SCOPE
from tests.test_lifecycle import start, wait_run
from tests.test_runtime import FakeAgentModel


def test_database_wait_does_not_block_other_http_requests(client_factory, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = AgentRepository.replay_session_run

    def slow_read(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentRepository, "replay_session_run", slow_read)
    with client_factory() as client, ThreadPoolExecutor() as executor:
        pending = executor.submit(start, client)
        try:
            assert entered.wait(2)
            health = executor.submit(client.get, "/healthz")
            assert health.result(timeout=1).status_code == 200
        finally:
            release.set()
        assert pending.result(timeout=3)["run"]


def test_source_resolver_runs_off_event_loop(client_factory):
    with client_factory() as client:
        loop_thread = client.portal.call(threading.get_ident)
        resolver_threads = []

        def resolver(*_args):
            resolver_threads.append(threading.get_ident())
            return {"record": "snapshot"}

        client.app.state.agent_runtime.source_context_registry.register("record", resolver)
        response = client.post(
            "/api/v1/agent/sessions",
            json={"content": "hi", "context": {"source_type": "record", "source_id": "1"}},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        assert resolver_threads and resolver_threads[0] != loop_thread

        async def async_resolver(*_args):
            await asyncio.sleep(0)
            return {"async": True}

        registry = client.app.state.agent_runtime.source_context_registry
        registry.register("async", async_resolver)
        resolved = client.portal.call(
            registry.verify, LOCAL_SCOPE, {"source_type": "async", "source_id": "1"}
        )
        assert resolved["verified_payload"] == {"async": True}


def test_question_response_refreshes_cached_state_after_cancellation(client_factory):
    with client_factory(FakeAgentModel()) as client:
        created = start(client)
        run_id = created["run"]["id"]
        wait_run(client, created["session"]["id"], "waiting_for_user")
        factory = client.app.state.database.session_factory
        with factory() as stale:
            question = stale.scalar(select(AgentQuestion).where(AgentQuestion.run_id == run_id))
            run = stale.get(AgentRun, run_id)
            # expire_on_commit=False retains both loaded objects, as a caller's
            # preflight can. Release the transaction before concurrent mutation.
            stale.commit()
            with factory() as other:
                AgentRepository(other).cancel_run(LOCAL_SCOPE, run_id, str(uuid4()))
            assert question.status == "pending"
            assert run.status == "waiting_for_user"
            with pytest.raises(DomainError) as rejected:
                AgentRepository(stale).respond_question(
                    LOCAL_SCOPE,
                    question.id,
                    AgentQuestionResponse(action="answer", content="late answer"),
                    str(uuid4()),
                )
            assert rejected.value.code == "agent_question_already_resolved"
            assert run.status == "cancelled"
            assert question.status == "cancelled"


@pytest.mark.parametrize("first", ["answer", "cancel"])
def test_postgres_answer_and_cancel_serialize_without_deadlock(client_factory, first):
    with client_factory(FakeAgentModel()) as client:
        database = client.app.state.database
        if database.engine.dialect.name != "postgresql":
            pytest.skip("PostgreSQL row locks required")
        created = start(client)
        run_id = created["run"]["id"]
        wait_run(client, created["session"]["id"], "waiting_for_user")
        with database.session_factory() as db:
            question_id = db.scalar(select(AgentQuestion.id).where(AgentQuestion.run_id == run_id))
        with database.session_factory() as locked, ThreadPoolExecutor() as executor:
            locked.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
            started = threading.Event()

            def operate(db, action):
                repo = AgentRepository(db)
                if action == "cancel":
                    return repo.cancel_run(LOCAL_SCOPE, run_id, str(uuid4()))
                return repo.respond_question(
                    LOCAL_SCOPE,
                    question_id,
                    AgentQuestionResponse(action="answer", content="answer"),
                    str(uuid4()),
                )

            def contender():
                with database.session_factory() as db:
                    started.set()
                    try:
                        operate(db, "cancel" if first == "answer" else "answer")
                    except DomainError as exc:
                        assert first == "cancel" and exc.code == "agent_question_already_resolved"

            future = executor.submit(contender)
            assert started.wait(1)
            try:
                operate(locked, first)
            finally:
                locked.rollback()
            future.result(timeout=3)
        with database.session_factory() as db:
            assert db.get(AgentRun, run_id).status == "cancelled"
