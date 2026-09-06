"""Vercel entry point: bind HTTP before importing the model SDKs."""

import asyncio
from contextlib import AsyncExitStack
from importlib import import_module


class VercelApplication:
    def __init__(self):
        self._application = None
        self._initialization_lock = asyncio.Lock()
        self._lifespan = AsyncExitStack()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await self._lifespan.aclose()
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        async with self._initialization_lock:
            if self._application is None:
                # Importing LiteLLM can exceed the container's port-binding deadline.
                # The first request waits for the real application and its lifespan;
                # readiness is never reported before the database and Redis are ready.
                module = await asyncio.to_thread(import_module, "app.main")
                application = module.create_app()
                await self._lifespan.enter_async_context(
                    application.router.lifespan_context(application)
                )
                self._application = application

        await self._application(scope, receive, send)


app = VercelApplication()
