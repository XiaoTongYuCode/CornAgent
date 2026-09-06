import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.database import Database
from app.main import create_app
from app.persistence.models import Base
from app.settings import Settings
from tests.test_runtime import FakeAgentEventStream, FinalAgentModel


@pytest.fixture
def settings(tmp_path):
    postgres = os.environ.get("CORNAGENT_TEST_POSTGRES_URL")
    schema = "test_" + uuid4().hex
    admin = None
    url = f"sqlite+pysqlite:///{tmp_path / 'agent.db'}"
    if postgres:
        admin = create_engine(postgres)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = (
            make_url(postgres)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
    settings = Settings(
        _env_file=None,
        environment=schema,
        database_url=url,
        redis_url=os.environ.get("CORNAGENT_TEST_REDIS_URL"),
        file_store_path=tmp_path / "files",
        agent_reconcile_seconds=0.05,
        event_heartbeat_seconds=0.05,
        event_poll_seconds=0.01,
        agent_user_runs_per_minute=120,
        agent_tenant_runs_per_minute=1000,
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    database.close()
    try:
        yield settings
    finally:
        if admin:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.fixture
def client_factory(settings):
    @contextmanager
    def factory(model=None, stream=None, *, client_address=("127.0.0.1", 50000)):
        if not settings.redis_url and stream is None:
            stream = FakeAgentEventStream()
        app = create_app(settings, model_client=model or FinalAgentModel(), event_stream=stream)
        with TestClient(app, client=client_address) as client:
            yield client

    return factory
