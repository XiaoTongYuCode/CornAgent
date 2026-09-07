import asyncio
import json

import httpx
import pytest

from app.agent.tool_executor import AgentToolExecutor
from app.agent.tools.base import ToolExecutionContext
from app.agent.tools.catalog import AgentToolCatalog
from app.agent.tools.web import build_web_tools
from app.settings import Settings


@pytest.fixture
def web(monkeypatch):
    requests, responses = [], []
    real_client = httpx.AsyncClient

    async def handle(request):
        requests.append(request)
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real_client(
            **kw,
            transport=httpx.MockTransport(handle),
        ),
    )
    catalog = AgentToolCatalog(
        build_web_tools(Settings(_env_file=None, tavily_api_key="test-secret"))
    )
    return AgentToolExecutor(catalog), requests, responses


def test_search_and_reader_for_child_with_bounded_content(web):
    executor, requests, responses = web
    responses.append(
        httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Source", "url": "https://example.com", "content": "x" * 5000},
                ]
            },
        )
    )
    result = asyncio.run(
        executor.execute_tool(
            "web_search",
            {"query": "test"},
            context=ToolExecutionContext(execution_scope="child"),
        )
    )
    assert result["results"][0]["url"] == "https://example.com"
    assert len(result["results"][0]["content"]) == 4000
    assert requests[0].headers["authorization"] == "Bearer test-secret"
    assert json.loads(requests[0].content) == {
        "query": "test",
        "max_results": 5,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
        "auto_parameters": False,
    }
    responses.append(
        httpx.Response(
            200,
            json={
                "data": {
                    "title": "Example",
                    "content": "a" * 25000,
                }
            },
        )
    )
    result = asyncio.run(executor.execute_tool("read_url", {"url": "https://example.com?a=b"}))
    assert result["truncated"] is True and len(result["content"]) == 24000
    assert str(requests[1].url) == "https://r.jina.ai/"
    assert json.loads(requests[1].content) == {"url": "https://example.com?a=b"}
    assert "authorization" not in requests[1].headers
    assert requests[1].headers["x-no-cache"] == "true"
    assert executor.catalog.for_scope("child").names() == ("web_search", "read_url")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost",
        "http://127.0.0.1",
        "http://169.254.169.254",
        "http://[::1]",
        "https://user:password@example.com",
        "http://example.com:8080",
    ],
)
def test_reader_rejects_nonpublic_targets(web, url):
    executor, requests, _ = web
    result = asyncio.run(executor.execute_tool("read_url", {"url": url}))
    assert result["error"]["type"] == "InvalidToolArguments"
    assert requests == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, text="test-secret"),
        httpx.Response(200, text="not JSON test-secret"),
        httpx.Response(200, json={"results": None}),
        httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
        httpx.ReadTimeout("test-secret"),
    ],
)
def test_provider_errors_do_not_leak_upstream_data(web, response):
    executor, _, responses = web
    responses.append(response)
    result = asyncio.run(executor.execute_tool("web_search", {"query": "test"}))
    assert result["ok"] is False
    assert "test-secret" not in json.dumps(result)


def test_missing_key_and_cancellation_do_not_call_provider(web):
    executor, requests, responses = web
    missing = AgentToolExecutor(
        AgentToolCatalog(
            build_web_tools(
                Settings(_env_file=None, tavily_api_key=None),
            )
        )
    )
    result = asyncio.run(missing.execute_tool("web_search", {"query": "test"}))
    assert result["error"]["type"] == "WebSearchNotConfigured"
    cancelled = asyncio.Event()
    cancelled.set()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            executor.execute_tool(
                "read_url",
                {"url": "https://example.com"},
                context=ToolExecutionContext(cancel_event=cancelled),
            )
        )
    assert requests == responses == []
