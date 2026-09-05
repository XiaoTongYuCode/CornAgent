"""Durable subagents, waiting state and cancellation fencing.

Revision ID: 0002_subagents
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_subagents"
down_revision = "0001"
branch_labels = None
depends_on = None

ACTIVE = (
    "status IN ('pending', 'running', 'waiting_for_user', 'waiting_for_subagents', 'cancelling')"
)
STATUS = (
    "status IN ('pending', 'running', 'waiting_for_user', 'waiting_for_subagents', "
    "'cancelling', 'completed', 'failed', 'cancelled')"
)


def upgrade():
    with op.batch_alter_table("cornagent_agent_runs") as batch:
        batch.add_column(
            sa.Column("checkpoint_revision", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column(
                "subagent_completion_seq", sa.BigInteger(), nullable=False, server_default="0"
            )
        )
        batch.add_column(
            sa.Column("cancel_epoch", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.drop_constraint("ck_cornagent_agent_runs_status", type_="check")
        batch.create_check_constraint("ck_cornagent_agent_runs_status", STATUS)
        batch.drop_index("uq_cornagent_agent_runs_active_session")
        batch.create_index(
            "uq_cornagent_agent_runs_active_session",
            ["session_id"],
            unique=True,
            postgresql_where=sa.text(ACTIVE),
            sqlite_where=sa.text(ACTIVE),
        )
    op.create_table(
        "cornagent_subagent_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("root_run_id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("tool_call_id", sa.String(length=200), nullable=False),
        sa.Column("task_key", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(length=20), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("task_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("completion_seq", sa.BigInteger(), nullable=True),
        sa.Column("delivery_status", sa.String(length=20), nullable=False),
        sa.Column("delivery_checkpoint_revision", sa.BigInteger(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_fence", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("root_cancel_epoch", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'delivered', 'ignored')",
            name="ck_cornagent_child_delivery",
        ),
        sa.CheckConstraint(
            "profile IN ('researcher', 'analyst', 'verifier')", name="ck_cornagent_child_profile"
        ),
        sa.CheckConstraint(
            (
                "status IN ('queued', 'running', 'completed', 'failed', "
                "'needs_input', 'cancelled', 'timed_out')"
            ),
            name="ck_cornagent_child_status",
        ),
        sa.CheckConstraint(
            "ordinal >= 0 AND attempt_count >= 0 AND lease_fence >= 0",
            name="ck_cornagent_child_counters",
        ),
        sa.ForeignKeyConstraint(["root_run_id"], ["cornagent_agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("root_run_id", "completion_seq", name="uq_cornagent_child_completion"),
        sa.UniqueConstraint(
            "root_run_id", "group_id", "ordinal", name="uq_cornagent_child_ordinal"
        ),
        sa.UniqueConstraint("root_run_id", "group_id", "task_key", name="uq_cornagent_child_key"),
    )
    op.create_index(
        "ix_cornagent_child_recovery",
        "cornagent_subagent_tasks",
        ["status", "lease_expires_at", "deadline_at"],
        unique=False,
    )
    op.create_index(
        "ix_cornagent_child_root_status",
        "cornagent_subagent_tasks",
        ["root_run_id", "status", "delivery_status"],
        unique=False,
    )


def downgrade():
    # Active child runs cannot be represented by the earlier schema.
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM cornagent_agent_runs r "
            "WHERE r.status = 'waiting_for_subagents' OR ("
            "r.status IN ('pending', 'running', 'waiting_for_user', 'cancelling') "
            "AND EXISTS (SELECT 1 FROM cornagent_subagent_tasks t WHERE t.root_run_id = r.id))"
        )
    ).scalar():
        raise RuntimeError("Finish or cancel all runs with subagents before downgrading.")
    op.drop_table("cornagent_subagent_tasks")
    old_active = "status IN ('pending', 'running', 'waiting_for_user', 'cancelling')"
    with op.batch_alter_table("cornagent_agent_runs") as batch:
        batch.drop_index("uq_cornagent_agent_runs_active_session")
        batch.create_index(
            "uq_cornagent_agent_runs_active_session",
            ["session_id"],
            unique=True,
            postgresql_where=sa.text(old_active),
            sqlite_where=sa.text(old_active),
        )
        batch.drop_constraint("ck_cornagent_agent_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_cornagent_agent_runs_status",
            (
                "status IN ('pending', 'running', 'waiting_for_user', 'cancelling', "
                "'completed', 'failed', 'cancelled')"
            ),
        )
        batch.drop_column("checkpoint_revision")
        batch.drop_column("subagent_completion_seq")
        batch.drop_column("cancel_epoch")
