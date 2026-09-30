"""Transaction boundary for the hosted Run executor.

An alternative backend must preserve the AgentRepository operations and their
atomic commit, lease and fencing semantics. Swapping a connection string or
implementing only checkpoint serialization is insufficient.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.persistence.agent_runtime import AgentRepository


class DurableBackend(Protocol):
    async def transact(self, operation: Callable[[AgentRepository], Any]) -> Any:
        """Execute one synchronous repository transaction without holding an event-loop thread."""


class PostgresDurableBackend:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        context_window_tokens: int,
        file_input_enabled: bool,
        file_max_count: int,
        file_max_total_bytes: int,
        pdf_max_count: int,
    ) -> None:
        self.session_factory = session_factory
        self.repository_options = {
            "context_window_tokens": context_window_tokens,
            "file_input_enabled": file_input_enabled,
            "file_max_count": file_max_count,
            "file_max_total_bytes": file_max_total_bytes,
            "pdf_max_count": pdf_max_count,
        }

    async def transact(self, operation: Callable[[AgentRepository], Any]) -> Any:
        def invoke() -> Any:
            with self.session_factory() as db:
                return operation(AgentRepository(db, **self.repository_options))

        return await asyncio.to_thread(invoke)
