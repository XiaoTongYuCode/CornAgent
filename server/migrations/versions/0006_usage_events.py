"""Optional, payload-free usage events."""

import sqlalchemy as sa
from alembic import op

revision = "0006_usage_events"
down_revision = "0005_optional_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cornagent_usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("owner_membership_id", sa.String(36), nullable=False),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("cornagent_agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("cornagent_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("execution_scope", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_usage_owner_created",
        "cornagent_usage_events",
        ["tenant_id", "owner_membership_id", "created_at"],
    )


def downgrade():
    op.drop_table("cornagent_usage_events")
