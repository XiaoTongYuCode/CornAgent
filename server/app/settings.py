"""Project environment configuration for the CornAgent runtime."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORNAGENT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
    environment: str = "local"
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8000, ge=1, le=65535)
    server_reload: bool = True
    server_log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = "info"
    frontend_host: str = "127.0.0.1"
    frontend_port: int = Field(default=5173, ge=1, le=65535)
    database_url: str = "postgresql+psycopg://localhost:5432/cornagent"
    database_ssl_ca_pem: str | None = None
    redis_url: str | None = "redis://127.0.0.1:6379/0"
    file_store_path: Path = Path("server/.data/files")
    file_store_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_prefix: str = "cornagent/"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_session_token: SecretStr | None = None
    frontend_dist: Path = Path("frontend/dist")
    event_heartbeat_seconds: float = Field(default=5, gt=0)
    event_poll_seconds: float = Field(default=0.25, gt=0)
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    agent_model: str = Field(default="deepseek-v4-flash-vision-exp", min_length=1, max_length=200)
    agent_api_key: SecretStr | None = Field(
        default=None,
    )
    agent_api_base: str | None = "https://api.deepseek.com"
    agent_model_timeout_seconds: float = Field(default=120, gt=0, le=600)
    agent_reconcile_seconds: float = Field(default=5, gt=0, le=60)
    agent_stream_max_events: int = Field(default=1_000, ge=100, le=10_000)
    agent_max_concurrency: int = Field(default=20, ge=1, le=500)
    agent_subagents_enabled: bool = True
    tavily_api_key: SecretStr | None = Field(default=None, validation_alias="tavily_api_key")
    agent_mock_tools_enabled: bool = False
    agent_subagent_model: str | None = None
    agent_subagent_spawn_max_tasks: int = Field(default=10, ge=1, le=10)
    agent_subagent_run_max_tasks: int = Field(default=10, ge=1, le=100)
    agent_subagent_run_max_concurrency: int = Field(default=5, ge=1, le=5)
    agent_subagent_timeout_seconds: float = Field(default=600, gt=0)
    agent_subagent_wait_default_seconds: int = Field(default=300, ge=1, le=600)
    agent_subagent_result_batch_max_bytes: int = Field(default=64 * 1024, ge=1024)
    agent_subagent_result_projection_max_chars: int = Field(default=8000, ge=100, le=16000)
    agent_subagent_final_candidate_max_bytes: int = Field(default=256 * 1024, ge=1024)
    agent_subagent_reconcile_seconds: float = Field(default=1, gt=0, le=60)
    agent_user_runs_per_minute: int = Field(default=6, ge=1, le=120)
    agent_tenant_runs_per_minute: int = Field(default=60, ge=1, le=1_000)
    agent_identity_stream_connections: int = Field(default=8, ge=1, le=100)
    agent_run_stream_connections: int = Field(default=4, ge=1, le=50)
    agent_stream_batch_window_ms: int = Field(default=32, ge=0, le=1_000)
    agent_stream_batch_max_bytes: int = Field(default=4_096, ge=256, le=65_536)
    agent_file_input_enabled: bool = True
    file_upload_body_timeout_seconds: float = Field(default=60, gt=0, le=300)
    file_admission_timeout_seconds: float = Field(default=5, gt=0, le=60)
    file_body_max_concurrency: int = Field(default=2, ge=1, le=16)
    file_upload_max_concurrency: int = Field(default=2, ge=1, le=16)
    file_extraction_max_concurrency: int = Field(default=1, ge=1, le=4)
    agent_file_image_mime_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
    )
    agent_file_max_count: int = Field(default=4, ge=1, le=16)
    agent_file_image_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=32 * 1024 * 1024)
    agent_file_max_total_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1,
        le=64 * 1024 * 1024,
    )
    agent_file_image_hydration_max_count: int = Field(default=16, ge=1, le=128)
    agent_file_image_hydration_max_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1,
        le=128 * 1024 * 1024,
    )
    agent_file_image_max_side: int = Field(default=8192, ge=1, le=8192)
    agent_file_image_max_pixels: int = Field(default=25_000_000, ge=1, le=100_000_000)
    agent_file_pdf_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        le=16 * 1024 * 1024,
    )
    agent_file_pdf_max_count: int = Field(default=1, ge=1, le=4)
    agent_file_pdf_max_pages: int = Field(default=50, ge=1, le=200)
    agent_file_extraction_timeout_seconds: float = Field(default=20, gt=0, le=120)
    agent_file_extracted_max_chars: int = Field(default=200_000, ge=1_000, le=1_000_000)
    agent_stream_active_ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    agent_stream_terminal_ttl_seconds: int = Field(default=10_800, ge=60, le=604_800)
    agent_model_max_retries: int = Field(default=2, ge=0, le=10)
    agent_retry_base_delay_seconds: float = Field(default=0.5, ge=0, le=30)
    agent_retry_max_delay_seconds: float = Field(default=4.0, ge=0, le=120)
    agent_fallback_model: str = Field(
        default="deepseek-v4-flash-0731", min_length=1, max_length=200
    )
    agent_fallback_api_key: SecretStr | None = Field(
        default=None,
    )
    agent_fallback_api_base: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        min_length=1,
    )
    agent_fallback_supports_images: bool = False
    agent_context_checkpoint_trigger_ratio: float = Field(default=0.8, ge=0.5, le=0.95)
    agent_context_summary_max_tokens: int = Field(default=4_096, ge=256, le=32_768)

    @field_validator("file_store_path", "frontend_dist")
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
        value = value.expanduser()
        return (PROJECT_ROOT / value).resolve() if not value.is_absolute() else value.resolve()
