"""Immutable tool receipts and session materials."""

import sqlalchemy as sa
from alembic import op

revision = "0008_agent_materials"
down_revision = "0007_agent_inputs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cornagent_agent_tool_receipts",
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
        sa.Column("call_id", sa.String(240), nullable=False),
        sa.Column("tool_name", sa.String(160), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("private_result", sa.Boolean(), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("source_truncated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "call_id", name="uq_agent_receipts_run_call"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_agent_receipts_size"),
    )
    op.create_index(
        "ix_agent_receipts_session_created",
        "cornagent_agent_tool_receipts",
        ["session_id", "created_at", "id"],
    )


def downgrade():
    op.drop_table("cornagent_agent_tool_receipts")
