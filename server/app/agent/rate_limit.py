from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from time import monotonic

import redis.asyncio as async_redis
from redis.exceptions import RedisError

from app.persistence.errors import DomainError
from app.persistence.scope import Identity

_CONSUME_FIXED_WINDOW = """
local count = redis.call('INCRBY', KEYS[1], ARGV[2])
if count == tonumber(ARGV[2]) then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""


@dataclass(slots=True)
class _MemoryWindow:
    count: int
    reset_at: float


class AgentRunRateLimiter:
    """Bound newly-created Agent Runs per user and tenant."""

    def __init__(
        self,
        *,
        redis_url: str | None,
        environment: str,
        user_runs_per_minute: int,
        tenant_runs_per_minute: int,
    ) -> None:
        self._redis = (
            async_redis.Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        )
        self._namespace = f"cornagent:{environment}:agent-run"
        self._limits = (
            ("user", user_runs_per_minute),
            ("tenant", tenant_runs_per_minute),
        )
        self._memory_lock = asyncio.Lock()
        self._memory_windows: dict[str, _MemoryWindow] = {}

    async def require(self, identity: Identity) -> None:
        resources = {
            "user": f"{identity.tenant_id}:{identity.user_id}",
            "tenant": identity.tenant_id,
        }
        for scope, limit in self._limits:
            key = self._key(scope, resources[scope])
            try:
                count, retry_after = await self._consume(key)
            except RedisError as exc:
                raise DomainError(
                    "agent_run_rate_limit_unavailable",
                    "Agent Run admission is temporarily unavailable.",
                    status_code=503,
                ) from exc
            if count <= limit:
                continue
            raise DomainError(
                "agent_run_rate_limited",
                "Agent Run request limit exceeded.",
                status_code=429,
                details={"scope": scope, "retry_after_seconds": retry_after},
            )

    async def aclose(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def _consume(self, key: str) -> tuple[int, int]:
        if self._redis is not None:
            result = await self._redis.eval(_CONSUME_FIXED_WINDOW, 1, key, 60, 1)
            count, ttl = (int(item) for item in result)
            return count, max(ttl, 1)
        async with self._memory_lock:
            now = monotonic()
            window = self._memory_windows.get(key)
            if window is None or window.reset_at <= now:
                window = _MemoryWindow(count=0, reset_at=now + 60)
                self._memory_windows[key] = window
            window.count += 1
            return window.count, max(1, int(window.reset_at - now))

    def _key(self, scope: str, resource: str) -> str:
        digest = hashlib.sha256(resource.encode()).hexdigest()
        return f"{self._namespace}:{scope}:{digest}"


@dataclass(slots=True)
class AgentStreamConnectionLease:
    _limiter: AgentStreamConnectionLimiter
    _identity_key: str
    _run_id: str
    _released: bool = False

    async def release(self) -> None:
        await self._limiter._release(self)


class AgentStreamConnectionLimiter:
    """Bound live SSE readers per authenticated membership and Run on this instance."""

    def __init__(self, *, identity_limit: int, run_limit: int) -> None:
        self._identity_limit = identity_limit
        self._run_limit = run_limit
        self._lock = asyncio.Lock()
        self._identity_connections: dict[str, int] = {}
        self._run_connections: dict[str, int] = {}

    async def acquire(
        self,
        identity: Identity,
        run_id: str,
    ) -> AgentStreamConnectionLease:
        identity_key = f"{identity.tenant_id}:{identity.membership_id}"
        async with self._lock:
            if self._identity_connections.get(identity_key, 0) >= self._identity_limit:
                raise self._limit_error("identity")
            if self._run_connections.get(run_id, 0) >= self._run_limit:
                raise self._limit_error("run")
            self._identity_connections[identity_key] = (
                self._identity_connections.get(identity_key, 0) + 1
            )
            self._run_connections[run_id] = self._run_connections.get(run_id, 0) + 1
        return AgentStreamConnectionLease(self, identity_key, run_id)

    async def _release(self, lease: AgentStreamConnectionLease) -> None:
        async with self._lock:
            if lease._released:
                return
            lease._released = True
            self._decrement(self._identity_connections, lease._identity_key)
            self._decrement(self._run_connections, lease._run_id)

    @staticmethod
    def _decrement(connections: dict[str, int], resource: str) -> None:
        remaining = connections.get(resource, 0) - 1
        if remaining > 0:
            connections[resource] = remaining
        else:
            connections.pop(resource, None)

    @staticmethod
    def _limit_error(scope: str) -> DomainError:
        return DomainError(
            "agent_stream_connection_limited",
            "Agent stream connection limit exceeded.",
            status_code=429,
            details={"scope": scope},
        )


__all__ = [
    "AgentRunRateLimiter",
    "AgentStreamConnectionLease",
    "AgentStreamConnectionLimiter",
]
