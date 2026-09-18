"""Persisted execution receipts survive streams, history refresh and runtime restart."""

import json
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.agent.model import ModelStreamEvent
from app.agent.outcomes import OPERATION_METADATA_MAX_BYTES, summarize_turn
from app.agent.tools import ToolApproval, ToolDefinition, ToolExecutionContext
from app.agent.tools.materials import build_material_tools
from app.main import create_app
from app.persistence.materials import canonical_json
from app.persistence.models import AgentRun, AgentToolReceipt
from app.persistence.scope import LOCAL_SCOPE
from tests.test_runtime import FakeAgentEventStream


def wait_for_status(client, run_id, status):
    deadline = time.monotonic() + 10
    runtime = client.app.state.agent_runtime
    snapshot = None
    while time.monotonic() < deadline:
        snapshot = client.portal.call(runtime.snapshot, run_id)
        if snapshot and snapshot.run.status == status:
            return snapshot
        time.sleep(0.01)
    pytest.fail(f"Expected {status}: {snapshot}")


class ReceiptModel:
    def __init__(self, tool_name="apply_batch"):
        self.requests = []
        self.tool_name = tool_name

    async def stream(self, messages, *, tools=None):
        self.requests.append(deepcopy(messages))
        if not any(row.get("role") == "tool" for row in messages):
            yield ModelStreamEvent(
                kind="tool_calls",
                tool_calls=[
                    {
                        "id": "write-call",
                        "name": self.tool_name,
                        "arguments": "{}",
                    }
                ],
            )
        else:
            yield ModelStreamEvent(kind="content", content="The execution receipts are available.")


def tool_result():
    def change(resource_id):
        return {
            "resource_id": resource_id,
            "resource_type": "record",
            "title": resource_id,
            "action": "update",
            "fields": [{"label": "Status", "before": "pending", "value": "ready"}],
        }

    return {
        "ok": False,
        "items": [
            {"operation_receipt": {"state": "committed", "changes": [change("saved")]}},
            {"status": "draft", "changes": [change("draft")]},
            {"status": "failed", "changes": [change("failed")]},
        ],
    }


def history_parts(client, session_id):
    response = client.get(f"/api/v1/agent/sessions/{session_id}")
    assert response.status_code == 200
    return next(
        row["content_parts"] for row in response.json()["messages"] if row["role"] == "assistant"
    )


def notice(messages):
    return next(
        row["content"]
        for row in messages
        if row.get("role") == "system" and row["content"].startswith("Server execution evidence")
    )


def test_mixed_write_evidence_matches_sse_snapshot_history_and_restart(settings):
    async def execute(arguments, context):
        return tool_result()

    tool = ToolDefinition(
        name="apply_batch",
        description="Apply record changes.",
        parameters={"type": "object", "properties": {}},
        handler=execute,
        effect="write",
        resident=True,
    )
    model, stream = ReceiptModel(), FakeAgentEventStream()
    with TestClient(
        create_app(settings, model_client=model, event_stream=stream, additional_tools=(tool,))
    ) as client:
        response = client.post(
            "/api/v1/agent/sessions",
            headers={"Idempotency-Key": "mixed"},
            json={"content": "Update three records."},
        )
        assert response.status_code == 200, response.text
        created = response.json()
        run_id, session_id = created["run"]["id"], created["session"]["id"]
        final = wait_for_status(client, run_id, "completed")
        persisted = [part.model_dump(mode="json") for part in final.content_parts]
        summary = summarize_turn(persisted)
        assert summary["counts"]["committed"] == 1
        assert summary["counts"]["draft"] == 1
        assert summary["counts"]["failed"] == 1
        assert [row["resource_id"] for row in summary["changes"]] == ["saved"]
        assert '"committed":1' in notice(model.requests[1])
        assert '"draft":1' in notice(model.requests[1])
        assert '"failed":1' in notice(model.requests[1])
        assert summarize_turn(history_parts(client, session_id)) == summary
        events = [row for row in stream.events if row["event"] == "tool_call"]
        starting = next(
            row["data"]["metadata"]
            for row in events
            if row["data"].get("metadata", {}).get("status") == "running"
        )
        assert starting["operation_outcome"]["state"] == "unknown"
        assert starting["changes"] == []
        event_metadata = next(
            row["data"]["metadata"]
            for row in reversed(events)
            if "operation_outcome" in row["data"].get("metadata", {})
        )
        assert event_metadata["operation_outcome"]["state"] == "partial"
        assert [row["resource_id"] for row in event_metadata["changes"]] == ["saved"]
    with TestClient(
        create_app(
            settings,
            model_client=ReceiptModel(),
            event_stream=FakeAgentEventStream(),
            additional_tools=(tool,),
        )
    ) as restarted:
        assert summarize_turn(history_parts(restarted, session_id)) == summary
        assert (
            summarize_turn(
                [
                    part.model_dump(mode="json")
                    for part in restarted.portal.call(
                        restarted.app.state.agent_runtime.snapshot, run_id
                    ).content_parts
                ]
            )
            == summary
        )


def test_legacy_tool_acknowledgement_is_unconfirmed_in_the_next_model_request(settings):
    async def execute(arguments, context):
        return {"ok": True, "status": "committed", "message": "Saved everything"}

    tool = ToolDefinition(
        name="legacy_tool",
        description="Legacy application tool.",
        parameters={"type": "object", "properties": {}},
        handler=execute,
        resident=True,
    )
    model = ReceiptModel("legacy_tool")
    with TestClient(
        create_app(
            settings,
            model_client=model,
            event_stream=FakeAgentEventStream(),
            additional_tools=(tool,),
        )
    ) as client:
        created = client.post(
            "/api/v1/agent/sessions",
            headers={"Idempotency-Key": "legacy"},
            json={"content": "Run application tool"},
        ).json()
        final = wait_for_status(client, created["run"]["id"], "completed")
        summary = summarize_turn([part.model_dump(mode="json") for part in final.content_parts])
        assert summary["counts"]["unknown"] == 1
        assert summary["counts"]["committed"] == 0
        assert summary["changes"] == []
        assert '"unknown":1' in notice(model.requests[1])


def test_cancelled_approval_after_restart_is_noop_and_never_runs_the_write(settings):
    executions = []

    async def prepare(arguments, context):
        return ToolApproval(query="Apply record changes?", payload={"operation_id": "original"})

    async def execute(arguments, context):
        executions.append(arguments)
        return {"status": "committed"}

    tool = ToolDefinition(
        name="approved_write",
        description="Change a record after approval.",
        parameters={"type": "object", "properties": {}},
        handler=prepare,
        approval_handler=execute,
        effect="write",
        resident=True,
    )
    model = ReceiptModel("approved_write")
    with TestClient(
        create_app(
            settings,
            model_client=model,
            event_stream=FakeAgentEventStream(),
            additional_tools=(tool,),
        )
    ) as client:
        created = client.post(
            "/api/v1/agent/sessions",
            headers={"Idempotency-Key": "approval"},
            json={"content": "Prepare a change"},
        ).json()
        run_id, session_id = created["run"]["id"], created["session"]["id"]
        waiting = wait_for_status(client, run_id, "waiting_for_user")
        question_id = next(
            part.metadata["question_id"]
            for part in waiting.content_parts
            if part.kind == "user_question"
        )
    with TestClient(
        create_app(
            settings,
            model_client=model,
            event_stream=FakeAgentEventStream(),
            additional_tools=(tool,),
        )
    ) as restarted:
        response = restarted.post(
            f"/api/v1/agent/questions/{question_id}/respond",
            headers={"Idempotency-Key": "cancel-approval"},
            json={"action": "cancel"},
        )
        assert response.status_code == 200, response.text
        final = wait_for_status(restarted, run_id, "completed")
        summary = summarize_turn([part.model_dump(mode="json") for part in final.content_parts])
        assert summary["counts"]["noop"] == 1
        assert summary["counts"]["committed"] == 0
        assert executions == []
        assert summary["changes"] == []
        assert summarize_turn(history_parts(restarted, session_id)) == summary
        assert '"noop":1' in notice(model.requests[-1])
        assert "original" not in json.dumps(history_parts(restarted, session_id))


def test_write_then_lost_response_remains_unconfirmed_without_duplicate_execution(settings):
    executions = []

    async def execute(arguments, context):
        executions.append(context.tool_call_id)
        raise TimeoutError("Response lost after a possible external commit")

    tool = ToolDefinition(
        name="apply_batch",
        description="Write with an uncertain response.",
        parameters={"type": "object", "properties": {}},
        handler=execute,
        effect="write",
        resident=True,
    )
    model = ReceiptModel()
    with TestClient(
        create_app(
            settings,
            model_client=model,
            event_stream=FakeAgentEventStream(),
            additional_tools=(tool,),
        )
    ) as client:
        response = client.post(
            "/api/v1/agent/sessions",
            headers={"Idempotency-Key": "uncertain"},
            json={"content": "Apply the operation once"},
        )
        assert response.status_code == 200, response.text
        final = wait_for_status(client, response.json()["run"]["id"], "completed")
        summary = summarize_turn([part.model_dump(mode="json") for part in final.content_parts])
        assert executions == ["write-call"]
        assert summary["counts"]["unknown"] == 1
        assert summary["counts"]["committed"] == 0
        assert summary["changes"] == []
        assert '"unknown":1' in notice(model.requests[-1])


def test_large_committed_write_keeps_bounded_public_changes_and_complete_readable_receipt(settings):
    tail = "FULL_SAVED_FIELD_TAIL_82fb"
    result = {
        "ok": True,
        "items": [
            {
                "state": "committed",
                "changes": [
                    {
                        "resource_id": str(index),
                        "resource_type": "record",
                        "title": f"Record {index}",
                        "action": "update",
                        "fields": [
                            {"label": f"Field {field}", "value": "x" * 3000} for field in range(8)
                        ],
                    }
                ],
            }
            for index in range(80)
        ],
    }
    result["items"][-1]["changes"][0]["fields"][-1]["value"] += tail
    full_json = canonical_json(result)
    assert 1_900_000 < len(full_json.encode()) < 4 * 1024 * 1024
    executions = []

    async def execute(arguments, context):
        executions.append(context.tool_call_id)
        return result

    class LargeModel:
        receipt_id = ""

        async def stream(self, messages):
            latest = messages[-1]
            if latest["role"] != "tool":
                yield ModelStreamEvent(
                    kind="tool_calls",
                    tool_calls=[
                        {
                            "id": "large-write",
                            "name": "apply_large_batch",
                            "arguments": "{}",
                        }
                    ],
                )
            elif latest["name"] == "apply_large_batch":
                reference = json.loads(latest["content"])
                assert reference["type"] == "cornagent_material_ref"
                self.receipt_id = reference["receipt_id"]
                yield ModelStreamEvent(
                    kind="tool_calls",
                    tool_calls=[
                        {
                            "id": "read-large",
                            "name": "read_tool_result",
                            "arguments": json.dumps(
                                {
                                    "receipt_id": self.receipt_id,
                                    "max_chars": 20_000,
                                }
                            ),
                        }
                    ],
                )
            else:
                page = json.loads(latest["content"])
                assert latest["name"] == "read_tool_result"
                assert page["ok"] and len(page["content"]) == 20_000 and page["next_cursor"]
                yield ModelStreamEvent(
                    kind="content", content="80 writes were committed; full receipt saved."
                )

    model = LargeModel()
    tool = ToolDefinition(
        name="apply_large_batch",
        description="Commit a large batch.",
        parameters={"type": "object", "properties": {}},
        handler=execute,
        effect="write",
    )
    app = create_app(
        settings, model_client=model, event_stream=FakeAgentEventStream(), additional_tools=(tool,)
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/sessions",
            headers={"Idempotency-Key": "large-receipt"},
            json={"content": "Commit the full batch"},
        )
        assert response.status_code == 200, response.text
        created = response.json()
        final = wait_for_status(client, created["run"]["id"], "completed")
        metadata = next(
            part.metadata
            for part in final.content_parts
            if part.metadata and part.metadata.get("tool_name") == "apply_large_batch"
        )
        public = {key: metadata[key] for key in ("operation_outcome", "changes")}
        assert len(canonical_json(public).encode()) <= OPERATION_METADATA_MAX_BYTES
        assert public["operation_outcome"]["truncated"] is True
        assert public["operation_outcome"]["counts"]["committed"] == 80
        assert tail not in json.dumps(public)
        assert executions == ["large-write"]
        with app.state.database.session_factory() as db:
            receipt = db.get(AgentToolReceipt, model.receipt_id)
            assert receipt.result_json == full_json
            run = db.get(AgentRun, created["run"]["id"])
            assert len(canonical_json(run.checkpoint).encode()) < 3 * 1024 * 1024
            safe_part = next(
                part
                for part in run.checkpoint["safe_content_parts"]
                if part.get("metadata", {}).get("tool_name") == "apply_large_batch"
            )
            assert safe_part["metadata"]["operation_outcome"]["truncated"] is True
        reader = next(
            tool
            for tool in build_material_tools(app.state.database.session_factory)
            if tool.name == "read_tool_result"
        )
        context = ToolExecutionContext(
            tenant_id=LOCAL_SCOPE.tenant_id,
            owner_membership_id=LOCAL_SCOPE.membership_id,
            run_id=created["run"]["id"],
            session_id=created["session"]["id"],
        )
        cursor, fragments = "", []
        while True:
            page = client.portal.call(
                reader.handler,
                {"receipt_id": model.receipt_id, "cursor": cursor, "max_chars": 20_000},
                context,
            )
            assert page["ok"] and page["complete"] and not page["source_truncated"]
            fragments.append(page["content"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(fragments) > 90
        assert "".join(fragments) == full_json
        assert tail in fragments[-1]
