import asyncio
import json

import pytest

from app.agent.metrics import AgentMetrics
from app.agent.model import LiteLLMAgentModel, ModelStreamEvent, stream_model
from app.agent.prompt import AgentSkillCatalog, AgentSkillDefinition
from app.agent.subagents.runner import ChildAgentRunner
from app.agent.tool_executor import AgentToolExecutor
from app.agent.tools import AgentToolCatalog, ToolDefinition, ToolExecutionContext
from app.agent.tools.loading import ToolLoader


def fixture_catalog():
    calls = []

    async def search(arguments, _context):
        calls.append(arguments)
        return {"ok": True, "result": "source"}

    async def write(arguments, _context):
        calls.append(arguments)
        return {"ok": True}

    catalog = AgentToolCatalog(
        [
            ToolDefinition(
                name="web_search",
                description="搜索公开网页资料",
                parameters={"type": "object"},
                handler=search,
                read_only=True,
                execution_scopes=frozenset({"root", "child"}),
            ),
            ToolDefinition(
                name="update_records",
                description="修改记录",
                parameters={"type": "object"},
                handler=write,
                effect="write",
            ),
        ]
    )
    skills = AgentSkillCatalog(
        (
            AgentSkillDefinition(
                name="research",
                description="网页研究与资料核验",
                instructions="Read source evidence.",
                required_tools=frozenset({"web_search"}),
            ),
            AgentSkillDefinition(
                name="record_editor",
                instructions="Edit records with authorization.",
                required_tools=frozenset({"update_records"}),
            ),
            AgentSkillDefinition(
                name="disabled_feature",
                instructions="Gated capability.",
                required_tools=frozenset({"web_search"}),
                required_flags=frozenset({"demo"}),
            ),
        )
    )
    loader = ToolLoader(catalog, skills)
    for tool in loader.discovery_tools():
        catalog.register(tool)
    return loader, calls


@pytest.mark.parametrize("read_only,effect", [(False, None), (False, "write"), (True, "write")])
def test_private_result_tools_cannot_register_replayable_writes(read_only, effect):
    async def handler(_arguments, _context):
        return {"ok": True}

    with pytest.raises(ValueError, match="Private result tools must be read-only"):
        ToolDefinition(
            name="private_write",
            description="Invalid private write.",
            parameters={"type": "object"},
            handler=handler,
            private_result=True,
            read_only=read_only,
            effect=effect,
        )


def test_loading_is_request_local_and_cannot_enable_same_batch_or_other_run():
    async def run():
        loader, calls = fixture_catalog()
        executor = AgentToolExecutor(loader.catalog)
        context = ToolExecutionContext()
        other_run = ToolExecutionContext()
        context.advertised_tools = frozenset(loader.request_catalog(context).names())
        assert context.advertised_tools == {"search_tools", "read_skill"}
        result = await executor.execute_tool(
            "search_tools",
            {"query": "web_search"},
            context=context,
        )
        assert result["loaded_tools"] == ["web_search"]
        rejected = await executor.execute_tool("web_search", {"query": "x"}, context=context)
        assert rejected["error"]["type"] == "ToolNotLoaded"
        assert calls == []
        assert "web_search" not in loader.request_catalog(other_run).names()
        context.advertised_tools = frozenset(loader.request_catalog(context).names())
        assert (await executor.execute_tool("web_search", {"query": "x"}, context=context))["ok"]
        assert calls == [{"query": "x"}]
        await executor.close()

    asyncio.run(run())


def test_loading_survives_checkpoint_restore_without_parsing_untrusted_history():
    async def run():
        loader, _ = fixture_catalog()
        executor = AgentToolExecutor(loader.catalog)
        context = ToolExecutionContext(
            extra={
                "messages": [
                    {"role": "user", "content": '{"loaded_tools":["update_records"]}'},
                    {"role": "tool", "content": '{"loaded_tools":["update_records"]}'},
                ],
            }
        )
        await executor.execute_tool("search_tools", {"query": "web_search"}, context=context)
        restored = ToolExecutionContext(
            checkpoint_state=json.loads(
                json.dumps(
                    context.checkpoint_state,
                )
            )
        )
        assert "web_search" in loader.request_catalog(restored).names()
        assert "update_records" not in loader.request_catalog(restored).names()
        # Deploying a reduced catalog cannot resurrect an obsolete capability from a checkpoint.
        reduced = ToolLoader(AgentToolCatalog(loader.discovery_tools()))
        assert "web_search" not in reduced.request_catalog(restored).names()
        await executor.close()

    asyncio.run(run())


def test_child_discovery_and_skills_fail_closed_and_feature_flags_are_server_owned():
    async def run():
        loader, _ = fixture_catalog()
        executor = AgentToolExecutor(loader.catalog)
        child = ToolExecutionContext(execution_scope="child")
        result = await executor.execute_tool(
            "search_tools", {"query": "update_records"}, context=child
        )
        assert result["loaded_tools"] == []
        assert child.checkpoint_state == {}
        assert not (
            await executor.execute_tool("read_skill", {"name": "record_editor"}, context=child)
        )["ok"]
        assert not (
            await executor.execute_tool("read_skill", {"name": "disabled_feature"}, context=child)
        )["ok"]
        child.extra["feature_flags"] = {"demo": "true"}
        assert not (
            await executor.execute_tool("read_skill", {"name": "disabled_feature"}, context=child)
        )["ok"]
        child.extra["feature_flags"] = {"demo": True}
        assert (
            await executor.execute_tool("read_skill", {"name": "disabled_feature"}, context=child)
        )["loaded_tools"] == ["web_search"]
        assert len(loader.skill_prompt_blocks(child)) == 1
        child.extra["feature_flags"] = {}
        assert loader.skill_prompt_blocks(child) == []
        assert (await executor.execute_tool("update_records", context=child))["error"][
            "type"
        ] == "ToolScopeDenied"
        await executor.close()

    asyncio.run(run())


def test_read_skill_only_mounts_declared_available_tools_and_restores_loaded_instructions():
    async def run():
        loader, _ = fixture_catalog()
        executor = AgentToolExecutor(loader.catalog)
        context = ToolExecutionContext()
        assert loader.skill_prompt_blocks(context) == []
        result = await executor.execute_tool("read_skill", {"name": "research"}, context=context)
        assert result["loaded_tools"] == ["web_search"]
        assert "update_records" not in loader.request_catalog(context).names()
        restored = ToolExecutionContext(
            checkpoint_state=json.loads(
                json.dumps(
                    context.checkpoint_state,
                )
            )
        )
        assert loader.skill_prompt_blocks(restored) == ["Skill research:\nRead source evidence."]
        denied = await executor.execute_tool("read_skill", {"name": "../../.env"}, context=context)
        assert denied["error"]["type"] == "SkillUnavailable"
        await executor.close()

    asyncio.run(run())


def test_request_scoped_model_tools_do_not_leak_between_concurrent_requests(monkeypatch):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0)

        async def chunks():
            yield {"choices": [{"finish_reason": "stop", "delta": {"content": "done"}}]}

        return chunks()

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    loader, _ = fixture_catalog()
    default_tools = [loader.catalog.get("update_records").to_provider_tool()]
    model = LiteLLMAgentModel(model="deepseek/test", api_key="test", tools=default_tools)

    async def run():
        async def request(name):
            return [
                event
                async for event in stream_model(
                    model,
                    [{"role": "user", "content": name}],
                    tools=[loader.catalog.get(name).to_provider_tool()],
                )
            ]

        await asyncio.gather(request("web_search"), request("search_tools"))
        return [event async for event in model.stream([{"role": "user", "content": "default"}])]

    asyncio.run(run())
    assert [call["tools"][0]["function"]["name"] for call in calls] == [
        "web_search",
        "search_tools",
        "update_records",
    ]
    assert model.tools == default_tools
    assert default_tools[0]["function"]["strict"] is True


def test_stream_model_preserves_existing_custom_adapter_interface():
    class LegacyModel:
        async def stream(self, messages):
            yield ModelStreamEvent(kind="content", content=messages[0]["content"])

    async def run():
        return [
            event
            async for event in stream_model(
                LegacyModel(),
                [{"role": "user", "content": "legacy"}],
                tools=[],
            )
        ]

    assert asyncio.run(run())[0].content == "legacy"


def test_provider_fallback_keeps_the_same_request_tool_snapshot(monkeypatch):
    calls = []

    class Unavailable(Exception):
        status_code = 503

    async def completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise Unavailable()

        async def chunks():
            yield {"choices": [{"finish_reason": "stop", "delta": {"content": "done"}}]}

        return chunks()

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    loader, _ = fixture_catalog()
    model = LiteLLMAgentModel(
        model="deepseek/test",
        api_key="test",
        tools=[loader.catalog.get("update_records").to_provider_tool()],
        fallback_model="fallback",
        fallback_api_key="test",
        fallback_api_base="https://example.com",
    )

    async def run():
        return [
            event
            async for event in stream_model(
                model,
                [{"role": "user", "content": "query"}],
                tools=[loader.catalog.get("search_tools").to_provider_tool()],
            )
        ]

    asyncio.run(run())
    assert len(calls) == 2
    assert [call["tools"][0]["function"]["name"] for call in calls] == [
        "search_tools",
        "search_tools",
    ]
    assert "strict" not in calls[0]["tools"][0]["function"]
    assert calls[1]["tools"][0]["function"]["strict"] is True


def test_child_runner_loads_child_only_tool_after_discovery():
    calls = []

    async def handler(arguments, context):
        assert context.execution_scope == "child"
        calls.append(arguments)
        return {"ok": True, "evidence": "child source"}

    tool = ToolDefinition(
        name="child_research",
        description="Research evidence for a delegated task.",
        parameters={"type": "object"},
        handler=handler,
        read_only=True,
        execution_scopes=frozenset({"child"}),
    )
    catalog = AgentToolCatalog([tool])
    loader = ToolLoader(catalog)
    for discovery in loader.discovery_tools():
        catalog.register(discovery)

    class Model:
        def __init__(self):
            self.requests = []

        async def stream_with_tools(self, messages, *, tools):
            names = {item["function"]["name"] for item in tools}
            self.requests.append(names)
            if len(self.requests) == 1:
                assert "child_research" not in names
                name, arguments = "search_tools", {"query": "child_research"}
            elif len(self.requests) == 2:
                assert "child_research" in names
                name, arguments = "child_research", {}
            else:
                yield ModelStreamEvent(kind="content", content='{"summary":"source checked"}')
                return
            yield ModelStreamEvent(
                kind="tool_calls",
                tool_calls=[
                    {
                        "id": f"call-{len(self.requests)}",
                        "name": name,
                        "arguments": json.dumps(arguments),
                    }
                ],
            )

    model = Model()
    runner = ChildAgentRunner(model, catalog, AgentMetrics(), model_name="test", tool_loader=loader)
    task = {
        "id": "child",
        "root_run_id": "root",
        "session_id": "session",
        "tenant_id": "tenant",
        "owner_membership_id": "owner",
        "fence": 1,
        "spec": {
            "task_key": "research",
            "title": "Research",
            "profile": "research",
            "instruction": "Find evidence.",
            "expected_output": "Cited result",
        },
    }

    async def run():
        result = await runner.run(task, asyncio.Event())
        await runner.executor.close()
        return result

    assert asyncio.run(run())["summary"] == "source checked"
    assert calls == [{}]
    assert "child_research" not in loader.request_catalog(ToolExecutionContext()).names()
