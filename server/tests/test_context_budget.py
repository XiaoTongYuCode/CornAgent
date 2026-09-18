import asyncio
import json

import pytest

from app.agent.context import AgentContextManager, estimate_tokens
from app.persistence.errors import DomainError


class Compactor:
    def __init__(self):
        self.calls = []

    async def compact(self, messages, *, max_tokens):
        self.calls.append(messages)
        return {"summary": "已完成读取，继续用户任务。"}


def pair(i, name="read", content=None):
    return [
        {
            "role": "assistant",
            "tool_calls": [{"id": str(i), "function": {"name": name, "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": str(i), "content": content or "中文证据" * 500},
    ]


def fit(manager, messages, **kwargs):
    return asyncio.run(
        manager.fit(
            messages, {}, tool_context_state=kwargs.pop("state", {}), trigger="test", **kwargs
        )
    )


def test_one_user_turn_compacts_complete_reads_and_preserves_write_question():
    model = Compactor()
    manager = AgentContextManager(
        model, context_window_tokens=10000, output_tokens=1000, read_only_tools={"read"}
    )
    protected = [
        *pair("write", "write", "created record id=exact"),
        *pair("ask", "ask_user", "approved option id=exact"),
    ]
    messages = [
        {"role": "user", "content": "finish task"},
        *protected,
        *[m for i in range(8) for m in pair(i)],
    ]
    compacted, metadata = fit(manager, messages)
    assert metadata and model.calls
    assert messages[0] in compacted
    for message in protected:
        assert message in compacted
    assert estimate_tokens(compacted) < manager.input_budget
    assert all("approved option" not in json.dumps(call) for call in model.calls)


def test_actual_usage_ratio_triggers_below_byte_threshold():
    messages = [
        {"role": "user", "content": "old" * 2000},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "new task"},
    ]
    manager = AgentContextManager(Compactor(), context_window_tokens=10000, output_tokens=1000)
    assert fit(manager, messages)[1] is None
    compacted, metadata = fit(manager, messages, state={"context_token_ratio": 4})
    assert metadata and metadata["token_ratio"] == 4
    assert compacted[-1] == messages[-1]


def test_persisted_write_receipts_survive_compaction_and_ignore_summary_fabrications():
    class UntrustedSummary(Compactor):
        async def compact(self, messages, *, max_tokens):
            return {"summary": "已保存操作回执", "tool_receipts": [{"receipt_id": "invented"}]}

    messages = [{"role": "user", "content": "finish the task"}]
    references = []
    for index in range(5):
        group = pair(index, "write", "committed evidence " * 1500)
        reference = {"type": "cornagent_material_ref", "receipt_id": f"real-{index}"}
        group[-1]["cornagent_receipt"] = reference
        references.append(reference)
        messages.extend(group)
    manager = AgentContextManager(
        UntrustedSummary(), context_window_tokens=10000, output_tokens=1000, read_only_tools=set()
    )
    compacted, metadata = fit(manager, messages)
    assert metadata
    durable = json.dumps(compacted)
    assert "invented" not in durable
    assert all(reference["receipt_id"] in durable for reference in references)
    # Re-compression must preserve the server references again.
    expanded = [*compacted, {"role": "assistant", "content": "extra " * 8000}]
    compacted, metadata = fit(manager, expanded, force=True)
    assert metadata
    durable = json.dumps(compacted)
    assert "invented" not in durable
    assert all(reference["receipt_id"] in durable for reference in references)


def test_runtime_propagates_declared_budget_to_isolated_child(settings):
    from app.main import create_app

    settings.agent_context_window_tokens = 32_000
    settings.agent_output_max_tokens = 2_048
    app = create_app(settings, model_client=Compactor(), child_model_client=Compactor())
    runtime = app.state.agent_runtime
    child = runtime.subagents.runner
    assert child.context_window_tokens == 32_000
    assert child.output_tokens == 2_048
    assert runtime.context_manager.input_budget == 23_552
    app.state.database.close()


def test_recompress_oversized_summary_and_reject_no_progress():
    class Verbose(Compactor):
        async def compact(self, messages, *, max_tokens):
            self.calls.append(messages)
            return {"summary": "verbose " * 2000 if len(self.calls) == 1 else "short"}

    model = Verbose()
    manager = AgentContextManager(model, summary_max_tokens=256)
    messages = [{"role": "user", "content": "old" * 10000}, {"role": "user", "content": "latest"}]
    compacted, metadata = fit(manager, messages, force=True)
    assert metadata and len(model.calls) > 1 and "short" in compacted[0]["content"]

    class Stuck(Compactor):
        async def compact(self, messages, *, max_tokens):
            return {"summary": "verbose " * 2000}

    with pytest.raises(DomainError, match="did not shrink"):
        fit(AgentContextManager(Stuck(), summary_max_tokens=256), messages, force=True)


def test_private_read_text_is_summarized_and_reference_survives_recompression():
    reference = {
        "type": "cintel_private_tool_result_ref",
        "tool_name": "read_file",
        "arguments": {"file_id": "f", "cursor": "0"},
    }
    messages = [
        {"role": "user", "content": "task"},
        *pair("read", "read_file", json.dumps(reference)),
    ]

    async def prepare(values):
        return [
            {**m, "content": "private evidence " * 1000} if m.get("role") == "tool" else m
            for m in values
        ]

    model = Compactor()
    manager = AgentContextManager(model, read_only_tools={"read_file"})
    compacted, metadata = fit(manager, messages, force=True, prepare=prepare)
    assert metadata
    assert "private evidence" in json.dumps(model.calls)
    assert "file_reads" in json.dumps(compacted) and "file_id" in json.dumps(compacted)
    assert "private evidence" not in json.dumps(compacted)


def test_official_capacity_overrides_and_storage_limit_are_independent():
    from app.agent.model_context import checkpoint_byte_limit, model_context_window
    from app.persistence.agent_runtime import ensure_checkpoint_size

    assert model_context_window("deepseek-v4-flash", "https://api.deepseek.com") == 1_000_000
    assert model_context_window("deepseek-v4-flash", "https://proxy.example/v1") == 64_000
    assert model_context_window("custom", "https://proxy.example/v1", 128_000) == 128_000
    assert checkpoint_byte_limit(64_000) == 3 * 1024 * 1024
    assert checkpoint_byte_limit(1_000_000) == 16_000_000 + 256 * 1024
    with pytest.raises(DomainError):
        ensure_checkpoint_size({"provider_messages": ["x" * 4_000_000]})
    ensure_checkpoint_size(
        {"context_window_tokens": 1_000_000, "provider_messages": ["x" * 4_000_000]}
    )
