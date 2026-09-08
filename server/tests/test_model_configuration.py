import asyncio

import litellm
import pytest

from app.agent.model import AgentModelConfigurationError, LiteLLMAgentModel
from tests.test_lifecycle import start, wait_run


@pytest.mark.parametrize("streaming", [True, False])
def test_unsupported_parameters_fail_without_retry_or_leaking_payload(monkeypatch, streaming):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise litellm.UnsupportedParamsError(
            message="secret-request-body", model="fake", llm_provider="openai"
        )

    monkeypatch.setattr("app.agent.model.litellm.acompletion", completion)
    model = LiteLLMAgentModel(model="fake", api_key="test", max_retries=3)

    async def run():
        if streaming:
            return [event async for event in model.stream([{"role": "user", "content": "secret"}])]
        return await model.compact(
            [{"role": "user", "content": "secret"}], max_tokens=100
        )

    with pytest.raises(AgentModelConfigurationError) as error:
        asyncio.run(run())
    assert len(calls) == 1
    assert "secret" not in str(error.value)


def test_reasoning_effort_is_opt_in_and_deepseek_override_is_request_local():
    for model_name, effort in [
        ("deepseek/deepseek-chat", "high"),
        ("openai/test", "low"),
        ("openai/test", None),
    ]:
        model = LiteLLMAgentModel(model=model_name, api_key="test", reasoning_effort=effort)
        request = model._request(model.primary, messages=[], tools=[], stream=True)
        assert request.get("reasoning_effort") == effort
        assert ("reasoning_effort" in request) == (effort is not None)
        assert ("allowed_openai_params" in request) == model_name.startswith("deepseek/")


def test_configuration_failure_is_persisted_and_projected(client_factory):
    class Model:
        async def stream(self, messages):
            raise AgentModelConfigurationError("test", "fake")
            yield

    with client_factory(model=Model()) as client:
        created = start(client)
        detail = wait_run(client, created["session"]["id"], "failed")
        assert "agent_model_configuration_error" in str(detail)
        assert "模型调用参数配置错误" in str(detail)
