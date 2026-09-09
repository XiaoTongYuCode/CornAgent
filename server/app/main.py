"""CornAgent composition root. PostgreSQL is authoritative; Redis replays SSE."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent.model import AgentModelClient
from app.agent.rate_limit import AgentRunRateLimiter, AgentStreamConnectionLimiter
from app.agent.runtime import AgentRuntime
from app.agent.stream import AgentEventStream
from app.agent.subagents.protocol import SubagentOptions
from app.agent.tools.base import ToolDefinition
from app.agent.tools.catalog import build_default_tool_catalog
from app.agent.tools.files import build_file_tools
from app.agent.tools.mock_search import build_mock_web_search_tool
from app.agent.tools.web import build_web_tools
from app.api.routes.agent import router as agent_router
from app.api.routes.files import router as file_router
from app.auth.email import EmailSender, SmtpEmailSender
from app.auth.provider import BuiltinIdentityProvider, IdentityProvider
from app.auth.routes import router as auth_router
from app.database import Database
from app.object_store import BlobStore, build_blob_store
from app.pdf_reader import PdfReader
from app.persistence.errors import DomainError
from app.persistence.models import FileResource, utcnow
from app.settings import Settings

logger = logging.getLogger(__name__)


def collect_files(database: Database, store: BlobStore):
    with database.session_factory() as db:
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        rows = db.scalars(
            select(FileResource)
            .where(
                or_(
                    FileResource.state == "delete_pending",
                    (FileResource.state.in_(("pending", "stored")))
                    & (FileResource.created_at < cutoff),
                )
            )
            .with_for_update(skip_locked=True)
        ).all()
        for item in rows:
            store.delete(item.storage_key)
            item.state = "deleted"
            item.deleted_at = utcnow()
            item.extracted_markdown = None
            item.extraction_status = "not_requested"
        db.commit()


def create_app(
    settings: Settings | None = None,
    *,
    model_client: AgentModelClient | None = None,
    child_model_client: AgentModelClient | None = None,
    additional_tools: tuple[ToolDefinition, ...] = (),
    identity_provider: IdentityProvider | None = None,
    email_sender: EmailSender | None = None,
    event_stream: AgentEventStream | None = None,
) -> FastAPI:
    settings = settings or Settings()
    if (
        settings.users_enabled
        and settings.auth_mode == "account"
        and identity_provider is None
        and email_sender is None
        and (not settings.auth_smtp_host or not settings.auth_smtp_from)
    ):
        raise ValueError("Account mode requires SMTP host/from or an injected EmailSender")
    database = Database(settings)
    store = build_blob_store(settings)
    extraction_admission = asyncio.Semaphore(settings.file_extraction_max_concurrency)
    pdf_reader = PdfReader(settings, store, extraction_admission)
    runtime = AgentRuntime(
        session_factory=database.session_factory,
        redis_url=settings.redis_url,
        model=settings.agent_model,
        api_key=settings.agent_api_key.get_secret_value() if settings.agent_api_key else None,
        api_base=settings.agent_api_base,
        model_timeout_seconds=settings.agent_model_timeout_seconds,
        reconcile_seconds=settings.agent_reconcile_seconds,
        stream_max_events=settings.agent_stream_max_events,
        model_client=model_client,
        child_model_client=child_model_client,
        child_model=settings.agent_subagent_model,
        subagent_options=SubagentOptions(
            enabled=settings.agent_subagents_enabled,
            spawn_max_tasks=settings.agent_subagent_spawn_max_tasks,
            run_max_tasks=settings.agent_subagent_run_max_tasks,
            run_max_concurrency=settings.agent_subagent_run_max_concurrency,
            timeout_seconds=settings.agent_subagent_timeout_seconds,
            wait_default_seconds=settings.agent_subagent_wait_default_seconds,
            result_batch_max_bytes=settings.agent_subagent_result_batch_max_bytes,
            result_projection_max_chars=settings.agent_subagent_result_projection_max_chars,
            final_candidate_max_bytes=settings.agent_subagent_final_candidate_max_bytes,
            reconcile_seconds=settings.agent_subagent_reconcile_seconds,
        ),
        event_stream=event_stream,
        tool_catalog=build_default_tool_catalog(
            [
                *build_file_tools(database.session_factory, pdf_reader),
                *build_web_tools(settings),
                *([build_mock_web_search_tool()] if settings.agent_mock_tools_enabled else []),
                *additional_tools,
            ]
        ),
        max_concurrency=settings.agent_max_concurrency,
        tool_max_concurrency=settings.agent_tool_max_concurrency,
        reasoning_effort=settings.agent_reasoning_effort,
        stream_batch_window_ms=settings.agent_stream_batch_window_ms,
        stream_batch_max_bytes=settings.agent_stream_batch_max_bytes,
        stream_active_ttl_seconds=settings.agent_stream_active_ttl_seconds,
        stream_terminal_ttl_seconds=settings.agent_stream_terminal_ttl_seconds,
        model_max_retries=settings.agent_model_max_retries,
        retry_base_delay_seconds=settings.agent_retry_base_delay_seconds,
        retry_max_delay_seconds=settings.agent_retry_max_delay_seconds,
        fallback_model=settings.agent_fallback_model,
        fallback_api_key=settings.agent_fallback_api_key.get_secret_value()
        if settings.agent_fallback_api_key
        else None,
        fallback_api_base=settings.agent_fallback_api_base,
        fallback_supports_images=settings.agent_fallback_supports_images,
        file_store=store,
        file_input_enabled=settings.agent_file_input_enabled,
        image_hydration_max_count=settings.agent_file_image_hydration_max_count,
        image_hydration_max_bytes=settings.agent_file_image_hydration_max_bytes,
        context_checkpoint_trigger_ratio=settings.agent_context_checkpoint_trigger_ratio,
        context_summary_max_tokens=settings.agent_context_summary_max_tokens,
    )
    rate_limiter = AgentRunRateLimiter(
        redis_url=settings.redis_url,
        environment=settings.environment,
        user_runs_per_minute=settings.agent_user_runs_per_minute,
        tenant_runs_per_minute=settings.agent_tenant_runs_per_minute,
    )

    async def file_collector():
        while True:
            try:
                await run_in_threadpool(collect_files, database, store)
            except Exception:
                logger.exception("Attachment collection failed; will retry")
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(_app):
        collector = None
        try:
            await run_in_threadpool(database.ping)
            await runtime.start()
            collector = asyncio.create_task(file_collector())
            yield
        finally:
            if collector:
                collector.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await collector
            await runtime.close()
            await rate_limiter.aclose()
            database.close()

    app = FastAPI(title="CornAgent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    app.state.settings = settings
    app.state.identity_provider = identity_provider or BuiltinIdentityProvider()
    app.state.auth_email_sender = email_sender or SmtpEmailSender(settings)
    app.state.database = database
    app.state.file_store = store
    app.state.file_body_admission = asyncio.Semaphore(settings.file_body_max_concurrency)
    app.state.file_upload_admission = asyncio.Semaphore(settings.file_upload_max_concurrency)
    app.state.file_extraction_admission = extraction_admission
    app.state.agent_runtime = runtime
    app.state.agent_run_rate_limiter = rate_limiter
    app.state.agent_stream_connection_limiter = AgentStreamConnectionLimiter(
        identity_limit=settings.agent_identity_stream_connections,
        run_limit=settings.agent_run_stream_connections,
    )

    @app.exception_handler(DomainError)
    async def domain_error(_request, error):
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "The request contains invalid fields.",
                }
            },
        )

    @app.middleware("http")
    async def same_origin_mutations(request: Request, call_next):
        # Cookie authentication and local access both require same-origin mutations.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            expected = (
                settings.auth_origin
                if settings.users_enabled
                else str(request.base_url).rstrip("/")
            )
            if (
                (origin and origin.rstrip("/") != expected)
                or (
                    settings.users_enabled and request.headers.get("sec-fetch-site") == "cross-site"
                )
                or (
                    settings.users_enabled
                    and not origin
                    and request.headers.get("x-cornagent-request") != "1"
                )
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "origin_rejected",
                            "message": "Use the same-origin CornAgent frontend.",
                        }
                    },
                )
        response = await call_next(request)
        if settings.users_enabled and request.url.path.startswith("/api/"):
            is_sse = (
                response.headers.get("Content-Type", "").split(";", 1)[0] == "text/event-stream"
            )
            # Keep authenticated responses private without allowing SSE compression.
            response.headers["Cache-Control"] = (
                "no-store, no-transform" if is_sse else "no-store"
            )
            response.headers["Vary"] = "Cookie"
        return response

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(file_router, prefix="/api/v1")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready():
        await run_in_threadpool(database.ping)
        runtime.require_available()
        await runtime.event_stream.ping()
        return {"status": "ready"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        return runtime.metrics.render()

    dist = settings.frontend_dist.resolve()
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        @app.get("/chat")
        @app.get("/chat/{session_id}")
        @app.get("/sidebar")
        @app.get("/rendering")
        def spa(session_id: str | None = None):
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
