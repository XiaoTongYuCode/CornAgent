"""Public transport models for the durable CornAgent capability."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AGENT_FILE_IMAGE_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")
AGENT_FILE_PDF_MIME_TYPE = "application/pdf"
AGENT_FILE_MAX_COUNT = 4
AGENT_FILE_IMAGE_MAX_BYTES = 5 * 1024 * 1024
AGENT_FILE_PDF_MAX_BYTES = 2 * 1024 * 1024
AGENT_FILE_MAX_TOTAL_BYTES = 16 * 1024 * 1024
AGENT_FILE_IMAGE_MAX_SIDE = 8192
AGENT_FILE_IMAGE_MAX_PIXELS = 25_000_000
AGENT_FILE_PDF_MAX_COUNT = 1
AGENT_FILE_PDF_MAX_PAGES = 50
AGENT_FILE_EXTRACTED_MAX_CHARS = 200_000


class AgentContentPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["markdown", "reasoning", "tool_call", "user_question"]
    title: str | None = None
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunOut(BaseModel):
    id: str
    session_id: str
    user_message_id: str
    assistant_message_id: str
    kind: Literal["create", "regenerate"]
    status: Literal[
        "pending",
        "running",
        "waiting_for_user",
        "waiting_for_subagents",
        "cancelling",
        "completed",
        "failed",
        "cancelled",
    ]
    stream_epoch: int
    next_sequence: int
    provider_usage: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class AgentFileOut(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    content_url: str
    scope: Literal["session"] = "session"
    media_kind: Literal["image", "document"]
    inspection_status: Literal["validated"]
    extraction_status: Literal["not_requested", "ready"]


class AgentMessageOut(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    markdown: str
    attachments: list[AgentFileOut] = Field(default_factory=list)
    content_parts: list[AgentContentPart]
    run: AgentRunOut | None = None
    parent_message_id: str | None
    version_group_id: str
    version_index: int
    previous_version_id: str | None = None
    next_version_id: str | None = None
    version_count: int = 1
    supersedes_message_id: str | None
    process_started_at: datetime | None
    process_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentSessionOut(BaseModel):
    id: str
    title: str
    context: dict[str, Any]
    active_leaf_message_id: str | None
    created_at: datetime
    updated_at: datetime


class AgentSessionDetail(AgentSessionOut):
    messages: list[AgentMessageOut]
    active_run: AgentRunOut | None = None
    next_before: str | None = None


class AgentSessionList(BaseModel):
    data: list[AgentSessionOut]
    next_cursor: str | None = None


class AgentSessionDeleteResult(BaseModel):
    id: str
    deleted: bool = True


class AgentFileConstraint(BaseModel):
    mime_type: str
    max_bytes: int
    max_count: int


class AgentFileInputCapability(BaseModel):
    enabled: bool
    accepts: list[AgentFileConstraint]
    max_count: int
    max_total_bytes: int


class AgentFileRefInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1, max_length=36)


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=40_000)
    # The runtime-configured capability is authoritative; keeping transport
    # validation free of the current default lets operators lower or raise the
    # advertised limit without shipping a second schema change.
    attachments: list[AgentFileRefInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_cannot_be_blank(self) -> AgentRunCreate:
        self.content = self.content.strip()
        file_ids = [item.file_id for item in self.attachments]
        if len(set(file_ids)) != len(file_ids):
            raise ValueError("attachments cannot contain duplicate file_id values")
        if not self.content and not self.attachments:
            raise ValueError("content and attachments cannot both be empty")
        return self


class AgentSessionRunCreate(AgentRunCreate):
    title: str = Field(default="新对话", max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)


class AgentSessionRunOut(BaseModel):
    session: AgentSessionOut
    run: AgentRunOut


class AgentMessageEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=40_000)
    attachments: list[AgentFileRefInput] | None = None

    @model_validator(mode="after")
    def validate_edit(self) -> AgentMessageEdit:
        self.content = self.content.strip()
        if self.attachments is not None:
            file_ids = [item.file_id for item in self.attachments]
            if len(set(file_ids)) != len(file_ids):
                raise ValueError("attachments cannot contain duplicate file_id values")
            if not self.content and not self.attachments:
                raise ValueError("content and attachments cannot both be empty")
        return self


class AgentVersionSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=36)


class AgentQuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["answer", "cancel"]
    option_id: str | None = Field(default=None, max_length=64)
    content: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def validate_choice(self) -> AgentQuestionResponse:
        if self.action == "cancel":
            if self.option_id is not None or self.content is not None:
                raise ValueError("cancel cannot include option_id or content")
            return self
        if self.option_id is not None and self.content is not None:
            raise ValueError("answer accepts option_id or content, not both")
        if self.option_id is None:
            self.content = (self.content or "").strip()
            if not self.content:
                raise ValueError("a custom answer cannot be blank")
        return self


class AgentQuestionResult(BaseModel):
    question_id: str
    run_id: str
    status: Literal["answered", "cancelled"]
    selected_option_id: str | None
    answer_content: str | None
    stream_epoch: int
    part: AgentContentPart


class AgentStreamSnapshot(BaseModel):
    run: AgentRunOut
    draft_markdown: str
    reasoning_markdown: str
    content_parts: list[AgentContentPart]
    replace: bool = True


__all__ = [
    "AGENT_FILE_EXTRACTED_MAX_CHARS",
    "AGENT_FILE_IMAGE_MAX_BYTES",
    "AGENT_FILE_IMAGE_MAX_PIXELS",
    "AGENT_FILE_IMAGE_MAX_SIDE",
    "AGENT_FILE_IMAGE_MIME_TYPES",
    "AGENT_FILE_MAX_COUNT",
    "AGENT_FILE_MAX_TOTAL_BYTES",
    "AGENT_FILE_PDF_MAX_BYTES",
    "AGENT_FILE_PDF_MAX_COUNT",
    "AGENT_FILE_PDF_MAX_PAGES",
    "AGENT_FILE_PDF_MIME_TYPE",
    "AgentContentPart",
    "AgentFileConstraint",
    "AgentFileInputCapability",
    "AgentFileOut",
    "AgentFileRefInput",
    "AgentMessageEdit",
    "AgentMessageOut",
    "AgentQuestionResponse",
    "AgentQuestionResult",
    "AgentRunCreate",
    "AgentRunOut",
    "AgentSessionDeleteResult",
    "AgentSessionDetail",
    "AgentSessionList",
    "AgentSessionOut",
    "AgentSessionRunCreate",
    "AgentSessionRunOut",
    "AgentStreamSnapshot",
    "AgentVersionSwitch",
]
