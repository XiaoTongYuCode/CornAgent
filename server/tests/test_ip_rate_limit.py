import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import Request
from sqlalchemy import select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.agent.rate_limit import AgentRunRateLimiter
from app.api.deps import get_run_rate_limit_identity, get_scope
from app.auth.provider import BuiltinIdentityProvider
from app.persistence.errors import DomainError
from app.persistence.models import AgentQuestion
from app.persistence.scope import LOCAL_SCOPE
from app.settings import Settings
from tests.test_lifecycle import post, start, wait_run
from tests.test_runtime import FakeAgentModel, RejectingAgentRunRateLimiter

TEST_APP = SimpleNamespace(
    state=SimpleNamespace(
        settings=Settings(_env_file=None), identity_provider=BuiltinIdentityProvider()
    )
)


def identity(host, headers=()):
    return get_run_rate_limit_identity(
        Request(
            {
                "type": "http",
                "app": TEST_APP,
                "client": (host, 1234) if host else None,
                "headers": headers,
            }
        )
    )


def test_ip_identity_normalizes_addresses_and_ignores_untrusted_headers():
    assert identity("2001:0db8:0:0::1") == identity("2001:db8::1")
    assert identity("::ffff:192.0.2.1") == identity("192.0.2.1")
    assert identity("192.0.2.1", [(b"x-forwarded-for", b"192.0.2.2")]) == identity("192.0.2.1")
    assert identity(None) == identity("invalid")
    assert get_scope(Request({"type": "http", "app": TEST_APP})) is LOCAL_SCOPE


@pytest.mark.parametrize(
    "trusted,expected", [("127.0.0.1", "192.0.2.1"), ("10.0.0.1", "127.0.0.1")]
)
def test_ip_identity_uses_asgi_server_proxy_trust(trusted, expected):
    async def endpoint(scope, receive, send):
        assert get_run_rate_limit_identity(Request(scope)) == identity(expected)

    app = ProxyHeadersMiddleware(endpoint, trusted_hosts=trusted)
    asyncio.run(
        app(
            {
                "type": "http",
                "app": TEST_APP,
                "client": ("127.0.0.1", 1234),
                "headers": [(b"x-forwarded-for", b"192.0.2.1")],
            },
            None,
            None,
        )
    )


def test_ip_window_expires_without_sleep(monkeypatch):
    now = 100.0
    monkeypatch.setattr("app.agent.rate_limit.monotonic", lambda: now)

    async def run():
        nonlocal now
        limiter = AgentRunRateLimiter(
            redis_url=None, environment="test", user_runs_per_minute=6, tenant_runs_per_minute=60
        )
        for _ in range(6):
            await limiter.require(identity("192.0.2.1"))
        now = 159.0
        with pytest.raises(DomainError) as error:
            await limiter.require(identity("192.0.2.1"))
        assert error.value.status_code == 429
        await limiter.require(identity("192.0.2.2"))
        now = 160.0
        await limiter.require(identity("192.0.2.1"))
        await limiter.aclose()

    asyncio.run(run())


def test_all_new_run_routes_share_ip_quota_and_replays_are_free(settings, client_factory):
    settings.agent_user_runs_per_minute = 6
    with client_factory(client_address=("192.0.2.1", 1234)) as client:
        key = str(uuid4())
        created = start(client, key=key)
        session_id = created["session"]["id"]
        detail = wait_run(client, session_id)
        user, assistant = detail["messages"]
        for _ in range(5):
            start(client)
        assert start(client, key=key)["run"]["id"] == created["run"]["id"]
        for path, payload in [
            ("/sessions", {"content": "seventh"}),
            (f"/sessions/{session_id}/messages", {"content": "seventh"}),
            (f"/messages/{assistant['id']}/regenerate", {}),
            (f"/messages/{user['id']}/edit", {"content": "seventh"}),
        ]:
            response = post(client, path, payload)
            assert response.status_code == 429, response.text
            assert response.json()["error"]["details"]["scope"] == "user"
            assert 1 <= response.json()["error"]["details"]["retry_after_seconds"] <= 60
        forged = client.post(
            "/api/v1/agent/sessions",
            json={"content": "forged"},
            headers={
                "Idempotency-Key": str(uuid4()),
                "X-Forwarded-For": "192.0.2.99",
                "X-Real-IP": "192.0.2.99",
                "X-Vercel-Forwarded-For": "192.0.2.99",
            },
        )
        assert forged.status_code == 429

        # Reuse the application's event loop as well as its real Redis connections.
        async def other_address():
            transport = httpx.ASGITransport(app=client.app, client=("192.0.2.2", 5678))
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as other:
                assert (await other.get(f"/api/v1/agent/sessions/{session_id}")).status_code == 200
                response = await other.post(
                    "/api/v1/agent/sessions",
                    json={"content": "other address"},
                    headers={"Idempotency-Key": str(uuid4())},
                )
                assert response.status_code == 200, response.text

        client.portal.call(other_address)


def test_question_response_does_not_consume_new_run_quota(client_factory):
    with client_factory(FakeAgentModel()) as client:
        created = start(client)
        detail = wait_run(client, created["session"]["id"], "waiting_for_user")
        client.app.state.agent_run_rate_limiter = RejectingAgentRunRateLimiter()
        with client.app.state.database.session_factory() as db:
            question_id = db.scalar(select(AgentQuestion.id))
        response = post(
            client, f"/questions/{question_id}/respond", {"action": "answer", "content": "yes"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["run_id"] == detail["active_run"]["id"]
