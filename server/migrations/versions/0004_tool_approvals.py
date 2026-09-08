"""Allow durable user decisions for any registered approval-capable tool."""

import sqlalchemy as sa
from alembic import op

revision = "0004_tool_approvals"
down_revision = "0003_source_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cornagent_agent_questions") as batch:
        batch.drop_constraint("ck_cornagent_agent_questions_tool_name", type_="check")
        batch.drop_constraint("uq_cornagent_agent_question_tool_call", type_="unique")
        batch.create_check_constraint(
            "ck_cornagent_agent_questions_tool_name", "length(trim(tool_name)) > 0"
        )

    op.create_index(
        "uq_cornagent_agent_question_tool_call",
        "cornagent_agent_questions",
        ["run_id", "tool_call_id"],
        unique=True,
        postgresql_where=sa.text("tool_name = 'ask_user'"),
        sqlite_where=sa.text("tool_name = 'ask_user'"),
    )


def downgrade() -> None:
    op.drop_index("uq_cornagent_agent_question_tool_call", table_name="cornagent_agent_questions")
    with op.batch_alter_table("cornagent_agent_questions") as batch:
        batch.drop_constraint("ck_cornagent_agent_questions_tool_name", type_="check")
        batch.create_check_constraint(
            "ck_cornagent_agent_questions_tool_name", "tool_name = 'ask_user'"
        )
        batch.create_unique_constraint(
            "uq_cornagent_agent_question_tool_call", ["run_id", "tool_call_id"]
        )
