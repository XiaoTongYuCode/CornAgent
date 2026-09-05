"""Exercise frozen Alembic revisions with real pre-upgrade conversation rows."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.database import Database
from app.persistence.agent_runtime import AgentRepository
from app.persistence.models import AgentRun, AgentSubagentTask
from app.persistence.scope import LOCAL_SCOPE
from app.settings import Settings


@pytest.mark.parametrize("existing", [False, True])
def test_subagent_schema_fresh_install_and_upgrade(settings, tmp_path, monkeypatch, existing):
    postgres = settings.database_url.startswith("postgresql")
    schema = "migration_" + uuid4().hex
    admin = None
    url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    if postgres:
        admin = create_engine(settings.database_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = (
            make_url(settings.database_url)
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
    monkeypatch.setenv("CORNAGENT_DATABASE_URL", url)
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    connection_settings = Settings(_env_file=None, database_url=url)
    before = None
    try:
        if existing:
            command.upgrade(config, "0001")
            engine = create_engine(url)
            metadata = MetaData()
            metadata.reflect(engine)
            now = datetime.now(UTC)
            ids = {name: str(uuid4()) for name in ("session", "user", "assistant", "run")}
            with engine.begin() as connection:
                connection.execute(
                    metadata.tables["cornagent_agent_sessions"]
                    .insert()
                    .values(
                        id=ids["session"],
                        tenant_id=LOCAL_SCOPE.tenant_id,
                        owner_membership_id=LOCAL_SCOPE.membership_id,
                        title="Existing conversation",
                        context={},
                        active_leaf_message_id=ids["assistant"],
                        created_at=now,
                        updated_at=now,
                    )
                )
                for role in ("user", "assistant"):
                    connection.execute(
                        metadata.tables["cornagent_agent_messages"]
                        .insert()
                        .values(
                            id=ids[role],
                            tenant_id=LOCAL_SCOPE.tenant_id,
                            owner_membership_id=LOCAL_SCOPE.membership_id,
                            session_id=ids["session"],
                            role=role,
                            markdown=f"Existing {role}",
                            content_parts=[],
                            provider_messages=[],
                            parent_message_id=ids["user"] if role == "assistant" else None,
                            version_group_id=ids[role],
                            version_index=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                connection.execute(
                    metadata.tables["cornagent_agent_runs"]
                    .insert()
                    .values(
                        id=ids["run"],
                        tenant_id=LOCAL_SCOPE.tenant_id,
                        owner_membership_id=LOCAL_SCOPE.membership_id,
                        session_id=ids["session"],
                        user_message_id=ids["user"],
                        assistant_message_id=ids["assistant"],
                        kind="create",
                        status="completed",
                        draft_markdown="Existing assistant",
                        reasoning_markdown="",
                        content_parts=[],
                        provider_usage={},
                        checkpoint={},
                        attempt=1,
                        stream_epoch=1,
                        next_sequence=2,
                        lease_fence=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
            before = ids
            engine.dispose()
        command.upgrade(config, "head")
        database = Database(connection_settings)
        inspector = inspect(database.engine)
        assert "cornagent_subagent_tasks" in inspector.get_table_names()
        assert {"checkpoint_revision", "subagent_completion_seq", "cancel_epoch"} <= {
            item["name"] for item in inspector.get_columns("cornagent_agent_runs")
        }
        with database.session_factory() as db:
            if before:
                row = db.get(AgentRun, before["run"])
                assert row.status == "completed" and row.draft_markdown == "Existing assistant"
                assert (
                    row.checkpoint_revision == row.cancel_epoch == row.subagent_completion_seq == 0
                )
            _, run = AgentRepository(db).create_session_run(
                LOCAL_SCOPE,
                content="new after migration",
                idempotency_key=str(uuid4()),
            )
            row = db.get(AgentRun, run.id)
            row.status = "waiting_for_subagents"
            db.commit()
            with pytest.raises(Exception, match="(?i)(unique|duplicate)"):
                clone = {
                    column.name: getattr(row, column.name) for column in AgentRun.__table__.columns
                }
                clone["id"] = str(uuid4())
                db.add(AgentRun(**clone))
                db.commit()
            db.rollback()
            assert not db.query(AgentSubagentTask).count()
            row = db.get(AgentRun, run.id)
            row.status = "cancelled"
            db.commit()
        database.close()
    finally:
        if admin:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()
