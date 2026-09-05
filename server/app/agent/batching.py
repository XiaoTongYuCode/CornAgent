"""Small-window batching for provider text deltas."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from app.agent.model import ModelStreamEvent


@dataclass(frozen=True, slots=True)
class _ProducerError:
    error: BaseException


class _ProducerDone:
    pass


_DONE = _ProducerDone()


async def batch_model_stream_events(
    events: AsyncIterator[ModelStreamEvent],
    *,
    window_ms: int,
    max_bytes: int,
    on_source_event: Callable[[ModelStreamEvent], None] | None = None,
) -> AsyncIterator[ModelStreamEvent]:
    """Merge adjacent content/reasoning deltas without delaying first text."""

    normalized_window_ms = max(0, int(window_ms))
    normalized_max_bytes = max(1, int(max_bytes))
    if normalized_window_ms == 0:
        async for event in events:
            if on_source_event is not None:
                on_source_event(event)
            yield event
        return

    queue: asyncio.Queue[ModelStreamEvent | _ProducerError | _ProducerDone] = asyncio.Queue(
        maxsize=1
    )

    async def produce() -> None:
        try:
            async for event in events:
                if on_source_event is not None:
                    on_source_event(event)
                await queue.put(event)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - preserve provider exception ordering
            await queue.put(_ProducerError(exc))
        else:
            await queue.put(_DONE)

    producer = asyncio.create_task(produce(), name="cornagent-agent-stream-batcher")
    pending: ModelStreamEvent | None = None
    pending_bytes = 0
    first_text_published = False
    loop = asyncio.get_running_loop()
    deadline = 0.0
    try:
        while True:
            if pending is None:
                item = await queue.get()
            else:
                try:
                    item = await asyncio.wait_for(queue.get(), max(0.0, deadline - loop.time()))
                except TimeoutError:
                    yield pending
                    pending = None
                    pending_bytes = 0
                    continue
            if isinstance(item, _ProducerError):
                if pending is not None:
                    yield pending
                raise item.error
            if item is _DONE:
                if pending is not None:
                    yield pending
                return
            if item.kind == "raw":
                # ``raw`` is an internal retry-safety marker. Keep it visible to
                # the runtime without turning every provider chunk into a text
                # batch boundary.
                yield item
                continue
            if item.kind not in {"content", "reasoning"} or not item.content:
                if pending is not None:
                    yield pending
                    pending = None
                    pending_bytes = 0
                yield item
                continue
            if not first_text_published:
                first_text_published = True
                yield item
                continue
            if pending is None or pending.kind != item.kind:
                if pending is not None:
                    yield pending
                pending = item
                pending_bytes = len(item.content.encode("utf-8"))
                deadline = loop.time() + normalized_window_ms / 1000
            else:
                pending = ModelStreamEvent(
                    kind=pending.kind,
                    content=f"{pending.content}{item.content}",
                )
                pending_bytes += len(item.content.encode("utf-8"))
            if pending_bytes >= normalized_max_bytes:
                yield pending
                pending = None
                pending_bytes = 0
    finally:
        if not producer.done():
            producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer


__all__ = ["batch_model_stream_events"]
