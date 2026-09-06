from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.batching import batch_model_stream_events
from app.agent.context import AgentContextManager
from app.agent.model import (
    CONTEXT_COMPACTION_SYSTEM_PROMPT,
    AgentContextWindowExceededError,
    AgentModelIncompleteError,
    LiteLLMAgentModel,
    ModelStreamEvent,
    extract_reasoning_content,
    normalize_provider_usage,
)
from app.agent.rate_limit import AgentRunRateLimiter, AgentStreamConnectionLimiter
from app.agent.runtime import AgentRuntime
from app.agent.stream import RedisAgentEventStream
from app.agent.tool_executor import AgentToolExecutor
from app.agent.tools import (
    AgentToolCatalog,
    RuntimeToolCall,
    RuntimeToolOutcome,
    ToolDefinition,
    ToolExecutionContext,
    build_ask_user_tool,
    build_default_tool_catalog,
)
from app.persistence.agent_runtime import AgentRepository, normalize_ask_user_arguments
from app.persistence.errors import DomainError
from app.persistence.scope import Identity


class FakeAgentModel:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, Any]]] = []

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append([dict(message) for message in messages])
        if messages[-1]["role"] == "tool":
            yield ModelStreamEvent(kind="reasoning", content="回答后排除 B。")
            yield ModelStreamEvent(
                kind="content",
                content="\n\n## 建议\n\n继续推进。",
            )
            yield ModelStreamEvent(
                kind="usage",
                payload={"completion_tokens": 18, "reasoning_tokens": 7},
            )
            return
        yield ModelStreamEvent(kind="reasoning", content="我先分析 A，再排除 B。")
        yield ModelStreamEvent(kind="content", content="需要确认前置条件。")
        yield ModelStreamEvent(
            kind="usage",
            payload={"completion_tokens": 11, "reasoning_tokens": 5},
        )
        yield ModelStreamEvent(
            kind="tool_calls",
            tool_calls=[
                {
                    "id": "call-question-1",
                    "name": "ask_user",
                    "arguments": (
                        '{"query":"候选人是否进入面试？","options":['
                        '{"content":"进入","description":"安排首轮面试"},'
                        '{"content":"暂缓","description":"继续收集信息"}]}'
                    ),
                }
            ],
        )


class FakeAgentEventStream:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def ping(self) -> None:
        return None

    async def publish(self, _run_id: str, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def read(
        self, _run_id: str, cursor: str, *, block_ms: int = 1_000
    ) -> tuple[str, list[dict[str, Any]]]:
        await asyncio.sleep(min(block_ms / 1_000, 0.01))
        return cursor, []

    async def close(self) -> None:
        return None


class MixedToolAgentModel:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, Any]]] = []

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append([dict(message) for message in messages])
        if any(
            message.get("role") == "tool"
            and "ExclusiveToolBatch" in str(message.get("content") or "")
            for message in messages
        ):
            yield ModelStreamEvent(kind="content", content="已按独占规则调整。")
            return
        yield ModelStreamEvent(
            kind="tool_calls",
            tool_calls=[
                {"id": "call-list", "name": "list_subagents", "arguments": "{}"},
                {
                    "id": "call-search",
                    "name": "mock_web_search",
                    "arguments": '{"query":"测试工具","max_results":1}',
                },
            ],
        )


class InterruptedAgentModel:
    async def stream(self, _messages: list[dict[str, Any]]) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(kind="reasoning", content="尚未形成安全边界")
        yield ModelStreamEvent(kind="content", content="不应保留的半段")
        await asyncio.Event().wait()


class FailingAgentEventStream(FakeAgentEventStream):
    async def publish(self, _run_id: str, _event: dict[str, Any]) -> None:
        raise ConnectionError("Redis unavailable")


class FailingAgentModel:
    async def stream(self, _messages: list[dict[str, Any]]) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(kind="content", content="尚未完成的草稿")
        raise RuntimeError("provider failed")


class TruncatedAgentModel:
    async def stream(self, _messages: list[dict[str, Any]]) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(kind="content", content="被截断的草稿")
        raise AgentModelIncompleteError("deepseek", "length")


class RejectingAgentRunRateLimiter:
    async def require(self, _identity: Identity) -> None:
        raise AssertionError("idempotent replay must bypass Run admission")


class RecordingAgentRunRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def require(self, _identity: Identity) -> None:
        self.calls += 1


class RecordingPipeline:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.executed = False

    async def __aenter__(self) -> RecordingPipeline:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    def xadd(self, *args: Any, **kwargs: Any) -> RecordingPipeline:
        self.commands.append(("xadd", args, kwargs))
        return self

    def expire(self, *args: Any, **kwargs: Any) -> RecordingPipeline:
        self.commands.append(("expire", args, kwargs))
        return self

    async def execute(self) -> None:
        self.executed = True


class RecordingRedis:
    def __init__(self) -> None:
        self.transaction: bool | None = None
        self.recording_pipeline = RecordingPipeline()

    def pipeline(self, *, transaction: bool) -> RecordingPipeline:
        self.transaction = transaction
        return self.recording_pipeline


def test_agent_run_rate_limit_is_scoped_to_user_and_tenant() -> None:
    first = Identity(
        user_id="user-1",
        tenant_id="tenant-1",
        membership_id="membership-1",
    )
    second = Identity(
        user_id="user-2",
        tenant_id="tenant-1",
        membership_id="membership-2",
    )

    async def run() -> None:
        user_limiter = AgentRunRateLimiter(
            redis_url=None,
            environment="test",
            user_runs_per_minute=1,
            tenant_runs_per_minute=10,
        )
        await user_limiter.require(first)
        with pytest.raises(DomainError, match="Agent Run request limit exceeded") as user_error:
            await user_limiter.require(first)
        assert user_error.value.code == "agent_run_rate_limited"
        assert user_error.value.details["scope"] == "user"

        tenant_limiter = AgentRunRateLimiter(
            redis_url=None,
            environment="test",
            user_runs_per_minute=10,
            tenant_runs_per_minute=1,
        )
        await tenant_limiter.require(first)
        with pytest.raises(DomainError, match="Agent Run request limit exceeded") as tenant_error:
            await tenant_limiter.require(second)
        assert tenant_error.value.details["scope"] == "tenant"
        await user_limiter.aclose()
        await tenant_limiter.aclose()

    asyncio.run(run())


def test_agent_stream_connection_limit_releases_identity_and_run_slots() -> None:
    identity = Identity(
        user_id="user-1",
        tenant_id="tenant-1",
        membership_id="membership-1",
    )

    async def run() -> None:
        limiter = AgentStreamConnectionLimiter(identity_limit=2, run_limit=1)
        first = await limiter.acquire(identity, "run-1")
        with pytest.raises(DomainError) as run_error:
            await limiter.acquire(identity, "run-1")
        assert run_error.value.code == "agent_stream_connection_limited"
        assert run_error.value.details["scope"] == "run"

        second = await limiter.acquire(identity, "run-2")
        with pytest.raises(DomainError) as identity_error:
            await limiter.acquire(identity, "run-3")
        assert identity_error.value.details["scope"] == "identity"

        await first.release()
        replacement = await limiter.acquire(identity, "run-3")
        await first.release()
        await second.release()
        await replacement.release()

    asyncio.run(run())


def test_agent_stream_publishes_event_and_ttl_in_one_redis_transaction() -> None:
    redis = RecordingRedis()
    stream = RedisAgentEventStream.__new__(RedisAgentEventStream)
    stream.redis = redis  # type: ignore[assignment]
    stream.max_events = 100
    stream.active_ttl_seconds = 3_600
    stream.terminal_ttl_seconds = 600

    asyncio.run(stream.publish("run-1", {"event": "done", "data": {"ok": True}}))

    assert redis.transaction is True
    assert redis.recording_pipeline.executed is True
    assert [command[0] for command in redis.recording_pipeline.commands] == ["xadd", "expire"]
    assert redis.recording_pipeline.commands[1][1] == ("cornagent:agent:run:run-1:events", 600)


def test_raw_chunk_markers_do_not_split_text_batches() -> None:
    async def source() -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(kind="raw")
        yield ModelStreamEvent(kind="content", content="A")
        yield ModelStreamEvent(kind="raw")
        yield ModelStreamEvent(kind="content", content="B")
        yield ModelStreamEvent(kind="raw")
        yield ModelStreamEvent(kind="content", content="C")

    async def collect() -> list[ModelStreamEvent]:
        return [
            event
            async for event in batch_model_stream_events(
                source(),
                window_ms=32,
                max_bytes=4_096,
            )
        ]

    events = asyncio.run(collect())

    assert [event.kind for event in events] == ["raw", "content", "raw", "raw", "content"]
    assert events[-1].content == "BC"


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "", "options": [{"content": "A", "description": "a"}]},
        {"query": "Q", "options": []},
        {
            "query": "Q",
            "options": [{"content": str(index), "description": "x"} for index in range(7)],
        },
        {"query": "Q", "options": [{"content": "A", "description": "a", "id": "x"}]},
    ],
)
def test_ask_user_schema_rejects_invalid_arguments(arguments: dict[str, Any]) -> None:
    with pytest.raises(DomainError) as error:
        normalize_ask_user_arguments(arguments)
    assert error.value.code == "invalid_ask_user"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"reasoning_content": "逐步分析"}, "逐步分析"),
        ({"reasoning": "排除错误路径"}, "排除错误路径"),
        ({"thinking": "检查约束"}, "检查约束"),
        ({"content_parts": [{"type": "reasoning", "text": "来自 part"}]}, "来自 part"),
        ({"content": "普通答案"}, ""),
    ],
)
def test_provider_reasoning_is_preserved_without_fabrication(
    payload: dict[str, Any], expected: str
) -> None:
    assert extract_reasoning_content(payload) == expected


@pytest.mark.parametrize(
    ("finish_reason", "expected_error_reason"),
    [("length", "length"), (None, "missing_finish_reason")],
)
def test_model_adapter_rejects_truncated_or_unterminated_stream(
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str | None,
    expected_error_reason: str,
) -> None:
    async def chunks() -> AsyncIterator[dict[str, Any]]:
        yield {"choices": [{"delta": {"content": "被截断的草稿"}, "finish_reason": None}]}
        yield {"choices": [{"delta": {}, "finish_reason": finish_reason}]}

    async def completion(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        return chunks()

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    model = LiteLLMAgentModel(model="fake", api_key="test-key")

    async def collect() -> list[ModelStreamEvent]:
        return [event async for event in model.stream([{"role": "user", "content": "继续"}])]

    with pytest.raises(AgentModelIncompleteError) as error:
        asyncio.run(collect())
    assert error.value.provider == "primary"
    assert error.value.finish_reason == expected_error_reason


def test_model_adapter_does_not_expose_provider_response_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def chunks() -> AsyncIterator[dict[str, Any]]:
        yield {
            "id": "provider-response-1",
            "model": "provider-model",
            "system_fingerprint": "provider-fingerprint",
            "choices": [{"delta": {"content": "完成"}, "finish_reason": "stop"}],
        }

    async def completion(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        return chunks()

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    model = LiteLLMAgentModel(model="fake", api_key="test-key")

    async def collect() -> list[ModelStreamEvent]:
        return [event async for event in model.stream([{"role": "user", "content": "继续"}])]

    events = asyncio.run(collect())

    assert [event.kind for event in events] == ["raw", "content"]


def test_multimodal_503_does_not_fall_back_to_text_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class ProviderUnavailable(RuntimeError):
        status_code = 503

    async def completion(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        calls.append(kwargs)
        raise ProviderUnavailable("temporarily unavailable")

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    model = LiteLLMAgentModel(
        model="vision-primary",
        api_key="primary-key",
        api_base="https://api.deepseek.com",
        max_retries=0,
        fallback_model="text-fallback",
        fallback_api_key="fallback-key",
        fallback_api_base="https://fallback.example.test/v1",
        fallback_supports_images=False,
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "分析图片"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AA==", "detail": "auto"},
                },
            ],
        }
    ]

    async def collect() -> list[ModelStreamEvent]:
        return [event async for event in model.stream(messages)]

    with pytest.raises(ProviderUnavailable):
        asyncio.run(collect())
    assert len(calls) == 1
    assert calls[0]["model"].endswith("/vision-primary")


def test_context_compaction_uses_a_dedicated_json_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    async def completion(**kwargs: Any) -> dict[str, Any]:
        requests.append(kwargs)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"summary":"保留历史事实"}'},
                }
            ]
        }

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    model = LiteLLMAgentModel(model="fake", api_key="test-key")

    result = asyncio.run(model.compact([{"role": "user", "content": "历史消息"}], max_tokens=256))

    assert result == '{"summary":"保留历史事实"}'
    assert requests[0]["messages"][0] == {
        "role": "system",
        "content": CONTEXT_COMPACTION_SYSTEM_PROMPT,
    }
    assert "tools" not in requests[0]
    assert requests[0]["stream"] is False


def test_context_compaction_projects_private_files_to_text_only() -> None:
    observed: list[list[dict[str, Any]]] = []

    class RecordingCompactor:
        async def compact(
            self,
            messages: list[dict[str, Any]],
            *,
            max_tokens: int,
        ) -> dict[str, Any]:
            del max_tokens
            observed.append(messages)
            return {"summary": "已保留图片存在性"}

    manager = AgentContextManager(RecordingCompactor())  # type: ignore[arg-type]
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "历史图像"},
                {
                    "type": "cintel_file_ref",
                    "file_id": "file-private",
                    "filename": "候选人.png",
                    "mime_type": "image/png",
                },
            ],
        },
        *({"role": "assistant", "content": f"history-{index}"} for index in range(4)),
    ]

    compacted, _ = asyncio.run(
        manager.fit(
            messages,
            {},
            tool_context_state={},
            trigger="test",
            force=True,
        )
    )

    assert observed
    serialized = json.dumps(observed, ensure_ascii=False)
    assert "[历史文件：候选人.png]" in serialized
    assert "cintel_file_ref" not in serialized
    assert "file-private" not in serialized
    assert compacted[0]["role"] == "system"


def test_provider_overflow_compaction_retains_private_tool_evidence_references() -> None:
    observed: list[list[dict[str, Any]]] = []

    class RecordingCompactor:
        async def compact(
            self,
            messages: list[dict[str, Any]],
            *,
            max_tokens: int,
        ) -> dict[str, Any]:
            del max_tokens
            observed.append(messages)
            return {"summary": "已压缩非私有历史"}

    private_reference = json.dumps(
        {
            "type": "cintel_private_tool_result_ref",
            "tool_name": "read_file",
            "arguments": {"file_id": "file-private", "offset": 0, "limit": 20_000},
        },
        separators=(",", ":"),
    )
    private_unit = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-read-page-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"file_id":"file-private","offset":0,"limit":20000}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-read-page-1",
            "name": "read_file",
            "content": private_reference,
        },
    ]
    manager = AgentContextManager(RecordingCompactor())  # type: ignore[arg-type]
    messages = [
        {"role": "user", "content": "需要压缩的普通历史" * 2_000},
        *private_unit,
        *({"role": "assistant", "content": f"tail-{index}"} for index in range(4)),
    ]

    compacted, metadata = asyncio.run(
        manager.fit(
            messages,
            {},
            tool_context_state={},
            trigger="provider_overflow",
            force=True,
        )
    )

    assert metadata is not None
    assert observed
    assert "cintel_private_tool_result_ref" not in json.dumps(observed, ensure_ascii=False)
    assert compacted[1:3] == private_unit


@pytest.mark.parametrize(
    ("finish_reason", "expected_error_reason"),
    [("length", "length"), (None, "missing_finish_reason")],
)
def test_context_compaction_rejects_truncated_or_unterminated_response(
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str | None,
    expected_error_reason: str,
) -> None:
    async def completion(**_kwargs: Any) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": '{"summary":"可能已截断"}'},
                }
            ]
        }

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    model = LiteLLMAgentModel(model="fake", api_key="test-key")

    with pytest.raises(AgentModelIncompleteError) as error:
        asyncio.run(model.compact([{"role": "user", "content": "历史消息"}], max_tokens=256))
    assert error.value.finish_reason == expected_error_reason


def test_context_compaction_normalizes_provider_window_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProviderContextError(RuntimeError):
        status_code = 400

    async def completion(**_kwargs: Any) -> dict[str, Any]:
        raise ProviderContextError("maximum context window exceeded")

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    model = LiteLLMAgentModel(model="fake", api_key="test-key")

    with pytest.raises(AgentContextWindowExceededError) as error:
        asyncio.run(model.compact([{"role": "user", "content": "超长历史"}], max_tokens=256))
    assert error.value.provider == "primary"


def test_context_compaction_recursively_splits_provider_overflow() -> None:
    attempted_sizes: list[int] = []
    successful_sizes: list[int] = []

    class WindowedCompactor:
        async def compact(
            self,
            messages: list[dict[str, Any]],
            *,
            max_tokens: int,
        ) -> dict[str, Any]:
            size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
            attempted_sizes.append(size)
            if size > 1_500:
                raise AgentContextWindowExceededError("primary")
            successful_sizes.append(size)
            return {"summary": f"保留 {len(messages)} 条历史，预算 {max_tokens}"}

    manager = AgentContextManager(WindowedCompactor())  # type: ignore[arg-type]
    messages = [{"role": "user", "content": f"历史 {index}: " + "x" * 420} for index in range(12)]
    compacted, metadata = asyncio.run(
        manager.fit(
            messages,
            {},
            tool_context_state={},
            trigger="provider_overflow",
            force=True,
        )
    )

    assert attempted_sizes[0] > 1_500
    assert successful_sizes and max(successful_sizes) <= 1_500
    assert len(compacted) == 5
    assert compacted[0]["role"] == "system"
    assert metadata is not None and metadata["passes"] == 1


def test_context_compaction_splits_one_oversized_history_unit() -> None:
    successful_sizes: list[int] = []

    class WindowedCompactor:
        async def compact(
            self,
            messages: list[dict[str, Any]],
            *,
            max_tokens: int,
        ) -> dict[str, Any]:
            del max_tokens
            size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
            if size > 1_200:
                raise AgentContextWindowExceededError("primary")
            successful_sizes.append(size)
            return {"summary": f"fragment-{len(successful_sizes)}"}

    manager = AgentContextManager(WindowedCompactor())  # type: ignore[arg-type]
    messages = [
        {"role": "user", "content": "x" * 5_000},
        *({"role": "user", "content": f"tail-{index}"} for index in range(4)),
    ]
    compacted, metadata = asyncio.run(
        manager.fit(
            messages,
            {},
            tool_context_state={},
            trigger="provider_overflow",
            force=True,
        )
    )

    assert successful_sizes and max(successful_sizes) <= 1_200
    assert len(compacted) == 5
    assert metadata is not None and metadata["passes"] == 1


def test_reasoning_usage_and_ask_user_tool_contract() -> None:
    usage = normalize_provider_usage(
        {
            "completion_tokens": 20,
            "completion_tokens_details": {"reasoning_tokens": 9},
        }
    )
    assert usage["reasoning_tokens"] == 9
    parameters = build_ask_user_tool().to_provider_tool()["function"]["parameters"]
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["options"]["minItems"] == 1
    assert parameters["properties"]["options"]["maxItems"] == 6


def test_generic_ask_user_executor_fails_closed() -> None:
    executor = AgentToolExecutor(build_default_tool_catalog())
    result = asyncio.run(executor.execute_tool("ask_user", {"query": "Q", "options": []}))
    assert result["ok"] is False
    assert result["error"]["type"] == "AskUserToolPaused"


def test_tool_catalog_accepts_injected_tools_without_executor_changes() -> None:
    async def custom_handler(
        arguments: dict[str, Any],
        _context: ToolExecutionContext,
    ) -> dict[str, Any]:
        return {"ok": True, "value": arguments["value"]}

    custom_tool = ToolDefinition(
        name="future_action",
        description="A future configurable action.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler=custom_handler,
    )
    catalog = build_default_tool_catalog([custom_tool])
    executor = AgentToolExecutor(catalog)

    assert catalog.names() == ("ask_user", "future_action")
    assert [item["function"]["name"] for item in catalog.provider_tools()] == [
        "ask_user",
        "future_action",
    ]
    assert asyncio.run(executor.execute_tool("future_action", {"value": "done"})) == {
        "ok": True,
        "value": "done",
    }
    with pytest.raises(ValueError, match="already registered"):
        catalog.register(custom_tool)


def test_runtime_tool_dispatch_uses_registered_handler_metadata() -> None:
    dispatched: list[RuntimeToolCall] = []

    async def executor_handler(
        _arguments: dict[str, Any],
        _context: ToolExecutionContext,
    ) -> dict[str, Any]:
        return {"ok": False}

    async def runtime_handler(call: RuntimeToolCall) -> RuntimeToolOutcome:
        dispatched.append(call)
        return RuntimeToolOutcome("waiting_for_user")

    tool = ToolDefinition(
        name="future_runtime_action",
        description="A future durable runtime action.",
        parameters={"type": "object", "additionalProperties": False},
        handler=executor_handler,
        runtime_handler="future_runtime_handler",
        exclusive=True,
    )
    runtime = AgentRuntime(
        session_factory=lambda: None,  # type: ignore[arg-type,return-value]
        redis_url=None,
        model="fake",
        api_key="test-key",
        api_base=None,
        model_timeout_seconds=30,
        reconcile_seconds=60,
        stream_max_events=100,
        tool_catalog=AgentToolCatalog([tool]),
        runtime_tool_handlers={"future_runtime_handler": runtime_handler},
        model_client=FinalAgentModel(),
        event_stream=FakeAgentEventStream(),
    )

    outcome = asyncio.run(
        runtime._handle_tool_calls(
            run_id="run-1",
            fence=3,
            provider_messages=[{"role": "user", "content": "go"}],
            round_content="process",
            round_reasoning="reasoning",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "future_runtime_action",
                    "arguments": "{}",
                }
            ],
            usage={"completion_tokens": 1},
        )
    )

    assert len(dispatched) == 1
    assert outcome == RuntimeToolOutcome("waiting_for_user")
    assert dispatched[0].definition is tool
    assert dispatched[0].tool_call_id == "call-1"
    assert dispatched[0].arguments == {}


def test_version_leaf_resolution_indexes_messages_once() -> None:
    class CountingMessages:
        def __init__(self, messages: list[Any]) -> None:
            self.messages = messages
            self.visits = 0

        def __iter__(self) -> Iterator[Any]:
            for message in self.messages:
                self.visits += 1
                yield message

    created_at = datetime(2026, 9, 2, tzinfo=UTC)
    messages = [
        SimpleNamespace(
            id=f"message-{index}",
            parent_message_id=f"message-{index - 1}" if index else None,
            created_at=created_at + timedelta(seconds=index),
        )
        for index in range(10_000)
    ]
    counted = CountingMessages(messages)

    leaf = AgentRepository._latest_descendant_leaf(counted, "message-0")

    assert leaf.id == "message-9999"
    assert counted.visits == len(messages)


def test_runtime_tool_configuration_fails_fast_for_missing_handler() -> None:
    async def executor_handler(
        _arguments: dict[str, Any],
        _context: ToolExecutionContext,
    ) -> dict[str, Any]:
        return {"ok": False}

    tool = ToolDefinition(
        name="misconfigured_runtime_action",
        description="A tool with a missing runtime handler.",
        parameters={"type": "object", "additionalProperties": False},
        handler=executor_handler,
        runtime_handler="missing_handler",
    )

    with pytest.raises(ValueError, match="missing_handler"):
        AgentRuntime(
            session_factory=lambda: None,  # type: ignore[arg-type,return-value]
            redis_url=None,
            model="fake",
            api_key="test-key",
            api_base=None,
            model_timeout_seconds=30,
            reconcile_seconds=60,
            stream_max_events=100,
            tool_catalog=AgentToolCatalog([tool]),
            model_client=FinalAgentModel(),
            event_stream=FakeAgentEventStream(),
        )


class FinalAgentModel:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, Any]]] = []

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append([dict(message) for message in messages])
        yield ModelStreamEvent(kind="content", content="已完成。")
