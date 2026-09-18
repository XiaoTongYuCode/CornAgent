"""Durable queued and steering messages."""

import sqlalchemy as sa
from alembic import op

revision = "0007_agent_inputs"
down_revision = "0006_usage_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cornagent_agent_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("cornagent_agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("file_ids", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(36)),
        sa.Column("message_id", sa.String(36)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('queue','steer')", name="ck_agent_inputs_mode"),
        sa.CheckConstraint(
            "status IN ('pending','applied','cancelled','failed')", name="ck_agent_inputs_status"
        ),
    )
    op.create_index(
        "ix_agent_inputs_pending", "cornagent_agent_inputs", ["session_id", "status", "created_at"]
    )
    op.create_table(
        "cornagent_agent_input_mutations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "input_id",
            sa.String(36),
            sa.ForeignKey("cornagent_agent_inputs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("cornagent_agent_input_mutations")
    op.drop_table("cornagent_agent_inputs")
