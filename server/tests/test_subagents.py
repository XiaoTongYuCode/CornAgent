"""Orchestration/recovery regression adapted from the archived agent_server suite."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.model import ModelStreamEvent
from app.agent.subagents.protocol import SubagentOptions
from app.agent.subagents.tools import build_subagent_orchestration_tools, parse_operation
from app.agent.tool_executor import AgentToolExecutor
from app.agent.tools import AgentToolCatalog, RuntimeToolCall, ToolExecutionContext
from app.agent.tools.mock_search import build_mock_web_search_tool
from app.database import Database
from app.main import create_app
from app.persistence.agent_runtime import AgentRepository, _now, checkpoint_json_size_bytes
from app.persistence.errors import DomainError
from app.persistence.models import AgentRun, AgentSubagentTask
from app.persistence.scope import LOCAL_SCOPE
from app.persistence.subagents import CheckpointSpaceNeeded, SubagentRepository
from tests.test_lifecycle import post, start, wait_run
from tests.test_runtime import FailingAgentEventStream, FakeAgentEventStream


def tasks(count=2, *, required=True):
    return [
        {
            "title": f"Task {index}",
            "instruction": "用模拟搜索研究演示电池方案，标注模拟资料。",
            "expected_output": "结构化摘要、证据和缺口",
            "profile": ("researcher", "analyst", "verifier")[index % 3],
            "required": required,
        }
        for index in range(count)
    ]


def tool_event(name, args, call_id=None):
    return ModelStreamEvent(
        kind="tool_calls",
        tool_calls=[
            {
                "id": call_id or f"call-{name}",
                "name": name,
                "arguments": json.dumps(args),
            }
        ],
    )


class ChildModel:
    def __init__(self, *, delay=0.02, gate=None, result_status="completed"):
        self.delay = delay
        self.gate = gate
        self.result_status = result_status
        self.requests = []

    async def stream(self, messages):
        self.requests.append(messages)
        if messages[-1]["role"] != "tool":
            yield tool_event("mock_web_search", {"query": "电池 方案 风险"})
            return
        while self.gate is not None and not self.gate.is_set():
            await asyncio.sleep(0.01)
        await asyncio.sleep(self.delay)
        assert json.loads(messages[-1]["content"])["is_mock"] is True
        yield ModelStreamEvent(
            kind="content",
            content=json.dumps(
                {
                    "status": self.result_status,
                    "summary": "模拟资料：模块便于维护，接口兼容性待验证。",
                    "evidence": [
                        {
                            "claim": "模拟接口存在待验证项",
                            "source_title": "模拟资料",
                            "url": "https://example.com/cornagent-demo/integration-risk",
                        }
                    ],
                    "warnings": ["缺少真实成本数据"],
                },
                ensure_ascii=False,
            ),
        )
        yield ModelStreamEvent(kind="usage", payload={"completion_tokens": 12})

    async def compact(self, _messages, *, max_tokens):
        return {"summary": "压缩后的模拟任务历史"}


class RootModel:
    def __init__(self, *, delegate=False, premature=False, required=True):
        self.delegate = delegate
        self.premature = premature
        self.required = required
        self.requests = []
        self.counter = 0

    async def stream(self, messages):
        self.requests.append(messages)
        self.counter += 1
        tools = [item for item in messages if item.get("role") == "tool"]
        if not tools:
            yield tool_event(
                "delegate_tasks" if self.delegate else "spawn_subagents",
                {"tasks": tasks(3, required=self.required)},
                "dispatch",
            )
            return
        last = tools[-1]
        payload = json.loads(last["content"])
        if not self.required or (self.premature and last["name"] == "spawn_subagents"):
            yield ModelStreamEvent(kind="reasoning", content="PREMATURE REASONING")
            yield ModelStreamEvent(kind="content", content="PREMATURE ANSWER")
            return
        if last["name"] == "spawn_subagents":
            yield tool_event("list_subagents", {}, "list")
        elif last["name"] == "list_subagents":
            yield tool_event("mock_web_search", {"query": "电池 比较"}, "root-search")
        elif last["name"] == "mock_web_search":
            yield tool_event("collect_subagent_results", {}, "collect-first")
        elif payload.get("undelivered_result_task_ids"):
            yield tool_event(
                "collect_subagent_results",
                {"task_ids": payload["undelivered_result_task_ids"]},
                f"collect-{self.counter}",
            )
        elif payload.get("pending_task_ids"):
            yield tool_event(
                "wait_subagents",
                {"task_ids": payload["pending_task_ids"], "return_when": "all"},
                f"wait-{self.counter}",
            )
        else:
            yield ModelStreamEvent(kind="content", content="模拟资料汇总完成。")

    async def compact(self, _messages, *, max_tokens):
        return {"summary": "压缩后的主任务历史"}


def app(settings, root=None, child=None, stream=None):
    settings.agent_subagent_reconcile_seconds = 0.02
    return create_app(
        settings,
        model_client=root or RootModel(),
        child_model_client=child or ChildModel(),
        event_stream=stream or FakeAgentEventStream(),
    )


def wait_children(database, run_id, *, status="completed", count=1):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with database.session_factory() as db:
            rows = list(
                db.scalars(select(AgentSubagentTask).where(AgentSubagentTask.root_run_id == run_id))
            )
            if len(rows) >= count and all(row.status == status for row in rows):
                return
        time.sleep(0.01)
    pytest.fail(f"Children did not reach {status}")


@pytest.mark.parametrize("delegate", [False, True])
def test_complete_orchestration_with_shared_mock_tool(settings, delegate):
    root, child, stream = RootModel(delegate=delegate), ChildModel(), FakeAgentEventStream()
    settings.agent_max_concurrency = 1  # A waiting Root must release its only slot.
    with TestClient(app(settings, root, child, stream)) as client:
        created = start(client)
        detail = wait_run(client, created["session"]["id"])
        answer = detail["messages"][-1]
        assert answer["markdown"] == "模拟资料汇总完成。"
        parts = [
            part for part in answer["content_parts"] if part.get("metadata", {}).get("subagent")
        ]
        assert len(parts) == 3
        assert {part["metadata"]["profile"] for part in parts} == {
            "researcher",
            "analyst",
            "verifier",
        }
        assert all(part["metadata"]["delivery_status"] == "delivered" for part in parts)
        assert len(child.requests) == 6
        assert all("模拟资料" in part["content"] for part in parts)
        with client.app.state.database.session_factory() as db:
            run = db.get(AgentRun, created["run"]["id"])
            calls = [
                message["name"]
                for message in run.checkpoint["provider_messages"]
                if message["role"] == "tool"
            ]
            if delegate:
                assert "delegate_tasks" in calls
            else:
                assert {
                    "spawn_subagents",
                    "list_subagents",
                    "mock_web_search",
                    "collect_subagent_results",
                    "wait_subagents",
                } <= set(calls)
        metrics = client.get("/metrics").text
        assert "cornagent_subagent_finished_total" in metrics


def test_guard_discards_uncollected_final_candidate(settings):
    stream = FakeAgentEventStream()
    with TestClient(
        app(settings, RootModel(premature=True), ChildModel(delay=0.05), stream)
    ) as client:
        created = start(client)
        detail = wait_run(client, created["session"]["id"])
        assert detail["messages"][-1]["markdown"] == "模拟资料汇总完成。"
        assert "PREMATURE" not in json.dumps(detail)
        assert "PREMATURE" not in json.dumps(stream.events)
        assert any(
            event["event"] == "session"
            and event["data"].get("run", {}).get("status") == "waiting_for_subagents"
            for event in stream.events
        )


def test_wait_restart_and_expired_child_lease(settings):
    gate = threading.Event()
    root = RootModel(delegate=True)
    with TestClient(app(settings, root, ChildModel(gate=gate))) as client:
        created = start(client)
        run_id, session_id = created["run"]["id"], created["session"]["id"]
        wait_run(client, session_id, "waiting_for_subagents")
        time.sleep(0.05)
    database = Database(settings)
    with database.session_factory() as db:
        for task in db.scalars(
            select(AgentSubagentTask).where(AgentSubagentTask.root_run_id == run_id)
        ):
            task.lease_expires_at = _now() - timedelta(seconds=1)
        root_row = db.get(AgentRun, run_id)
        assert root_row.lease_owner is None
        assert root_row.checkpoint["provider_messages"][-1]["tool_calls"][0]["id"] == "dispatch"
        db.commit()
    with TestClient(app(settings, RootModel(delegate=True), ChildModel())) as client:
        detail = wait_run(client, session_id)
        assert detail["messages"][-1]["run"]["id"] == run_id
        assert detail["messages"][-1]["run"]["stream_epoch"] >= 2
        with database.session_factory() as db:
            rows = list(
                db.scalars(select(AgentSubagentTask).where(AgentSubagentTask.root_run_id == run_id))
            )
            assert len(rows) == 3
            assert all(row.delivery_status == "delivered" for row in rows)
            assert any(row.attempt_count > 1 for row in rows)
    database.close()


@pytest.mark.parametrize("mode", ["cancel", "delete", "optional"])
def test_root_terminal_cascades_to_children(settings, mode):
    gate = threading.Event()
    with TestClient(
        app(
            settings,
            RootModel(delegate=mode != "optional", required=mode != "optional"),
            ChildModel(gate=gate),
        )
    ) as client:
        created = start(client)
        run_id, session_id = created["run"]["id"], created["session"]["id"]
        if mode == "optional":
            wait_run(client, session_id)
        else:
            wait_run(client, session_id, "waiting_for_subagents")
            assert post(client, f"/runs/{run_id}/cancel").status_code == 200
            wait_run(client, session_id, "cancelled")
        with client.app.state.database.session_factory() as db:
            rows = list(
                db.scalars(select(AgentSubagentTask).where(AgentSubagentTask.root_run_id == run_id))
            )
            assert len(rows) == 3
            assert all(
                row.status == "cancelled" and row.delivery_status == "ignored" for row in rows
            )
            if mode != "optional":
                run = db.get(AgentRun, run_id)
                assert "subagent_wait" not in run.checkpoint
                messages = run.checkpoint["provider_messages"]
                assert messages[-1]["role"] == "tool"
                assert messages[-1]["tool_call_id"] == "dispatch"
                assert json.loads(messages[-1]["content"])["status"] == "cancelled"
                control = next(part for part in run.content_parts if part["id"] == "tool-dispatch")
                assert control["metadata"]["status"] == "cancelled"
        if mode == "delete":
            response = client.delete(
                f"/api/v1/agent/sessions/{session_id}", headers={"Idempotency-Key": str(uuid4())}
            )
            assert response.status_code == 200, response.text
            with client.app.state.database.session_factory() as db:
                assert not list(db.scalars(select(AgentSubagentTask)))
        gate.set()


def seed(database):
    with database.session_factory() as db:
        session, run = AgentRepository(db).create_session_run(
            LOCAL_SCOPE, content="test", idempotency_key=str(uuid4())
        )
        _, fence, _ = AgentRepository(db).claim_run(run.id, "root-worker")
    return session.id, run.id, fence


def call_for(database, run_id, fence, name, arguments, call_id):
    definition = next(tool for tool in build_subagent_orchestration_tools() if tool.name == name)
    with database.session_factory() as db:
        state = AgentRepository(db).runtime_state(run_id, "root-worker", fence)
    return RuntimeToolCall(
        definition,
        run_id,
        "root-worker",
        fence,
        call_id,
        arguments,
        state["checkpoint"]["provider_messages"],
        "",
        "",
        {},
        [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
        ToolExecutionContext(run_id=run_id),
    )


def operate(database, call, options=None):
    with database.session_factory() as db:
        return SubagentRepository(db, options).operate(
            call, parse_operation(call.definition.name, call.arguments, call.tool_call_id)
        )


def finish(database, task_id, summary="result", status="completed"):
    with database.session_factory() as db:
        claim, _ = SubagentRepository(db).claim(task_id, "child-worker")
    with database.session_factory() as db:
        SubagentRepository(db).finish(
            task_id,
            "child-worker",
            claim["fence"],
            {"status": status, "summary": summary, "evidence": [], "warnings": [], "usage": {}},
        )
    return claim


def task_rows(database, run_id):
    with database.session_factory() as db:
        return list(
            db.scalars(
                select(AgentSubagentTask)
                .where(AgentSubagentTask.root_run_id == run_id)
                .order_by(AgentSubagentTask.ordinal)
            )
        )


def test_spawn_and_delivery_idempotency_and_full_result_batches(settings):
    database = Database(settings)
    _, run_id, fence = seed(database)
    spawn = call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks()}, "spawn")
    operate(database, spawn)
    operate(database, spawn)
    children = task_rows(database, run_id)
    assert len(children) == 2
    summaries = ["A" * 70_000, "B" * 70_000]
    for child, summary in zip(children, summaries, strict=True):
        finish(database, child.id, summary)
    collect = call_for(database, run_id, fence, "collect_subagent_results", {}, "collect")
    _, messages, _ = operate(database, collect)
    payload = json.loads(messages[-1]["content"])
    assert payload["results"][0]["summary"] == summaries[0]
    assert payload["undelivered_result_task_ids"] == [children[1].id]
    assert payload["pending_task_ids"] == []
    assert payload["next_action"] == "collect_subagent_results"
    _, replay, _ = operate(database, collect)
    assert replay == messages
    assert [task.delivery_status for task in task_rows(database, run_id)] == [
        "delivered",
        "pending",
    ]
    operate(
        database, call_for(database, run_id, fence, "collect_subagent_results", {}, "collect-next")
    )
    assert all(task.delivery_status == "delivered" for task in task_rows(database, run_id))
    with database.session_factory() as db:
        parts = db.get(AgentRun, run_id).content_parts
        assert all(
            len(part["content"]) <= 8000
            for part in parts
            if part.get("metadata", {}).get("subagent")
        )
    database.close()


@pytest.mark.parametrize("return_when", ["all", "any"])
def test_wait_predicate_is_independent_of_result_batching(settings, return_when):
    database = Database(settings)
    _, run_id, fence = seed(database)
    operate(
        database, call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks()}, "spawn")
    )
    children = task_rows(database, run_id)
    finish(database, children[0].id, "x" * 70_000)
    wait = call_for(
        database,
        run_id,
        fence,
        "wait_subagents",
        {"task_ids": [task.id for task in children], "return_when": return_when},
        "wait",
    )
    status, messages, _ = operate(database, wait)
    if return_when == "any":
        assert status == "continue"
        assert json.loads(messages[-1]["content"])["pending_task_ids"] == [children[1].id]
    else:
        assert status == "waiting_for_subagents"
        assert all(task.delivery_status == "pending" for task in task_rows(database, run_id))
        with database.session_factory() as db:
            assert not SubagentRepository(db).resume_wait(run_id)
        finish(database, children[1].id, "y" * 70_000)
        with database.session_factory() as db:
            assert SubagentRepository(db).resume_wait(run_id)
            payload = json.loads(
                db.get(AgentRun, run_id).checkpoint["provider_messages"][-1]["content"]
            )
            assert payload["pending_task_ids"] == []
            assert payload["undelivered_result_task_ids"] == [children[1].id]
    database.close()


def test_wait_timeout_does_not_cancel_child_and_disabled_flag_drains(settings):
    database = Database(settings)
    _, run_id, fence = seed(database)
    operate(
        database,
        call_for(database, run_id, fence, "delegate_tasks", {"tasks": tasks(1)}, "delegate"),
    )
    with database.session_factory() as db:
        run = db.get(AgentRun, run_id)
        checkpoint = dict(run.checkpoint)
        checkpoint["subagent_wait"] = {
            **checkpoint["subagent_wait"],
            "deadline_at": (_now() - timedelta(seconds=1)).isoformat(),
        }
        run.checkpoint = checkpoint
        db.commit()
        assert SubagentRepository(db, SubagentOptions(enabled=False)).resume_wait(run_id)
        payload = json.loads(run.checkpoint["provider_messages"][-1]["content"])
        assert payload["timed_out"] is True
        assert payload["pending_task_ids"]
        assert db.get(AgentSubagentTask, payload["pending_task_ids"][0]).status == "queued"
        _, fence, _ = AgentRepository(db).claim_run(run_id, "root-worker")
    with pytest.raises(DomainError, match="disabled"):
        operate(
            database,
            call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks(1)}, "new"),
            SubagentOptions(enabled=False),
        )
    child = task_rows(database, run_id)[0]
    finish(database, child.id)
    operate(
        database,
        call_for(database, run_id, fence, "collect_subagent_results", {}, "collect"),
        SubagentOptions(enabled=False),
    )
    assert task_rows(database, run_id)[0].delivery_status == "delivered"
    database.close()


def test_oversized_delivery_rolls_back_markers(settings):
    database = Database(settings)
    _, run_id, fence = seed(database)
    operate(
        database, call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks(1)}, "spawn")
    )
    child = task_rows(database, run_id)[0]
    finish(database, child.id, "x" * 2_000_000)
    with pytest.raises(CheckpointSpaceNeeded):
        operate(
            database, call_for(database, run_id, fence, "collect_subagent_results", {}, "collect")
        )
    assert task_rows(database, run_id)[0].delivery_status == "pending"
    with database.session_factory() as db:
        assert all(
            message.get("tool_call_id") != "collect"
            for message in db.get(AgentRun, run_id).checkpoint["provider_messages"]
        )
    database.close()


def test_finalization_guard_transaction_and_late_result_fencing(settings):
    database = Database(settings)
    _, run_id, fence = seed(database)
    operate(
        database, call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks(1)}, "spawn")
    )
    child = task_rows(database, run_id)[0]
    with database.session_factory() as db, pytest.raises(DomainError, match="Required"):
        AgentRepository(db).complete_run(
            run_id, "root-worker", fence, provider_messages=[], usage={}
        )
    with database.session_factory() as db:
        first, _ = SubagentRepository(db).claim(child.id, "dead")
        row = db.get(AgentSubagentTask, child.id)
        row.lease_expires_at = _now() - timedelta(seconds=1)
        db.commit()
        SubagentRepository(db).recover()
        second, _ = SubagentRepository(db).claim(child.id, "new")
        assert second["fence"] > first["fence"]
        assert (
            SubagentRepository(db).finish(child.id, "dead", first["fence"], {"status": "completed"})
            == []
        )
        AgentRepository(db).cancel_run(LOCAL_SCOPE, run_id, "cancel")
    with database.session_factory() as db, pytest.raises(DomainError, match="no longer active"):
        SubagentRepository(db).finish(child.id, "new", second["fence"], {"status": "completed"})
    database.close()


def test_read_only_scopes_are_enforced_and_mock_is_deterministic():
    mock = build_mock_web_search_tool()

    async def run():
        executor = AgentToolExecutor(AgentToolCatalog([mock]))
        root = await executor.execute_tool(mock.name, {"query": "电池"})
        child = await executor.execute_tool(
            mock.name, {"query": "电池"}, context=ToolExecutionContext(execution_scope="child")
        )
        assert root == child and child["is_mock"] is True
        denied = await AgentToolExecutor(
            AgentToolCatalog(build_subagent_orchestration_tools())
        ).execute_tool("spawn_subagents", {}, context=ToolExecutionContext(execution_scope="child"))
        assert denied["error"]["type"] == "ToolScopeDenied"

    asyncio.run(run())
    with pytest.raises(ValueError, match="read-only"):
        replace(mock, read_only=False)
    with pytest.raises(ValueError, match="read-only"):
        replace(mock, runtime_handler="write")
    assert AgentToolCatalog([mock]).for_scope("child").names() == ("mock_web_search",)


@pytest.mark.parametrize(
    "arguments",
    [
        {"tasks": []},
        {"tasks": tasks(11)},
        {"tasks": tasks(1), "max_concurrency": True},
        {"tasks": tasks(1), "max_concurrency": 2},
        {"tasks": [{**tasks(1)[0], "profile": "root"}]},
        {"tasks": [{**tasks(1)[0], "required": "yes"}]},
        {"tasks": tasks(1), "extra": 1},
    ],
)
def test_copied_spawn_validators(arguments):
    with pytest.raises(ValueError):
        parse_operation("spawn_subagents", arguments, "call")


def test_cross_root_task_selection_is_rejected(settings):
    database = Database(settings)
    _, run_id, fence = seed(database)
    _, other, other_fence = seed(database)
    operate(
        database, call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks(1)}, "spawn")
    )
    with pytest.raises(DomainError, match="belong"):
        operate(
            database,
            call_for(
                database,
                other,
                other_fence,
                "collect_subagent_results",
                {"task_ids": [task_rows(database, run_id)[0].id]},
                "foreign",
            ),
        )
    database.close()


def test_postgres_concurrent_claims_respect_root_limit(settings):
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("Requires PostgreSQL row locking")
    database = Database(settings)
    _, run_id, fence = seed(database)
    operate(
        database, call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks(4)}, "spawn")
    )
    ids = [task.id for task in task_rows(database, run_id)]
    barrier = threading.Barrier(len(ids))

    def claim(task_id):
        barrier.wait(timeout=5)
        with database.session_factory() as db:
            return SubagentRepository(db, SubagentOptions(run_max_concurrency=1)).claim(
                task_id, task_id
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(claim, ids))
    assert sum(result is not None for result in results) == 1
    database.close()


def test_redis_failure_preserves_children_and_final_snapshot(settings):
    with TestClient(
        app(settings, RootModel(delegate=True), ChildModel(), FailingAgentEventStream())
    ) as client:
        created = start(client)
        wait_run(client, created["session"]["id"])
        response = client.get(f"/api/v1/agent/runs/{created['run']['id']}/stream")
        snapshot = json.loads(
            next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        )
        assert snapshot["run"]["status"] == "completed"
        assert (
            len(
                [
                    part
                    for part in snapshot["content_parts"]
                    if part.get("metadata", {}).get("subagent")
                ]
            )
            == 3
        )


@pytest.mark.parametrize("result_status", ["needs_input", "failed", "timed_out"])
def test_child_non_success_is_collected_before_finalization(settings, result_status):
    class ErrorChild(ChildModel):
        async def stream(self, messages):
            if result_status == "failed":
                raise RuntimeError("simulated provider failure")
            if result_status == "timed_out":
                await asyncio.Event().wait()
            async for event in super().stream(messages):
                yield event

    if result_status == "timed_out":
        settings.agent_subagent_timeout_seconds = 0.15
    with TestClient(
        app(settings, RootModel(delegate=True), ErrorChild(result_status="needs_input"))
    ) as client:
        created = start(client)
        detail = wait_run(client, created["session"]["id"])
        parts = [
            part
            for part in detail["messages"][-1]["content_parts"]
            if part.get("metadata", {}).get("subagent")
        ]
        assert all(part["metadata"]["status"] == result_status for part in parts)
        assert all(part["metadata"]["delivery_status"] == "delivered" for part in parts)


def test_children_complete_without_resuming_a_user_question(settings):
    class QuestionRoot(RootModel):
        async def stream(self, messages):
            tools = [item for item in messages if item.get("role") == "tool"]
            if tools and tools[-1]["name"] == "spawn_subagents":
                yield tool_event(
                    "ask_user",
                    {
                        "query": "选择演示方案",
                        "options": [{"content": "继续", "description": "继续分析"}],
                    },
                    "question",
                )
                return
            async for event in super().stream(messages):
                yield event

    with TestClient(app(settings, QuestionRoot(), ChildModel())) as client:
        created = start(client)
        run_id, session_id = created["run"]["id"], created["session"]["id"]
        wait_run(client, session_id, "waiting_for_user")
        wait_children(client.app.state.database, run_id, count=3)
        detail = wait_run(client, session_id, "waiting_for_user")
        question = next(
            part
            for part in detail["messages"][-1]["content_parts"]
            if part["kind"] == "user_question"
        )
        assert (
            post(
                client,
                f"/questions/{question['metadata']['question_id']}/respond",
                {"action": "answer", "content": "继续"},
            ).status_code
            == 200
        )
        detail = wait_run(client, session_id)
        assert all(
            part["metadata"]["delivery_status"] == "delivered"
            for part in detail["messages"][-1]["content_parts"]
            if part.get("metadata", {}).get("subagent")
        )


def test_child_finishing_during_guarded_stream_does_not_publish_candidate(settings):
    gate = threading.Event()
    child_done = threading.Event()

    class CompletingChild(ChildModel):
        async def stream(self, messages):
            async for event in super().stream(messages):
                yield event
            if messages[-1]["role"] == "tool":
                child_done.set()

    class GuardedRoot(RootModel):
        async def stream(self, messages):
            tools = [item for item in messages if item.get("role") == "tool"]
            if tools and tools[-1]["name"] == "spawn_subagents":
                yield ModelStreamEvent(kind="content", content="MUST BE DISCARDED")
                gate.set()
                while not child_done.is_set():
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.05)
                return
            async for event in super().stream(messages):
                yield event

    stream = FakeAgentEventStream()
    with TestClient(app(settings, GuardedRoot(), CompletingChild(gate=gate), stream)) as client:
        created = start(client)
        detail = wait_run(client, created["session"]["id"])
        assert "MUST BE DISCARDED" not in json.dumps(detail)
        assert "MUST BE DISCARDED" not in json.dumps(stream.events)


def test_guard_candidate_has_a_hard_buffer_bound(settings):
    settings.agent_subagent_final_candidate_max_bytes = 1024

    class LargeCandidate(RootModel):
        async def stream(self, messages):
            if any(item.get("role") == "tool" for item in messages):
                yield ModelStreamEvent(kind="content", content="x" * 1025)
                return
            async for event in super().stream(messages):
                yield event

    with TestClient(app(settings, LargeCandidate(), ChildModel(gate=threading.Event()))) as client:
        created = start(client)
        detail = wait_run(client, created["session"]["id"], "failed")
        assert detail["messages"][-1]["run"]["error_code"] == "subagent_final_candidate_too_large"
        assert "x" * 1025 not in json.dumps(detail)


def test_large_result_delivery_compacts_closed_history_without_losing_result(settings):
    database = Database(settings)
    _, run_id, fence = seed(database)
    operate(
        database, call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks(1)}, "spawn")
    )
    child = task_rows(database, run_id)[0]
    finish(database, child.id, "evidence" * 110_000)
    with database.session_factory() as db:
        root = db.get(AgentRun, run_id)
        history = [{"role": "user", "content": "old history " + "h" * 70_000} for _ in range(12)]
        root.checkpoint = {
            **root.checkpoint,
            "provider_messages": history,
            "safe_provider_messages": history,
        }
        db.commit()
    call = call_for(database, run_id, fence, "collect_subagent_results", {}, "collect")
    application = app(settings)
    runtime = application.state.agent_runtime
    outcome = asyncio.run(runtime.subagents.handle(call))
    assert outcome.status == "continue"
    result = json.loads(outcome.provider_messages[-1]["content"])["results"][0]
    assert result["summary"] == "evidence" * 110_000
    assert outcome.provider_messages[0]["role"] == "system"
    assert task_rows(database, run_id)[0].delivery_status == "delivered"
    asyncio.run(runtime.close())
    application.state.database.close()
    database.close()


def test_two_runtime_instances_complete_each_child_once(settings):
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("Requires PostgreSQL row locking")
    first = app(settings, RootModel(delegate=True), ChildModel(delay=0.1))
    second = app(settings, RootModel(delegate=True), ChildModel(delay=0.1))
    with TestClient(first) as client, TestClient(second):
        created = start(client)
        wait_run(client, created["session"]["id"])
        rows = task_rows(first.state.database, created["run"]["id"])
        assert len(rows) == 3
        assert all(row.attempt_count == 1 for row in rows)
        assert sorted(row.completion_seq for row in rows) == [1, 2, 3]
        assert all(row.delivery_status == "delivered" for row in rows)


@pytest.mark.parametrize("epoch_change", [False, True])
def test_sse_gap_replaces_snapshot_before_advancing_cursor(settings, epoch_change):
    started = threading.Event()

    class HoldingModel:
        async def stream(self, _messages):
            yield ModelStreamEvent(kind="content", content="seed")
            started.set()
            await asyncio.Event().wait()

    class OutOfOrderStream(FakeAgentEventStream):
        def __init__(self):
            super().__init__()
            self.application = None
            self.phase = 0

        async def read(self, run_id, cursor, *, block_ms=1000):
            with self.application.state.database.session_factory() as db:
                row = db.get(AgentRun, run_id)
                repo = AgentRepository(db)
                if self.phase == 0:
                    if epoch_change:
                        row.stream_epoch += 1
                        row.next_sequence = 1
                        db.commit()
                    first = repo.append_delta(
                        run_id,
                        row.lease_owner,
                        row.lease_fence,
                        kind="markdown",
                        content="A",
                        part_id="gap",
                    )
                    second = repo.append_delta(
                        run_id,
                        row.lease_owner,
                        row.lease_fence,
                        kind="markdown",
                        content="B",
                        part_id="gap",
                    )
                    self.phase = 1
                    return "1", [second, first]
                event = repo.complete_run(
                    run_id, row.lease_owner, row.lease_fence, provider_messages=[], usage={}
                )
                self.phase = 2
                return "2", [event]

    stream = OutOfOrderStream()
    application = app(settings, HoldingModel(), stream=stream)
    stream.application = application
    with TestClient(application) as client:
        created = start(client)
        assert started.wait(5)
        # The model signal precedes the buffered delta's database commit.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with application.state.database.session_factory() as db:
                if db.get(AgentRun, created["run"]["id"]).draft_markdown == "seed":
                    break
            time.sleep(0.01)
        else:
            pytest.fail("Initial model delta was not persisted")
        response = client.get(f"/api/v1/agent/runs/{created['run']['id']}/stream")
        blocks = response.text.strip().split("\n\n")
        assert "event: snapshot" in blocks[1]
        corrected = json.loads(
            next(line[6:] for line in blocks[1].splitlines() if line.startswith("data: "))
        )
        assert corrected["draft_markdown"] == "seedAB"
        assert corrected["run"]["status"] == "running"


def test_child_result_survives_a_full_root_projection_checkpoint(settings):
    database = Database(settings)
    _, run_id, fence = seed(database)
    operate(
        database, call_for(database, run_id, fence, "spawn_subagents", {"tasks": tasks(1)}, "spawn")
    )
    child = task_rows(database, run_id)[0]
    with database.session_factory() as db:
        claim, _ = SubagentRepository(db).claim(child.id, "child-worker")
        run = db.get(AgentRun, run_id)
        checkpoint = {**run.checkpoint, "padding": ""}
        checkpoint["padding"] = "x" * (
            3 * 1024 * 1024 - checkpoint_json_size_bytes(checkpoint) - 10
        )
        run.checkpoint = checkpoint
        db.commit()
    with database.session_factory() as db:
        events = SubagentRepository(db).finish(
            child.id,
            "child-worker",
            claim["fence"],
            {
                "status": "completed",
                "summary": "complete evidence " * 2000,
                "evidence": [],
                "warnings": [],
            },
        )
        assert events
        task = db.get(AgentSubagentTask, child.id)
        assert task.status == "completed"
        assert task.result_payload["summary"] == "complete evidence " * 2000
        assert task.delivery_status == "pending"
        run = db.get(AgentRun, run_id)
        assert checkpoint_json_size_bytes(run.checkpoint) <= 3 * 1024 * 1024
        projected = next(part for part in run.content_parts if part["id"] == f"subagent-{child.id}")
        assert projected["metadata"]["status"] == "completed"
        # The durable task restores the latest projection after a half-round rollback.
        from app.persistence.subagents import merge_task_projections

        run.content_parts = list(run.checkpoint["safe_content_parts"])
        merge_task_projections(db, run)
        assert (
            next(part for part in run.content_parts if part["id"] == projected["id"]) == projected
        )
    database.close()


def test_wait_compaction_provider_error_fails_root_without_delivering_result(settings):
    class BrokenCompactor(RootModel):
        async def compact(self, _messages, *, max_tokens):
            raise RuntimeError("test provider unavailable")

    database = Database(settings)
    _, run_id, fence = seed(database)
    with database.session_factory() as db:
        run = db.get(AgentRun, run_id)
        history = [{"role": "user", "content": "history" + "h" * 70_000} for _ in range(12)]
        run.checkpoint = {
            **run.checkpoint,
            "provider_messages": history,
            "safe_provider_messages": history,
        }
        db.commit()
    operate(
        database, call_for(database, run_id, fence, "delegate_tasks", {"tasks": tasks(1)}, "wait")
    )
    child = task_rows(database, run_id)[0]
    finish(database, child.id, "evidence" * 110_000)
    application = app(settings, BrokenCompactor())
    runtime = application.state.agent_runtime
    asyncio.run(runtime.subagents._resume(run_id))
    with database.session_factory() as db:
        run = db.get(AgentRun, run_id)
        assert run.status == "failed"
        assert run.error_code == "agent_context_compaction_failed"
        child = db.get(AgentSubagentTask, child.id)
        assert child.delivery_status == "ignored"
        assert child.delivered_at is None
        assert child.result_payload["summary"] == "evidence" * 110_000
    asyncio.run(runtime.close())
    application.state.database.close()
    database.close()


def test_production_child_adapter_uses_only_child_prompt_and_scoped_tools(settings, monkeypatch):
    from pydantic import SecretStr

    from app.agent.prompt import SYSTEM_PROMPT
    from app.agent.subagents.prompt import CHILD_AGENT_SYSTEM_PROMPT

    requests = []

    async def completion(**kwargs):
        requests.append(kwargs)

        async def chunks():
            yield {
                "choices": [
                    {
                        "delta": {"content": '{"status":"completed","summary":"verified"}'},
                        "finish_reason": "stop",
                    }
                ]
            }

        return chunks()

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    settings.agent_api_key = SecretStr("test-key")
    application = create_app(settings, event_stream=FakeAgentEventStream())
    runtime = application.state.agent_runtime
    claim = {
        "root_run_id": "root",
        "session_id": "session",
        "tenant_id": "tenant",
        "owner_membership_id": "owner",
        "id": "child",
        "fence": 1,
        "spec": {
            "task_key": "task",
            "title": "title",
            "profile": "researcher",
            "instruction": "inspect",
            "expected_output": "summary",
        },
    }
    result = asyncio.run(runtime.subagents.runner.run(claim, asyncio.Event()))
    assert result["status"] == "completed"
    messages = requests[0]["messages"]
    assert messages[0]["content"].startswith(CHILD_AGENT_SYSTEM_PROMPT)
    assert [message["role"] for message in messages] == ["system", "user"]
    assert not any(message.get("content") == SYSTEM_PROMPT for message in messages)
    assert {tool["function"]["name"] for tool in requests[0]["tools"]} == {
        "mock_web_search", "web_search", "read_url",
    }
    assert runtime.model_client.system_prompt == SYSTEM_PROMPT
    asyncio.run(runtime.close())
    application.state.database.close()
