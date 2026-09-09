"""Opt-in metrics, independent of agent correctness and payload persistence."""

import asyncio
import logging
import math
import queue
import threading
import time
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy import delete

from app.persistence.models import UsageEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricEvent:
    tenant_id: str
    owner_membership_id: str
    session_id: str
    run_id: str
    kind: str
    name: str
    execution_scope: str
    status: str
    duration_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventSink(Protocol):
    """Called only by the background consumer. Implementations must bound their IO."""

    def write(self, event: MetricEvent) -> None: ...


class DatabaseSink:
    def __init__(self, session_factory, retention_days: int):
        self.session_factory = session_factory
        self.retention_days = retention_days
        self._cleanup_at = 0.0

    def write(self, event: MetricEvent) -> None:
        with self.session_factory() as db:
            if time.monotonic() >= self._cleanup_at:
                db.execute(
                    delete(UsageEvent).where(
                        UsageEvent.created_at
                        < datetime.now(UTC) - timedelta(days=self.retention_days)
                    )
                )
                self._cleanup_at = time.monotonic() + 3600
            db.add(UsageEvent(**asdict(event)))
            db.commit()


class Collector:
    """Bounded, nonblocking, best-effort delivery. Never retries business work."""

    def __init__(self, sink: EventSink, capacity: int = 2048):
        self.sink = sink
        self.events: queue.Queue = queue.Queue(maxsize=capacity)
        self.dropped = 0
        self.failed = 0
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._consume, daemon=True, name="usage-metrics")
        self._thread.start()

    def emit(self, event: MetricEvent) -> None:
        if self._closed.is_set():
            return
        try:
            self.events.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def _consume(self):
        while not self._closed.is_set() or not self.events.empty():
            try:
                event = self.events.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.sink.write(event)
            except Exception:  # noqa: BLE001 - metrics must not affect execution
                self.failed += 1
                # Never log SQL parameters, identities or provider payloads.
                if self.failed == 1:
                    logger.warning("Usage event delivery failed; collection is best-effort")
            finally:
                self.events.task_done()

    def close(self):
        self._closed.set()
        self._thread.join(timeout=2)


_current: ContextVar[tuple | None] = ContextVar("usage_context", default=None)


@contextmanager
def bind(collector, context):
    token = _current.set((collector, context) if collector else None)
    try:
        yield
    finally:
        _current.reset(token)


def emit(kind, name, status, started, usage=None):
    with suppress(Exception):
        _emit(kind, name, status, started, usage)


def _emit(kind, name, status, started, usage=None):
    current = _current.get()
    if current is None:
        return
    collector, ctx = current
    usage = usage if isinstance(usage, dict) else {}

    def count(key):
        value = usage.get(key)
        return (
            max(0, int(value))
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value < 2**63
            else None
        )

    collector.emit(
        MetricEvent(
            tenant_id=ctx.tenant_id,
            owner_membership_id=ctx.owner_membership_id,
            session_id=ctx.session_id,
            run_id=ctx.run_id,
            execution_scope=ctx.execution_scope,
            kind=kind,
            name=name[:200],
            status=status,
            duration_seconds=time.monotonic() - started,
            input_tokens=count("prompt_tokens"),
            output_tokens=count("completion_tokens"),
        )
    )


async def tool_call(name, callback):
    if _current.get() is None or name is None:
        return await callback()
    started = time.monotonic()
    status = "failed"
    try:
        result = await callback()
        status = "failed" if isinstance(result, dict) and result.get("ok") is False else "completed"
        return result
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        emit("tool", name, status, started)


async def completion(callback, **kwargs):
    """Observe each actual provider attempt, including fallback and compaction."""
    if _current.get() is None:
        return await callback(**kwargs)
    started = time.monotonic()
    name = kwargs.get("model", "unknown")
    try:
        response = await callback(**kwargs)
    except BaseException as exc:
        emit(
            "model",
            name,
            "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
            started,
        )
        raise
    if not kwargs.get("stream"):
        usage = {}
        with suppress(Exception):
            usage = (
                response.get("usage")
                if isinstance(response, dict)
                else getattr(response, "usage", None)
            )
            if hasattr(usage, "model_dump"):
                usage = usage.model_dump()
        emit("model", name, "completed", started, usage if isinstance(usage, dict) else {})
        return response

    async def observed():
        status = "failed"
        usage = {}
        try:
            async for chunk in response:
                data = {}
                with suppress(Exception):
                    data = chunk if isinstance(chunk, dict) else chunk.model_dump()
                if data.get("usage"):
                    usage = data["usage"]
                yield chunk
            status = "completed"
        except (asyncio.CancelledError, GeneratorExit):
            status = "cancelled"
            raise
        finally:
            emit("model", name, status, started, usage)
            closer = getattr(response, "aclose", None)
            if closer:
                with suppress(Exception):
                    await closer()

    return observed()
