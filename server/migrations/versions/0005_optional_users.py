"""Optional account authentication; existing shared resources retain their scope."""

import sqlalchemy as sa
from alembic import op

revision = "0005_optional_users"
down_revision = "0004_tool_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cornagent_auth_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text()),
    )
    op.create_table(
        "cornagent_auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("cornagent_auth_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("authenticated_at", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "cornagent_auth_challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(254), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_table(
        "cornagent_auth_passkeys",
        sa.Column("id", sa.String(1024), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("cornagent_auth_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("transports", sa.JSON(), nullable=False),
    )
    op.create_table(
        "cornagent_auth_rate_buckets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    for table, columns in {
        "sessions": ["user_id", "expires_at"],
        "challenges": ["expires_at"],
        "passkeys": ["user_id"],
        "rate_buckets": ["expires_at"],
    }.items():
        name = "cornagent_auth_" + table
        for column in columns:
            op.create_index(f"ix_{name}_{column}", name, [column])


def downgrade():
    for table in ("rate_buckets", "passkeys", "challenges", "sessions", "users"):
        op.drop_table("cornagent_auth_" + table)
