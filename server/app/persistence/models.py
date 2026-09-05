from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class AgentSession(Base):
    __tablename__ = "cornagent_agent_sessions"
    __table_args__ = (
        Index(
            "ix_cornagent_agent_sessions_owner_updated",
            "tenant_id",
            "owner_membership_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_membership_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    active_leaf_message_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentMessage(Base):
    __tablename__ = "cornagent_agent_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_cornagent_agent_messages_role",
        ),
        CheckConstraint(
            "version_index >= 1",
            name="ck_cornagent_agent_messages_version_index",
        ),
        UniqueConstraint(
            "version_group_id",
            "version_index",
            name="uq_cornagent_agent_message_version",
        ),
        Index(
            "ix_cornagent_agent_messages_session_created",
            "session_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_membership_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_parts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    provider_messages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    parent_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("cornagent_agent_messages.id", ondelete="SET NULL")
    )
    version_group_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("cornagent_agent_messages.id", ondelete="SET NULL")
    )
    process_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    process_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentMessageFile(Base):
    __tablename__ = "cornagent_agent_message_files"
    __table_args__ = (
        CheckConstraint(
            "position >= 0",
            name="ck_cornagent_agent_message_files_position",
        ),
        UniqueConstraint(
            "message_id",
            "position",
            name="uq_cornagent_agent_message_file_position",
        ),
        Index(
            "ix_cornagent_agent_message_files_file_id",
            "file_id",
        ),
    )

    message_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AgentRun(Base):
    __tablename__ = "cornagent_agent_runs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('create', 'regenerate')",
            name="ck_cornagent_agent_runs_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting_for_user', "
            "'waiting_for_subagents', 'cancelling', "
            "'completed', 'failed', 'cancelled')",
            name="ck_cornagent_agent_runs_status",
        ),
        CheckConstraint("attempt >= 0", name="ck_cornagent_agent_runs_attempt"),
        CheckConstraint("stream_epoch >= 1", name="ck_cornagent_agent_runs_stream_epoch"),
        CheckConstraint("next_sequence >= 1", name="ck_cornagent_agent_runs_next_sequence"),
        Index(
            "uq_cornagent_agent_runs_active_session",
            "session_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'running', 'waiting_for_user', "
                "'waiting_for_subagents', 'cancelling')"
            ),
            sqlite_where=text(
                "status IN ('pending', 'running', 'waiting_for_user', "
                "'waiting_for_subagents', 'cancelling')"
            ),
        ),
        Index(
            "ix_cornagent_agent_runs_recovery",
            "status",
            "lease_expires_at",
            "created_at",
        ),
        Index(
            "ix_cornagent_agent_runs_assistant_message_id",
            "assistant_message_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_membership_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_message_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_message_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    draft_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reasoning_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_parts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    provider_usage: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    checkpoint_revision: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    subagent_completion_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cancel_epoch: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stream_epoch: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_fence: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_wait_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentSubagentTask(Base):
    """Durable child queue and inbox; one immutable result per task."""

    __tablename__ = "cornagent_subagent_tasks"
    __table_args__ = (
        UniqueConstraint("root_run_id", "group_id", "ordinal", name="uq_cornagent_child_ordinal"),
        UniqueConstraint("root_run_id", "group_id", "task_key", name="uq_cornagent_child_key"),
        UniqueConstraint("root_run_id", "completion_seq", name="uq_cornagent_child_completion"),
        CheckConstraint(
            (
                "status IN ('queued', 'running', 'completed', 'fa"
                "iled', 'needs_input', 'cancelled', 'timed_out')"
            ),
            name="ck_cornagent_child_status",
        ),
        CheckConstraint(
            "profile IN ('researcher', 'analyst', 'verifier')", name="ck_cornagent_child_profile"
        ),
        CheckConstraint(
            "delivery_status IN ('pending', 'delivered', 'ignored')",
            name="ck_cornagent_child_delivery",
        ),
        CheckConstraint(
            "ordinal >= 0 AND attempt_count >= 0 AND lease_fence >= 0",
            name="ck_cornagent_child_counters",
        ),
        Index("ix_cornagent_child_recovery", "status", "lease_expires_at", "deadline_at"),
        Index("ix_cornagent_child_root_status", "root_run_id", "status", "delivery_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    root_run_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    task_key: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    task_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_payload: Mapped[dict | None] = mapped_column(JSON)
    completion_seq: Mapped[int | None] = mapped_column(BigInteger)
    delivery_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    delivery_checkpoint_revision: Mapped[int | None] = mapped_column(BigInteger)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_fence: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    root_cancel_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentQuestion(Base):
    __tablename__ = "cornagent_agent_questions"
    __table_args__ = (
        CheckConstraint(
            "tool_name = 'ask_user'",
            name="ck_cornagent_agent_questions_tool_name",
        ),
        CheckConstraint(
            "status IN ('pending', 'answered', 'cancelled')",
            name="ck_cornagent_agent_questions_status",
        ),
        UniqueConstraint(
            "run_id",
            "tool_call_id",
            name="uq_cornagent_agent_question_tool_call",
        ),
        Index(
            "uq_cornagent_agent_questions_pending_run",
            "run_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_membership_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("cornagent_agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), default="ask_user", nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    selected_option_id: Mapped[str | None] = mapped_column(String(64))
    answer_content: Mapped[str | None] = mapped_column(Text)
    tool_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    resume_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_idempotency_key: Mapped[str | None] = mapped_column(String(160))
    response_request_hash: Mapped[str | None] = mapped_column(String(64))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FileResource(Base):
    __tablename__ = "cornagent_files"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'stored', 'ready', 'delete_pending', 'deleted')",
            name="ck_cornagent_files_state",
        ),
        CheckConstraint(
            "state <> 'ready' OR agent_session_id IS NOT NULL", name="ck_cornagent_files_owner"
        ),
        CheckConstraint("purpose = 'session_attachment'", name="ck_cornagent_files_purpose"),
        CheckConstraint(
            "inspection_status IN ('pending', 'validated', 'rejected', 'error')",
            name="ck_cornagent_files_inspection_status",
        ),
        CheckConstraint(
            "extraction_status IN ('not_requested', 'pending', 'ready', 'failed')",
            name="ck_cornagent_files_extraction_status",
        ),
        CheckConstraint(
            "extraction_status <> 'ready' OR "
            "(extracted_markdown IS NOT NULL AND extraction_parser IS NOT NULL "
            "AND extraction_parser_version IS NOT NULL AND extracted_sha256 IS NOT NULL "
            "AND extracted_size_bytes IS NOT NULL)",
            name="ck_cornagent_files_extracted_content",
        ),
        # Verified content is what makes an upload promotable, so a claim can
        # never turn an empty `pending` row into a referenceable File.
        CheckConstraint(
            "state NOT IN ('stored', 'ready') OR (sha256 IS NOT NULL AND size_bytes IS NOT NULL)",
            name="ck_cornagent_files_content",
        ),
        Index(
            "ix_cornagent_files_unclaimed",
            "state",
            "created_at",
        ),
        Index(
            "ix_cornagent_files_agent_session_state",
            "tenant_id",
            "agent_session_id",
            "state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(32), default="session_attachment", nullable=False)
    agent_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("cornagent_agent_sessions.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(320), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    inspection_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    extraction_status: Mapped[str] = mapped_column(
        String(24), default="not_requested", nullable=False
    )
    extracted_markdown: Mapped[str | None] = mapped_column(Text)
    extraction_parser: Mapped[str | None] = mapped_column(String(64))
    extraction_parser_version: Mapped[str | None] = mapped_column(String(32))
    extracted_sha256: Mapped[str | None] = mapped_column(String(64))
    extracted_size_bytes: Mapped[int | None] = mapped_column(Integer)
    extraction_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extraction_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
