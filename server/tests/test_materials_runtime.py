"""Full runtime receipt delivery, durable history and private rehydration."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.agent.model import ModelStreamEvent
from app.agent.tools import ToolDefinition, ToolExecutionContext
from app.database import Database
from app.main import create_app
from app.persistence import agent_runtime
from app.persistence.agent_runtime import AgentRepository
from app.persistence.errors import DomainError
from app.persistence.materials import MaterialRepository
from app.persistence.models import AgentRun, AgentSession, AgentToolReceipt
from app.persistence.scope import LOCAL_SCOPE
from tests.test_lifecycle import post, start, wait_run
from tests.test_runtime import FakeAgentEventStream, FinalAgentModel

TAIL = "UNIQUE_COMPLETE_RESULT_TAIL_91f0"
LARGE_RESULT = {"ok": True, "content": "prefix readable evidence; " * 1400 + TAIL}


def call(name, arguments, call_id):
    return ModelStreamEvent(
        kind="tool_calls",
        tool_calls=[
            {
                "id": call_id,
                "name": name,
                "arguments": json.dumps(arguments),
            }
        ],
    )


def test_runtime_archives_large_results_and_reads_complete_tail_after_restart(settings):
    settings.agent_context_window_tokens = 128_000
    executions = []

    async def large_tool(arguments, context):
        executions.append(context.tool_call_id)
        return LARGE_RESULT

    tool = ToolDefinition(
        name="read_large_evidence",
        description="Read a large test document.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=large_tool,
        read_only=True,
    )

    class ReaderModel:
        def __init__(self, receipt_id=""):
            self.receipt_id = receipt_id
            self.fragments = []
            self.requests = []
            self.database = None

        async def stream(self, messages):
            self.requests.append(messages)
            assert all("cornagent_receipt" not in item for item in messages)
            latest = messages[-1]
            if latest["role"] != "tool":
                if self.receipt_id:
                    yield call("read_tool_result", {"receipt_id": self.receipt_id}, "read-0")
                else:
                    yield call("read_large_evidence", {}, "large-1")
                return
            result = json.loads(latest["content"])
            if latest["name"] == "read_large_evidence":
                assert result["type"] == "cornagent_material_ref"
                assert TAIL not in latest["content"]
                self.receipt_id = result["receipt_id"]
                # Provider-visible ref cannot appear before both the full result and
                # safe completion checkpoint are committed in the same transaction.
                with self.database.session_factory() as db:
                    receipt = db.get(AgentToolReceipt, self.receipt_id)
                    assert json.loads(receipt.result_json) == LARGE_RESULT
                    run = db.get(AgentRun, receipt.run_id)
                    assert run.checkpoint["ordinary_tool_batch"]["phase"] == "completed"
                    assert self.receipt_id in json.dumps(run.checkpoint["safe_provider_messages"])
                yield call("read_tool_result", {"receipt_id": self.receipt_id}, "read-0")
                return
            assert latest["name"] == "read_tool_result" and result["ok"]
            self.fragments.append(result["content"])
            if result["next_cursor"]:
                yield call(
                    "read_tool_result",
                    {
                        "receipt_id": self.receipt_id,
                        "cursor": result["next_cursor"],
                    },
                    f"read-{len(self.fragments)}",
                )
            else:
                assert json.loads("".join(self.fragments)) == LARGE_RESULT
                yield ModelStreamEvent(kind="content", content="All persisted evidence was read.")

    first_model, stream = ReaderModel(), FakeAgentEventStream()
    app = create_app(
        settings, model_client=first_model, event_stream=stream, additional_tools=(tool,)
    )
    first_model.database = app.state.database
    with TestClient(app) as client:
        created = start(client, "Read all evidence")
        sid = created["session"]["id"]
        detail = wait_run(client, sid)
        receipt_id = first_model.receipt_id
        assert detail["messages"][-1]["markdown"] == "All persisted evidence was read."
        assert len(first_model.fragments) >= 3 and executions == ["large-1"]
        with app.state.database.session_factory() as db:
            run = db.get(AgentRun, created["run"]["id"])
            assert TAIL not in json.dumps(run.checkpoint)
            assert TAIL not in json.dumps(run.content_parts)
            assert db.scalar(select(func.count()).select_from(AgentToolReceipt)) == 1
        assert TAIL not in json.dumps(stream.events)
        assert receipt_id in json.dumps(stream.events)
    # A fresh app with no producer tool can still reread the ancestor's full receipt.
    second_model = ReaderModel(receipt_id)
    second = create_app(settings, model_client=second_model, event_stream=FakeAgentEventStream())
    second_model.database = second.state.database
    with TestClient(second) as client:
        response = post(
            client, f"/sessions/{sid}/messages", {"content": "Read the saved result again"}
        )
        assert response.status_code == 200, response.text
        detail = wait_run(client, sid)
        assert detail["messages"][-1]["markdown"] == "All persisted evidence was read."
        assert len(second_model.fragments) >= 3 and executions == ["large-1"]


def test_private_history_hydrates_without_advertised_tool_after_restart(settings):
    secret, executions = "PRIVATE_DERIVED_SOURCE_TEXT", []

    async def private_read(arguments, context):
        executions.append(context.run_id)
        return {"ok": True, "content": secret}

    tool = ToolDefinition(
        name="read_private_evidence",
        description="Read private evidence for this session.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=private_read,
        private_result=True,
        read_only=True,
        result_projector=lambda _: {"ok": True, "content_chars": len(secret)},
    )

    class Model:
        def __init__(self, fresh_run=False):
            self.fresh_run = fresh_run
            self.calls = 0

        async def stream_with_tools(self, messages, *, tools):
            self.calls += 1
            names = {item["function"]["name"] for item in tools}
            if self.fresh_run:
                assert "read_private_evidence" in names
                assert secret in json.dumps(messages)
                yield ModelStreamEvent(kind="content", content="Private source reauthorized.")
            elif self.calls == 1:
                assert "read_private_evidence" not in names
                yield call(
                    "search_tools", {"query": "read_private_evidence", "max_results": 1}, "load-1"
                )
            elif self.calls == 2:
                assert "read_private_evidence" in names
                yield call("read_private_evidence", {}, "private-1")
            else:
                assert secret in json.dumps(messages)
                yield ModelStreamEvent(kind="content", content="Private source read.")

    for fresh_run in (False, True):
        stream = FakeAgentEventStream()
        app = create_app(
            settings, model_client=Model(fresh_run), event_stream=stream, additional_tools=(tool,)
        )
        with TestClient(app) as client:
            if not fresh_run:
                created = start(client, "Read private evidence")
                sid = created["session"]["id"]
            else:
                response = post(client, f"/sessions/{sid}/messages", {"content": "Continue"})
                assert response.status_code == 200, response.text
                current_run_id = response.json()["id"]
            detail = wait_run(client, sid)
            assert secret not in json.dumps(detail)
            assert secret not in json.dumps(stream.events)
            with app.state.database.session_factory() as db:
                assert all(
                    secret not in row.result_json for row in db.scalars(select(AgentToolReceipt))
                )
                assert all(
                    secret not in json.dumps(row.checkpoint) for row in db.scalars(select(AgentRun))
                )
                if fresh_run:
                    row = db.get(AgentRun, current_run_id)
                    private_message = next(
                        item
                        for item in row.checkpoint["safe_provider_messages"]
                        if item.get("name") == "read_private_evidence"
                    )
            if fresh_run:

                async def hydrate_with_restricted_advertisement(
                    runtime, message, session_id, run_id
                ):
                    return await runtime._materialize_private_tool_results(
                        [message],
                        tool_context=ToolExecutionContext(
                            tenant_id=LOCAL_SCOPE.tenant_id,
                            owner_membership_id=LOCAL_SCOPE.membership_id,
                            session_id=session_id,
                            run_id=run_id,
                            advertised_tools=frozenset({"search_tools"}),
                        ),
                    )

                hydrated = client.portal.call(
                    hydrate_with_restricted_advertisement,
                    app.state.agent_runtime,
                    private_message,
                    sid,
                    current_run_id,
                )
                assert secret in json.dumps(hydrated)
    assert len(set(executions)) == 2


def test_receipt_and_safe_checkpoint_rollback_together(settings, monkeypatch):
    database = Database(settings)
    try:
        with database.session_factory() as db:
            repository = AgentRepository(db)
            _, run = repository.create_session_run(
                LOCAL_SCOPE, content="atomic", idempotency_key="atomic"
            )
            _, fence, _ = repository.claim_run(run.id, "worker")
            repository.persist_ordinary_tool_batch(
                run.id,
                "worker",
                fence,
                batch_id="batch",
                phase="executing",
                tool_calls=[],
                parts=[],
                tool_context_state={},
            )

        def reject_completed(checkpoint, **kwargs):
            if checkpoint.get("ordinary_tool_batch", {}).get("phase") == "completed":
                raise DomainError("agent_checkpoint_too_large", "Synthetic rejected checkpoint")

        monkeypatch.setattr(agent_runtime, "ensure_checkpoint_size", reject_completed)
        with (
            database.session_factory() as db,
            pytest.raises(DomainError, match="Synthetic rejected"),
        ):
            AgentRepository(db).persist_ordinary_tool_batch(
                run.id,
                "worker",
                fence,
                batch_id="batch",
                phase="completed",
                tool_calls=[],
                parts=[],
                tool_context_state={},
                provider_messages=[
                    {
                        "role": "tool",
                        "tool_call_id": "call",
                        "name": "large",
                        "content": json.dumps(LARGE_RESULT),
                    }
                ],
                receipts=[
                    {
                        "call_id": "call",
                        "tool_name": "large",
                        "arguments": {},
                        "result": LARGE_RESULT,
                        "read_only": True,
                    }
                ],
            )
        with database.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(AgentToolReceipt)) == 0
            persisted = db.get(AgentRun, run.id)
            assert persisted.checkpoint["ordinary_tool_batch"]["phase"] == "executing"
    finally:
        database.close()


@pytest.mark.parametrize("conflict", [False, True])
def test_repeated_provider_call_reuses_receipt_before_handler(settings, conflict):
    executions = []

    async def handler(arguments, context):
        executions.append(dict(arguments))
        return {"ok": True, "observed_version": len(executions)}

    tool = ToolDefinition(
        name="read_once",
        description="Read a mutable test record.",
        parameters={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        handler=handler,
        read_only=True,
    )

    class Model:
        def __init__(self):
            self.calls = 0

        async def stream(self, messages):
            self.calls += 1
            if self.calls < 3:
                yield call(
                    "read_once",
                    {"id": "changed" if conflict and self.calls == 2 else "same"},
                    "stable-call-id",
                )
            else:
                assert json.loads(messages[-1]["content"])["observed_version"] == 1
                yield ModelStreamEvent(kind="content", content="Reused the committed result.")

    app = create_app(
        settings,
        model_client=Model(),
        event_stream=FakeAgentEventStream(),
        additional_tools=(tool,),
    )
    with TestClient(app) as client:
        created = start(client, "Read evidence twice")
        detail = wait_run(client, created["session"]["id"], "failed" if conflict else "completed")
        if conflict:
            assert detail["messages"][-1]["run"]["error_code"] == "agent_material_call_conflict"
        assert executions == [{"id": "same"}]
        with app.state.database.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(AgentToolReceipt)) == 1


def test_call_id_material_reference_stays_on_original_run_after_restart(settings):
    executions = []

    async def source(arguments, context):
        executions.append((context.run_id, arguments["value"]))
        return {"ok": True, "value": arguments["value"]}

    tool = ToolDefinition(
        name="read_versioned_source",
        description="Read the selected source version.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=source,
        read_only=True,
    )

    class Model:
        def __init__(self, following):
            self.following = following
            self.calls = 0

        async def stream(self, messages):
            self.calls += 1
            reads = {
                item["tool_call_id"]: json.loads(item["content"])
                for item in messages
                if item.get("role") == "tool" and item.get("name") == "read_tool_result"
            }
            if self.following:
                # The old call-ID based read must still be authorized before this
                # Run produces any result, and after it reuses the same provider ID.
                assert reads["read-ancestor"]["ok"]
                assert json.loads(reads["read-ancestor"]["content"])["value"] == "ancestor"
            if self.calls == 1:
                yield call(
                    "read_versioned_source",
                    {
                        "value": "current" if self.following else "ancestor",
                    },
                    "provider-reused-call-id",
                )
            elif self.calls == 2:
                yield call(
                    "read_tool_result",
                    {"call_id": "provider-reused-call-id"},
                    "read-current" if self.following else "read-ancestor",
                )
            else:
                target = reads["read-current" if self.following else "read-ancestor"]
                assert target["ok"]
                assert json.loads(target["content"])["value"] == (
                    "current" if self.following else "ancestor"
                )
                if self.following:
                    assert target["receipt_id"] != reads["read-ancestor"]["receipt_id"]
                yield ModelStreamEvent(kind="content", content="Read the correct version.")

    for following in (False, True):
        app = create_app(
            settings,
            model_client=Model(following),
            event_stream=FakeAgentEventStream(),
            additional_tools=(tool,),
        )
        with TestClient(app) as client:
            if not following:
                created = start(client, "Read by call ID")
                session_id, run_id = created["session"]["id"], created["run"]["id"]
            else:
                response = post(
                    client, f"/sessions/{session_id}/messages", {"content": "Read new version"}
                )
                assert response.status_code == 200, response.text
                run_id = response.json()["id"]
            detail = wait_run(client, session_id)
            assert detail["messages"][-1]["markdown"] == "Read the correct version."
            with app.state.database.session_factory() as db:
                row = db.get(AgentRun, run_id)
                reference = json.loads(
                    next(
                        item["content"]
                        for item in row.checkpoint["safe_provider_messages"]
                        if item.get("name") == "read_tool_result"
                        and item["tool_call_id"] == "read-ancestor"
                    )
                )
                assert reference["arguments"]["receipt_id"]
                assert "call_id" not in reference["arguments"]
    assert [value for _, value in executions] == ["ancestor", "current"]


@pytest.mark.parametrize("tool_name", ["list_materials", "search_materials"])
def test_material_directory_rehydration_keeps_original_run_scope(settings, tool_name):
    ancestor_ids = set()

    async def source(arguments, context):
        return {"ok": True, "content": f"evidence {arguments['version']}"}

    tool = ToolDefinition(
        name="read_directory_source",
        description="Read a directory test source.",
        parameters={
            "type": "object",
            "properties": {"version": {"type": "string"}},
            "required": ["version"],
        },
        handler=source,
        read_only=True,
    )

    class Model:
        def __init__(self, following):
            self.following, self.calls = following, 0

        async def stream(self, messages):
            self.calls += 1
            listings = {
                item["tool_call_id"]: json.loads(item["content"])
                for item in messages
                if item.get("role") == "tool" and item.get("name") == tool_name
            }
            if self.following:
                assert listings["directory-old"]["ok"]
                assert {
                    item["material_id"] for item in listings["directory-old"]["materials"]
                } == ancestor_ids
            if self.calls == 1:
                yield call(
                    "read_directory_source",
                    {"version": "new" if self.following else "old"},
                    "source-call",
                )
            elif self.calls == 2:
                yield call(
                    tool_name,
                    {"query": "evidence"} if tool_name == "search_materials" else {},
                    "directory-current" if self.following else "directory-old",
                )
            else:
                listing = listings["directory-current" if self.following else "directory-old"]
                assert listing["ok"]
                ids = {item["material_id"] for item in listing["materials"]}
                if self.following:
                    assert len(ids) == 2 and ancestor_ids < ids
                else:
                    assert len(ids) == 1
                    ancestor_ids.update(ids)
                yield ModelStreamEvent(kind="content", content="Read the branch directory.")

    for following in (False, True):
        app = create_app(
            settings,
            model_client=Model(following),
            event_stream=FakeAgentEventStream(),
            additional_tools=(tool,),
        )
        with TestClient(app) as client:
            if not following:
                created = start(client, "List evidence")
                sid = created["session"]["id"]
            else:
                response = post(
                    client, f"/sessions/{sid}/messages", {"content": "Add and list evidence"}
                )
                assert response.status_code == 200, response.text
            detail = wait_run(client, sid)
            assert detail["messages"][-1]["markdown"] == "Read the branch directory."


def test_material_source_run_rehydration_rejects_sibling_and_deleted_scope(settings):
    app = create_app(settings, model_client=FinalAgentModel(), event_stream=FakeAgentEventStream())
    with TestClient(app) as client:
        runtime = app.state.agent_runtime
        client.portal.call(runtime.close)
        with app.state.database.session_factory() as db:
            repository = AgentRepository(db)
            session, original = repository.create_session_run(
                LOCAL_SCOPE, content="original", idempotency_key="original"
            )
            MaterialRepository(db).save(
                LOCAL_SCOPE,
                run_id=original.id,
                call_id="same-call",
                tool_name="source",
                arguments={},
                result={"value": "ancestor"},
            )
            db.get(AgentRun, original.id).status = "completed"
            db.commit()
            sibling = repository.regenerate(LOCAL_SCOPE, original.assistant_message_id, "sibling")
            MaterialRepository(db).save(
                LOCAL_SCOPE,
                run_id=sibling.id,
                call_id="same-call",
                tool_name="source",
                arguments={},
                result={"value": "sibling secret"},
            )
            db.get(AgentRun, sibling.id).status = "completed"
            db.get(AgentSession, session.id).active_leaf_message_id = original.assistant_message_id
            db.commit()
            current = repository.create_run(
                LOCAL_SCOPE, session.id, "continue original branch", "current"
            )
            MaterialRepository(db).save(
                LOCAL_SCOPE,
                run_id=current.id,
                call_id="same-call",
                tool_name="source",
                arguments={},
                result={"value": "current secret"},
            )
            db.commit()
        context = ToolExecutionContext(
            tenant_id=LOCAL_SCOPE.tenant_id,
            owner_membership_id=LOCAL_SCOPE.membership_id,
            session_id=session.id,
            run_id=current.id,
        )

        async def hydrate(source_run):
            return await runtime._materialize_private_tool_results(
                [
                    {
                        "role": "tool",
                        "name": "read_tool_result",
                        "tool_call_id": "historical-read",
                        "content": runtime._serialize_private_tool_reference(
                            definition=runtime.tool_catalog.get("read_tool_result"),
                            arguments={"call_id": "same-call"},
                            source_run_id=source_run,
                        ),
                    }
                ],
                tool_context=context,
            )

        valid = client.portal.call(hydrate, original.id)
        assert json.loads(json.loads(valid[0]["content"])["content"])["value"] == "ancestor"
        with pytest.raises(DomainError):
            client.portal.call(hydrate, sibling.id)
        with app.state.database.session_factory() as db:
            db.delete(db.get(AgentRun, original.id))
            db.commit()
        with pytest.raises(DomainError):
            client.portal.call(hydrate, original.id)
