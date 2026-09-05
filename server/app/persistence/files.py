"""Durable attachment retirement; the local collector retries interrupted deletes."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import FileResource


def retire_agent_session_attachments(db: Session, *, tenant_id: str, session_id: str) -> int:
    rows = list(
        db.scalars(
            select(FileResource)
            .where(
                FileResource.tenant_id == tenant_id,
                FileResource.agent_session_id == session_id,
            )
            .with_for_update()
        )
    )
    for item in rows:
        item.state = "delete_pending"
        item.agent_session_id = None
    db.flush()
    return len(rows)
