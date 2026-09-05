"""Bounded Redis Stream transport for already-persisted Agent events."""

from __future__ import annotations

import json
from typing import Any, Protocol

from redis.asyncio import Redis


class AgentEventStream(Protocol):
    async def publish(self, run_id: str, event: dict[str, Any]) -> None: ...

    async def read(
        self, run_id: str, redis_cursor: str, *, block_ms: int = 1_000
    ) -> tuple[str, list[dict[str, Any]]]: ...

    async def close(self) -> None: ...


class RedisAgentEventStream:
    def __init__(
        self,
        redis_url: str,
        *,
        max_events: int = 1_000,
        active_ttl_seconds: int = 86_400,
        terminal_ttl_seconds: int = 10_800,
    ) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.max_events = max_events
        self.active_ttl_seconds = active_ttl_seconds
        self.terminal_ttl_seconds = terminal_ttl_seconds

    @staticmethod
    def _key(run_id: str) -> str:
        return f"cornagent:agent:run:{run_id}:events"

    async def ping(self) -> None:
        await self.redis.ping()

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        key = self._key(run_id)
        ttl = (
            self.terminal_ttl_seconds
            if event.get("event") in {"done", "error", "cancelled"}
            else self.active_ttl_seconds
        )
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.xadd(
                key,
                {"event": json.dumps(event, ensure_ascii=False, separators=(",", ":"))},
                maxlen=self.max_events,
                approximate=True,
            )
            pipeline.expire(key, ttl)
            await pipeline.execute()

    async def read(
        self, run_id: str, redis_cursor: str, *, block_ms: int = 1_000
    ) -> tuple[str, list[dict[str, Any]]]:
        rows = await self.redis.xread({self._key(run_id): redis_cursor}, count=100, block=block_ms)
        events: list[dict[str, Any]] = []
        cursor = redis_cursor
        for _, entries in rows:
            for redis_id, fields in entries:
                cursor = redis_id
                raw = fields.get("event")
                if raw:
                    events.append(json.loads(raw))
        return cursor, events

    async def close(self) -> None:
        await self.redis.aclose()


__all__ = ["AgentEventStream", "RedisAgentEventStream"]
