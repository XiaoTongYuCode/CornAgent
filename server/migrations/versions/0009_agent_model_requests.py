"""Durable, content-free model request diagnostics."""

import sqlalchemy as sa
from alembic import op

revision = "0009_agent_model_requests"
down_revision = "0008_agent_materials"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cornagent_agent_model_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("cornagent_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_model_requests_run_sequence"),
    )
    op.create_index(
        "ix_cornagent_agent_model_requests_run_id",
        "cornagent_agent_model_requests",
        ["run_id"],
    )


def downgrade():
    op.drop_index(
        "ix_cornagent_agent_model_requests_run_id",
        table_name="cornagent_agent_model_requests",
    )
    op.drop_table("cornagent_agent_model_requests")
