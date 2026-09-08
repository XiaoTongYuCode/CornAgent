import asyncio
import threading

import pytest

from app.agent.tool_executor import AgentToolExecutor
from app.agent.tools import AgentToolCatalog, ToolDefinition, ToolExecutionContext


def executor(handler, limit=4):
    return AgentToolExecutor(
        AgentToolCatalog(
            [
                ToolDefinition(
                    name="work",
                    description="work",
                    parameters={"type": "object"},
                    handler=handler,
                )
            ]
        ),
        max_concurrency=limit,
    )


def test_tool_limit_is_shared_across_runs_and_preserves_results():
    async def run():
        active = peak = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(args, context):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 4:
                started.set()
            try:
                await release.wait()
                return {"run": context.run_id, "index": args["index"]}
            finally:
                active -= 1

        pool = executor(handler)
        calls = [
            asyncio.create_task(
                pool.execute_tool(
                    "work",
                    {"index": i},
                    context=ToolExecutionContext(run_id=str(i % 3)),
                )
            )
            for i in range(57)
        ]
        await asyncio.wait_for(started.wait(), 2)
        assert active == 4
        # Other event-loop work (including renewals/status) remains runnable.
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*calls)
        assert peak == 4 and active == 0
        assert results == [{"run": str(i % 3), "index": i} for i in range(57)]
        await pool.close()

    asyncio.run(run())


def test_cancelled_waiter_does_not_release_running_thread_or_start_queued_tool():
    async def run():
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = []

        def blocking():
            started.set()
            assert release.wait(5)
            finished.set()
            return {"ok": True}

        async def handler(args, context):
            calls.append(context.run_id)
            if context.run_id == "first":
                return await asyncio.to_thread(blocking)
            return {"ok": True}

        pool = executor(handler, 1)
        first = asyncio.create_task(
            pool.execute_tool("work", context=ToolExecutionContext(run_id="first"))
        )
        await asyncio.wait_for(asyncio.to_thread(started.wait, 2), 3)
        cancel = asyncio.Event()
        queued = asyncio.create_task(
            pool.execute_tool(
                "work", context=ToolExecutionContext(run_id="queued", cancel_event=cancel)
            )
        )
        other = asyncio.create_task(
            pool.execute_tool("work", context=ToolExecutionContext(run_id="other"))
        )
        try:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            cancel.set()
            await asyncio.sleep(0)
            assert calls == ["first"] and not other.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert await other == {"ok": True}
        await pool.close()
        assert finished.is_set() and calls == ["first", "other"]

    asyncio.run(run())


def test_cancel_task_while_queued_and_handler_error_do_not_leak_permits():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def handler(args, context):
            started.set()
            await release.wait()
            raise ValueError("expected")

        pool = executor(handler, 1)
        first = asyncio.create_task(pool.execute_tool("work"))
        await started.wait()
        queued = asyncio.create_task(pool.execute_tool("work"))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        release.set()
        assert (await first)["error"]["type"] == "ValueError"
        assert (await asyncio.wait_for(pool.execute_tool("work"), 2))["error"][
            "type"
        ] == "ValueError"
        await pool.close()

    asyncio.run(run())


def test_bounded_pool_keeps_connection_available_for_control_work():
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import QueuePool

    async def run():
        engine = create_engine(
            "sqlite://", poolclass=QueuePool, pool_size=5, max_overflow=0, pool_timeout=0.1
        )
        started, release = asyncio.Event(), asyncio.Event()
        active = 0

        async def handler(args, context):
            nonlocal active
            with engine.connect() as connection:
                assert connection.scalar(text("select 1")) == 1
                active += 1
                if active == 4:
                    started.set()
                try:
                    await release.wait()
                finally:
                    active -= 1
            return {"ok": True}

        pool = executor(handler)
        calls = [asyncio.create_task(pool.execute_tool("work")) for _ in range(19)]
        try:
            await asyncio.wait_for(started.wait(), 2)
            with engine.connect() as control:
                assert control.scalar(text("select 1")) == 1
            assert engine.pool.checkedout() == 4
        finally:
            release.set()
        assert all(result == {"ok": True} for result in await asyncio.gather(*calls))
        await pool.close()
        assert engine.pool.checkedout() == 0
        engine.dispose()

    asyncio.run(run())


def test_root_children_and_approval_share_the_runtime_budget():
    from app.agent.runtime import AgentRuntime
    from app.agent.tools import ToolApproval

    async def run():
        active = peak = 0
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(args, context):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                entered.set()
            try:
                await release.wait()
                return {"ok": True}
            finally:
                active -= 1

        async def prepare(args, context):
            return ToolApproval(query="Approve?", payload={})

        read = ToolDefinition(
            name="read",
            description="read",
            parameters={},
            handler=handler,
            execution_scopes=frozenset({"root", "child"}),
            read_only=True,
        )
        write = ToolDefinition(
            name="write",
            description="write",
            parameters={},
            handler=prepare,
            approval_handler=handler,
        )
        runtime = AgentRuntime(
            session_factory=lambda: None,
            redis_url=None,
            model="fake",
            api_key=None,
            api_base=None,
            model_timeout_seconds=30,
            reconcile_seconds=60,
            stream_max_events=100,
            tool_catalog=AgentToolCatalog([read, write]),
            tool_max_concurrency=2,
        )
        root = runtime.tool_executor
        child = runtime.subagents.runner.executor
        calls = [
            asyncio.create_task(root.execute_tool("read")),
            asyncio.create_task(
                child.execute_tool("read", context=ToolExecutionContext(execution_scope="child"))
            ),
            asyncio.create_task(root.invoke_approval(write, {}, ToolExecutionContext())),
        ]
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.sleep(0)
        assert active == peak == 2
        release.set()
        assert all(result["ok"] for result in await asyncio.gather(*calls))
        assert peak == 2
        denied = await child.execute_tool(
            "write", context=ToolExecutionContext(execution_scope="child")
        )
        assert denied["ok"] is False
        await runtime.close()

    asyncio.run(run())
