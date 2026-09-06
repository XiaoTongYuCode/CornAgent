import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import vercel_entrypoint


def test_vercel_binds_before_loading_and_initializes_once(monkeypatch):
    asyncio.run(_exercise_entrypoint(monkeypatch))


async def _exercise_entrypoint(monkeypatch):
    calls = []

    @asynccontextmanager
    async def lifespan(application):
        calls.append("startup")
        await asyncio.sleep(0)
        yield
        calls.append("shutdown")

    class Application:
        router = SimpleNamespace(lifespan_context=lifespan)

        async def __call__(self, scope, receive, send):
            assert calls == ["import", "startup"]
            await send({"type": "http.response.start", "status": 200})

    def import_app(name):
        assert name == "app.main"
        calls.append("import")
        return SimpleNamespace(create_app=Application)

    monkeypatch.setattr(vercel_entrypoint, "import_module", import_app)
    entry = vercel_entrypoint.VercelApplication()
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    process = asyncio.create_task(entry({"type": "lifespan"}, incoming.get, outgoing.put))
    await incoming.put({"type": "lifespan.startup"})
    assert await outgoing.get() == {"type": "lifespan.startup.complete"}
    assert calls == []

    await asyncio.gather(
        entry({"type": "http"}, incoming.get, outgoing.put),
        entry({"type": "http"}, incoming.get, outgoing.put),
    )
    assert calls == ["import", "startup"]
    assert (await outgoing.get())["status"] == 200
    assert (await outgoing.get())["status"] == 200

    await incoming.put({"type": "lifespan.shutdown"})
    assert await outgoing.get() == {"type": "lifespan.shutdown.complete"}
    await process
    assert calls == ["import", "startup", "shutdown"]
