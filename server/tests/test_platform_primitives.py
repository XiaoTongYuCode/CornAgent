"""Regression for the platform extension seams and durable state rules."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mcp.types import ListToolsResult, Tool

from app import platform_cli, telemetry
from app.agent import mcp_bridge
from app.agent.prompt import AgentSkillCatalog, AgentSkillDefinition
from app.agent.tools import ToolApproval, ToolDefinition, ToolExecutionContext
from app.main import create_app
from app.persistence.backend import PostgresDurableBackend
from app.persistence.transitions import transition_run
from app.settings import AgentMcpServer


def test_run_edges_reject_terminal_revival_and_allow_recovery():
    run = SimpleNamespace(status="pending")
    transition_run(run, "running")
    transition_run(run, "waiting_for_subagents")
    transition_run(run, "pending")
    transition_run(run, "cancelled")
    with pytest.raises(ValueError, match="cancelled -> running"):
        transition_run(run, "running")


@pytest.mark.parametrize("options", [{}, {"read_only": False}])
def test_approved_tool_has_stable_operation_identity(options):
    async def prepare(arguments, context):
        return ToolApproval(query="Apply?", payload=arguments)

    async def execute(payload, context):
        return {"ok": True, "operation_id": context.operation_id}

    tool = ToolDefinition.approved(
        name="change_record",
        description="Change a record",
        parameters={"type": "object", "properties": {}},
        prepare=prepare,
        execute=execute,
        **options,
    )
    assert tool.exclusive and tool.effect == "write"
    assert tool.read_only is False
    assert tool.runtime_handler == "tool_approval"
    context = ToolExecutionContext(run_id="run-1", tool_call_id="call-1")
    view = context.for_tool(tool_call_id="call-1", batch_id="b")
    assert context.operation_id == view.operation_id
    assert asyncio.run(execute({}, context))["operation_id"] == "run-1:call-1"
    with pytest.raises(ValueError):
        _ = ToolExecutionContext().operation_id


def test_approved_write_tool_rejects_read_only_classification():
    async def handler(arguments, context):
        return {"ok": True}

    with pytest.raises(ValueError, match="Approved write tools cannot be read-only"):
        ToolDefinition.approved(
            name="change_record",
            description="Change a record",
            parameters={"type": "object"},
            prepare=handler,
            execute=handler,
            read_only=True,
        )


@pytest.mark.parametrize("case", ["found", "missing", "repeated_cursor"])
def test_mcp_discovery_reads_all_pages_before_validating_allowlist(monkeypatch, case):
    cursors = []
    sessions = []
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    class Client:
        async def list_tools(self, *, params=None):
            cursor = params.cursor if params else None
            cursors.append(cursor)
            if cursor is None:
                return ListToolsResult(
                    tools=[Tool(name="unlisted", inputSchema={"type": "object"})],
                    nextCursor="second-page",
                )
            if cursor == "second-page":
                return ListToolsResult(tools=[], nextCursor="last-page")
            assert cursor == "last-page"
            return ListToolsResult(
                tools=[] if case == "missing" else [Tool(name="lookup", inputSchema=schema)],
                nextCursor="second-page" if case == "repeated_cursor" else None,
            )

    @asynccontextmanager
    async def session(url):
        sessions.append(url)
        yield Client()

    monkeypatch.setattr(mcp_bridge, "_session", session)
    configured = AgentMcpServer(
        name="catalog",
        url="https://example.org/mcp",
        tools=("lookup",),
        read_only_tools=("lookup",),
    )
    if case == "found":
        definitions = asyncio.run(mcp_bridge.discover_mcp_tools((configured,)))
        assert [tool.name for tool in definitions] == ["mcp_catalog_lookup"]
        function = definitions[0].to_provider_tool()["function"]
        assert function["parameters"] == schema
        assert function.get("strict") is not True
    else:
        message = "lacks allowlisted tools" if case == "missing" else "repeated a tools cursor"
        with pytest.raises(ValueError, match=message):
            asyncio.run(mcp_bridge.discover_mcp_tools((configured,)))
    assert cursors == [None, "second-page", "last-page"]
    assert sessions == [configured.url]


def test_mcp_discovery_allowlist_and_failed_write_are_conservative(monkeypatch):
    calls = []

    class FakeClient:
        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="lookup",
                        description="Read a public record",
                        inputSchema={"type": "object", "properties": {}},
                    ),
                    SimpleNamespace(
                        name="change",
                        description="Change a record",
                        inputSchema={"type": "object", "properties": {}},
                    ),
                    SimpleNamespace(
                        name="untrusted",
                        description="Must not be exposed",
                        inputSchema={"type": "object", "properties": {}},
                    ),
                ],
                nextCursor=None,
            )

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            if name == "change":
                raise ConnectionError("may have committed")
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(type="text", text="found")],
                structuredContent=None,
            )

    @asynccontextmanager
    async def session(url):
        assert url == "http://localhost:9001/mcp"
        yield FakeClient()

    monkeypatch.setattr(mcp_bridge, "_session", session)
    configured = AgentMcpServer(
        name="records",
        url="http://localhost:9001/mcp",
        tools=("lookup", "change"),
        read_only_tools=("lookup",),
        write_tools=("change",),
    )
    read, write = asyncio.run(mcp_bridge.discover_mcp_tools((configured,)))
    assert (read.name, write.name) == ("mcp_records_lookup", "mcp_records_change")
    assert read.read_only and not write.read_only
    assert all(
        tool.to_provider_tool()["function"].get("strict") is not True for tool in (read, write)
    )
    assert asyncio.run(read.handler({"id": 1}, ToolExecutionContext()))["content"] == ["found"]
    outcome = asyncio.run(write.handler({"id": 1}, ToolExecutionContext()))
    assert outcome["ok"] is False and outcome["write_state"] == "unknown"
    assert calls == [("lookup", {"id": 1}), ("change", {"id": 1})]


def test_mcp_successful_write_has_no_unverified_commit_receipt(monkeypatch):
    @asynccontextmanager
    async def session(_url):
        class Client:
            async def list_tools(self):
                return SimpleNamespace(
                    tools=[
                        SimpleNamespace(
                            name="send", description="Send", inputSchema={"type": "object"}
                        )
                    ],
                    nextCursor=None,
                )

            async def call_tool(self, _name, arguments):
                return SimpleNamespace(
                    isError=False,
                    content=[SimpleNamespace(type="text", text="sent")],
                    structuredContent=None,
                )

        yield Client()

    monkeypatch.setattr(mcp_bridge, "_session", session)
    server = AgentMcpServer(
        name="mail",
        url="https://example.org/mcp",
        tools=("send",),
        write_tools=("send",),
    )
    tool = asyncio.run(mcp_bridge.discover_mcp_tools((server,)))[0]
    result = asyncio.run(tool.handler({}, ToolExecutionContext()))
    assert result["ok"] is True
    assert result["write_state"] == "unknown"
    assert "operation_receipt" not in result


def test_mcp_config_rejects_unlisted_read_only_and_credentialed_urls():
    with pytest.raises(ValueError):
        AgentMcpServer(name="x", url="https://example.org/mcp", tools=("write",))
    with pytest.raises(ValueError):
        AgentMcpServer(
            name="x",
            url="https://example.org/mcp",
            tools=("write",),
            read_only_tools=("other",),
        )
    with pytest.raises(ValueError):
        AgentMcpServer(
            name="x",
            url="https://user:secret@example.org/mcp",
            tools=("read",),
            read_only_tools=("read",),
        )


def test_mcp_discovery_is_registered_before_agent_accepts_runs(
    settings, client_factory, monkeypatch
):
    from tests.test_runtime import FinalAgentModel
    from tests.test_tool_approval import _wait_for_snapshot_status

    async def handler(arguments, context):
        return {"ok": True}

    async def discover(servers):
        assert len(servers) == 1
        return [
            ToolDefinition(
                name="mcp_catalog_lookup",
                description="Look up a record",
                parameters={"type": "object", "properties": {}},
                handler=handler,
                read_only=True,
            )
        ]

    monkeypatch.setattr("app.agent.runtime.discover_mcp_tools", discover)
    skills = AgentSkillCatalog(
        (
            AgentSkillDefinition(
                name="catalog_lookup",
                instructions="Use the catalog to find records.",
                required_tools=frozenset({"mcp_catalog_lookup"}),
            ),
            AgentSkillDefinition(
                name="unavailable",
                instructions="This tool is not configured.",
                required_tools=frozenset({"mcp_other_lookup"}),
            ),
        )
    )
    monkeypatch.setattr("app.agent.runtime.AgentSkillCatalog", lambda: skills)
    settings.agent_mcp_servers = (
        AgentMcpServer(
            name="catalog",
            url="http://localhost:9001/mcp",
            tools=("lookup",),
            read_only_tools=("lookup",),
        ),
    )
    model = FinalAgentModel()
    with client_factory(model=model) as client:
        runtime = client.app.state.agent_runtime
        assert runtime.tool_catalog.get("mcp_catalog_lookup") is not None
        assert runtime.tool_loader.catalog.get("mcp_catalog_lookup") is not None
        assert client.get("/api/v1/agent/status").status_code == 200
        created = client.post(
            "/api/v1/agent/sessions",
            json={"content": "Find a record"},
            headers={"Idempotency-Key": "mcp-skill-prompt"},
        )
        assert created.status_code == 200
        _wait_for_snapshot_status(client, runtime, created.json()["run"]["id"], "completed")
        prompts = [
            message["content"] for message in model.requests[0] if message["role"] == "system"
        ]
        assert any("Skill catalog_lookup:\nUse the catalog to find records." in p for p in prompts)
        assert all("Skill unavailable:" not in p for p in prompts)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https:///v1/traces",
        "https://",
        "http:///v1/traces",
        "http://example.org/v1/traces",
        "https://user:password@example.org/v1/traces",
        "https://example.org/v1/traces#fragment",
    ],
)
def test_tracing_rejects_invalid_endpoint_before_installing_provider(monkeypatch, endpoint):
    provider = Mock()
    monkeypatch.setattr(telemetry, "TracerProvider", provider)
    monkeypatch.setattr(telemetry, "_tracing_configured", False)
    with pytest.raises(ValueError, match="OTLP tracing requires"):
        telemetry.configure_tracing(endpoint)
    provider.assert_not_called()
    assert telemetry._tracing_configured is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.org/v1/traces",
        "http://localhost:4318/v1/traces",
        "http://127.0.0.1:4318/v1/traces",
    ],
)
def test_tracing_accepts_https_and_local_http_endpoints(monkeypatch, endpoint):
    provider, exporter, processor, install = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(telemetry, "_tracing_configured", False)
    monkeypatch.setattr(telemetry, "TracerProvider", provider)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", exporter)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", processor)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", install)
    telemetry.configure_tracing(endpoint)
    exporter.assert_called_once_with(endpoint=endpoint)
    processor.assert_called_once_with(exporter.return_value)
    provider.return_value.add_span_processor.assert_called_once_with(processor.return_value)
    install.assert_called_once_with(provider.return_value)
    assert telemetry._tracing_configured is True


def test_app_uses_injected_durable_transaction_backend(settings):
    from fastapi.testclient import TestClient

    from app.database import Database
    from tests.test_runtime import FakeAgentEventStream, FinalAgentModel

    db = Database(settings)
    delegate = PostgresDurableBackend(
        db.session_factory,
        context_window_tokens=64000,
        file_input_enabled=True,
        file_max_count=4,
        file_max_total_bytes=16 * 1024 * 1024,
        pdf_max_count=1,
    )

    class Backend:
        calls = 0

        async def transact(self, operation):
            self.calls += 1
            return await delegate.transact(operation)

    backend = Backend()
    app = create_app(
        settings,
        model_client=FinalAgentModel(),
        event_stream=FakeAgentEventStream(),
        durable_backend=backend,
    )
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/agent/sessions",
                json={"content": "Hello"},
                headers={"Idempotency-Key": "backend-injection"},
            )
            assert created.status_code == 200
            for _ in range(100):
                detail = client.get(
                    f"/api/v1/agent/sessions/{created.json()['session']['id']}"
                ).json()
                if any(
                    item.get("run", {}).get("status") == "completed"
                    for item in detail["messages"]
                    if item.get("run")
                ):
                    break
                import time

                time.sleep(0.01)
            else:
                pytest.fail("Agent Run did not complete with injected backend")
            assert backend.calls >= 2
    finally:
        db.close()


def test_eval_runs_a_real_session_and_cleans_up(settings, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.test_runtime import FakeAgentEventStream, FinalAgentModel

    app = create_app(settings, model_client=FinalAgentModel(), event_stream=FakeAgentEventStream())
    monkeypatch.setattr(
        platform_cli.httpx,
        "Client",
        lambda **kwargs: TestClient(app, base_url=kwargs["base_url"], headers=kwargs["headers"]),
    )
    report = platform_cli.evaluate(
        "http://testserver/api/v1",
        {"cases": [{"name": "smoke", "prompt": "hello", "contains": ["已完成"]}]},
        timeout=5,
        keep_sessions=False,
    )
    assert (report["passed"], report["total"]) == (1, 1)
    from sqlalchemy import select

    from app.database import Database
    from app.persistence.models import AgentSession

    database = Database(settings)
    try:
        with database.session_factory() as db:
            assert db.scalars(select(AgentSession)).all() == []
    finally:
        database.close()
