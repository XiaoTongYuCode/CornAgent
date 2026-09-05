import os

import pytest

from app.object_store import S3ObjectStore
from app.settings import PROJECT_ROOT, Settings


@pytest.fixture(autouse=True)
def isolate_process_configuration(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("CORNAGENT_"):
            monkeypatch.delenv(key)


def test_dotenv_connections_secrets_arrays_and_environment_precedence(tmp_path, monkeypatch):
    config = tmp_path / ".env"
    config.write_text(
        "CORNAGENT_AGENT_API_KEY=fixture-model-key\n"
        "CORNAGENT_AGENT_API_BASE=https://model.example/v1\n"
        "CORNAGENT_DATABASE_URL=postgresql+psycopg://user:pass@db.example:5433/agent\n"
        "CORNAGENT_REDIS_URL=redis://:password@cache.example:6380/2\n"
        'CORNAGENT_AGENT_FILE_IMAGE_MIME_TYPES=["image/png","image/jpeg"]\n'
        "CORNAGENT_SERVER_RELOAD=false\n"
    )
    monkeypatch.setenv("CORNAGENT_AGENT_API_BASE", "https://override.example/v1")
    settings = Settings(_env_file=config)
    assert settings.agent_api_base == "https://override.example/v1"
    assert settings.agent_api_key.get_secret_value() == "fixture-model-key"
    assert "fixture-model-key" not in repr(settings)
    assert settings.database_url == "postgresql+psycopg://user:pass@db.example:5433/agent"
    assert settings.redis_url == "redis://:password@cache.example:6380/2"
    assert settings.agent_file_image_mime_types == ("image/png", "image/jpeg")
    assert settings.server_reload is False


def test_blank_optional_configuration_keeps_unconfigured_secrets(tmp_path, monkeypatch):
    config = tmp_path / ".env"
    config.write_text(
        "CORNAGENT_AGENT_API_KEY=\n"
        "CORNAGENT_AGENT_FALLBACK_API_KEY=\n"
        "CORNAGENT_S3_ENDPOINT_URL=\n"
    )
    monkeypatch.setenv("CORNAGENT_AGENT_API_KEY", "")
    monkeypatch.setenv("CORNAGENT_AGENT_FALLBACK_API_KEY", "")
    monkeypatch.setenv("CORNAGENT_S3_ENDPOINT_URL", "")
    settings = Settings(_env_file=config)
    assert settings.agent_api_key is None
    assert settings.agent_fallback_api_key is None
    assert settings.s3_endpoint_url is None


def test_relative_storage_paths_do_not_follow_process_working_directory(tmp_path, monkeypatch):
    config = tmp_path / "config.env"
    config.write_text(
        "CORNAGENT_FILE_STORE_PATH=server/.data/custom\n"
        "CORNAGENT_FRONTEND_DIST=frontend/custom-dist\n"
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=config)
    assert settings.file_store_path == PROJECT_ROOT / "server/.data/custom"
    assert settings.frontend_dist == PROJECT_ROOT / "frontend/custom-dist"


def test_s3_credentials_from_dotenv_reach_sdk(tmp_path, monkeypatch):
    import boto3

    config = tmp_path / ".env"
    config.write_text(
        "CORNAGENT_S3_BUCKET=fixture-bucket\n"
        "CORNAGENT_S3_ENDPOINT_URL=http://127.0.0.1:9000\n"
        "CORNAGENT_S3_ACCESS_KEY_ID=fixture-id\n"
        "CORNAGENT_S3_SECRET_ACCESS_KEY=fixture-secret\n"
        "CORNAGENT_S3_SESSION_TOKEN=fixture-token\n"
    )
    captured = {}

    def client(_service, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(boto3, "client", client)
    S3ObjectStore(Settings(_env_file=config))
    assert captured["endpoint_url"] == "http://127.0.0.1:9000"
    assert captured["aws_access_key_id"] == "fixture-id"
    assert captured["aws_secret_access_key"] == "fixture-secret"
    assert captured["aws_session_token"] == "fixture-token"
