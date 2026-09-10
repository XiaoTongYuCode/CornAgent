"""Site-wide usage aggregation, and nonblocking optional collection."""

import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.api.deps import get_scope
from app.persistence.models import AgentMessage, AgentRun, AgentSession, UsageEvent
from app.persistence.scope import LOCAL_SCOPE, Identity
from app.telemetry import Collector, MetricEvent, bind, completion, tool_call


@pytest.fixture
def anyio_backend():
    return "asyncio"


def seed(db, identity=LOCAL_SCOPE, *, ago=0, status="completed", tokens=None):
    now = datetime.now(UTC) - timedelta(days=ago, minutes=2)
    owner = dict(tenant_id=identity.tenant_id, owner_membership_id=identity.membership_id)
    session = AgentSession(id=str(uuid4()), **owner)
    db.add(session)
    db.flush()
    messages = [
        AgentMessage(
            id=str(uuid4()),
            session_id=session.id,
            role=role,
            version_group_id=str(uuid4()),
            **owner,
        )
        for role in ("user", "assistant")
    ]
    db.add_all(messages)
    db.flush()
    run = AgentRun(
        id=str(uuid4()),
        session_id=session.id,
        user_message_id=messages[0].id,
        assistant_message_id=messages[1].id,
        kind="create",
        status=status,
        created_at=now,
        started_at=now,
        completed_at=now + timedelta(seconds=12) if status == "completed" else None,
        provider_usage=tokens or {},
        **owner,
    )
    db.add(run)
    db.commit()
    return run


def test_usage_site_wide_range_zero_fill_and_missing_usage(client_factory):
    with client_factory() as client:
        with client.app.state.database.session_factory() as db:
            seed(db, tokens={"prompt_tokens": 100, "completion_tokens": 20})
            seed(db, status="failed")
            seed(db, ago=45)
            seed(db, Identity(membership_id="another-owner"), tokens={"prompt_tokens": 99999})
            seed(db, Identity(tenant_id="another-tenant"), tokens={"prompt_tokens": 99999})
        data = client.get("/api/v1/agent/usage?days=7").json()
        assert data["totalRuns"] == 4
        assert data["inputTokens"] == 200098
        assert data["reportedRuns"] == 3
        assert data["successRate"] == 75
        assert data["averageDurationSeconds"] == 12
        assert len(data["daily"]) == 7
        assert sum(day["runs"] for day in data["daily"]) == 4
        assert sum(map(sum, data["hours"])) == 4
        assert not data["telemetryEnabled"]
        assert client.get("/api/v1/agent/usage?days=90").json()["totalRuns"] == 5
        assert client.get("/api/v1/agent/usage?days=365").status_code == 422
        client.app.dependency_overrides[get_scope] = lambda: Identity(membership_id="empty")
        other = client.get("/api/v1/agent/usage?days=7").json()
        assert {k: v for k, v in other.items() if k != "to"} == {
            k: v for k, v in data.items() if k != "to"
        }
        assert client.get("/api/v1/agent/sessions").json()["data"] == []


def test_usage_empty(client_factory):
    with client_factory() as client:
        empty = client.get("/api/v1/agent/usage").json()
        assert empty["totalRuns"] == 0 and empty["successRate"] is None
        assert empty["averageDurationSeconds"] is None


def test_metrics_site_wide_retention_and_session_delete(client_factory, settings):
    settings.telemetry_enabled = True
    with client_factory() as client:
        with client.app.state.database.session_factory() as db:
            run = seed(db)
        collector = client.app.state.telemetry
        event = MetricEvent(
            run.tenant_id,
            run.owner_membership_id,
            run.session_id,
            run.id,
            "model",
            "test-model",
            "child",
            "completed",
            2,
            10,
            5,
        )
        with client.app.state.database.session_factory() as db:
            old = asdict(event)
            old.update(id=str(uuid4()), created_at=datetime.now(UTC) - timedelta(days=200))
            db.add(UsageEvent(**old))
            db.commit()
        collector.emit(event)
        collector.events.join()
        with client.app.state.database.session_factory() as db:
            assert db.get(UsageEvent, old["id"]) is None
        data = client.get("/api/v1/agent/usage").json()
        assert data["models"][0]["childCalls"] == 1
        assert data["models"][0]["inputTokens"] == 10
        client.app.dependency_overrides[get_scope] = lambda: Identity(membership_id="empty")
        assert client.get("/api/v1/agent/usage").json()["models"] == data["models"]
        with client.app.state.database.session_factory() as db:
            db.execute(delete(AgentSession).where(AgentSession.id == run.session_id))
            db.commit()
            assert list(db.scalars(select(UsageEvent))) == []


def test_events_aggregate_across_tenants_and_owners(client_factory, settings):
    settings.telemetry_enabled = True
    with client_factory() as client:
        with client.app.state.database.session_factory() as db:
            for identity in (
                LOCAL_SCOPE,
                Identity(membership_id="another-owner"),
                Identity(tenant_id="another-tenant"),
            ):
                run = seed(db, identity)
                for kind in ("model", "tool"):
                    db.add(UsageEvent(**asdict(MetricEvent(
                        run.tenant_id, run.owner_membership_id, run.session_id, run.id,
                        kind, "test-" + kind, "root", "completed", 2, 10, 5,
                    ))))
                db.commit()
        data = client.get("/api/v1/agent/usage").json()
        for key in ("models", "tools"):
            assert data[key][0]["calls"] == 3
            assert data[key][0]["inputTokens"] == 30
            assert data[key][0]["outputTokens"] == 15
        serialized = str(data)
        for private_field in ("tenant_id", "owner_membership_id", "session_id", "run_id"):
            assert private_field not in serialized


@pytest.mark.anyio
async def test_model_tool_events_allowlist_and_no_context_leak():
    events = []
    recorder = SimpleNamespace(emit=events.append)
    context = SimpleNamespace(
        tenant_id="t", owner_membership_id="u", session_id="s", run_id="r", execution_scope="child"
    )

    async def provider(**kwargs):
        async def chunks():
            yield {"usage": {"prompt_tokens": 12, "completion_tokens": 3}, "secret": "not recorded"}

        return chunks()

    async def tool():
        return {"ok": False, "error": {"message": "private"}}

    with bind(recorder, context):
        stream = await completion(
            provider, model="actual-model", stream=True, messages=[{"content": "secret"}]
        )
        assert len([chunk async for chunk in stream]) == 1
        assert await tool_call("example", tool) == await tool()
    await tool_call("outside", tool)
    assert len(events) == 2
    assert events[0].name == "actual-model" and events[0].input_tokens == 12
    assert events[1].status == "failed"
    assert "secret" not in str([asdict(e) for e in events])
    assert "private" not in str([asdict(e) for e in events])


@pytest.mark.anyio
async def test_broken_sink_or_usage_cannot_break_model_or_tool():
    def fail(_):
        raise RuntimeError("bad metrics plugin")

    recorder = SimpleNamespace(emit=fail)
    context = SimpleNamespace(
        tenant_id="t", owner_membership_id="u", session_id="s", run_id="r", execution_scope="root"
    )

    async def ok(**kwargs):
        return {"usage": {"prompt_tokens": float("nan")}, "result": "ok"}

    with bind(recorder, context):
        assert (await completion(ok, model="test"))["result"] == "ok"
        assert (await tool_call("test", ok))["result"] == "ok"


def test_collector_is_bounded_nonblocking_and_failure_safe():
    gate = threading.Event()
    entered = threading.Event()

    class SlowSink:
        def write(self, event):
            entered.set()
            gate.wait(2)
            raise RuntimeError("offline")

    collector = Collector(SlowSink(), capacity=1)
    event = MetricEvent("t", "u", "s", "r", "tool", "test", "root", "completed", 1)
    collector.emit(event)
    assert entered.wait(1)
    started = time.monotonic()
    for _ in range(20):
        collector.emit(event)
    assert time.monotonic() - started < 0.1
    assert collector.dropped >= 19
    gate.set()
    collector.close()
    assert collector.failed == 2


def test_real_runtime_emits_model_and_tool_metrics(client_factory, settings, monkeypatch):
    from app.agent.model import LiteLLMAgentModel
    from tests.test_lifecycle import start, wait_run

    settings.telemetry_enabled = True

    async def provider(**kwargs):
        has_tool = any(m.get("role") == "tool" for m in kwargs["messages"])

        async def chunks():
            if has_tool:
                yield {
                    "choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                }
            else:
                yield {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "search-1",
                                        "function": {
                                            "name": "mock_web_search",
                                            "arguments": '{"query":"test"}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 3},
                }

        return chunks()

    monkeypatch.setattr("app.agent.model.litellm.acompletion", provider)
    model = LiteLLMAgentModel(model="openai/test", api_key="test", max_retries=0)
    with client_factory(model=model) as client:
        created = start(client)
        wait_run(client, created["session"]["id"])
        client.app.state.telemetry.events.join()
        data = client.get("/api/v1/agent/usage").json()
        assert data["models"][0]["calls"] == 2
        assert data["models"][0]["inputTokens"] == 18
        assert data["tools"][0]["name"] == "mock_web_search"
        assert data["tools"][0]["calls"] == 1
        assert data["totalRuns"] == 1


def test_telemetry_enabled_by_default():
    from app.settings import Settings

    assert Settings(_env_file=None).telemetry_enabled is True
