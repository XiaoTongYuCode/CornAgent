"""Stable contracts for model-visible Agent tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

ToolEventEmitter = Callable[[str, Mapping[str, Any]], Awaitable[None]]
ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext"], Awaitable[Any]]
ToolStatusDetail = str | Callable[[Mapping[str, Any]], str | None] | None
ToolResultPresenter = Callable[[Any], str | None]
ToolResultProjector = Callable[[Any], Any]


class ToolContractError(ValueError):
    """Raised when a model call or handler result violates a tool contract."""

    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


@dataclass(frozen=True, slots=True)
class ToolApproval:
    """Server-generated question and private, resumable execution payload."""

    query: str
    payload: dict[str, Any]
    approve_label: str = "确认"
    cancel_label: str = "取消"

    @property
    def options(self) -> list[dict[str, str]]:
        return [
            {"content": self.approve_label, "description": ""},
            {"content": self.cancel_label, "description": ""},
        ]


@dataclass(slots=True)
class ToolExecutionContext:
    """Request-scoped dependencies; durable state belongs in checkpoint_state."""

    tenant_id: str | None = None
    owner_membership_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    worker_id: str | None = None
    fence: int | None = None
    tool_call_id: str | None = None
    batch_id: str | None = None
    execution_scope: Literal["root", "child"] = "root"
    child_task_id: str | None = None
    cancel_event: asyncio.Event | None = None
    emit_event: ToolEventEmitter | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    checkpoint_state: dict[str, Any] = field(default_factory=dict)
    runtime_cache: dict[str, Any] = field(default_factory=dict)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError

    def for_tool(self, *, tool_call_id: str, batch_id: str) -> ToolExecutionContext:
        """Create a call view while sharing Run-scoped mutable state and cache."""

        return ToolExecutionContext(
            tenant_id=self.tenant_id,
            owner_membership_id=self.owner_membership_id,
            session_id=self.session_id,
            run_id=self.run_id,
            worker_id=self.worker_id,
            fence=self.fence,
            tool_call_id=tool_call_id,
            batch_id=batch_id,
            execution_scope=self.execution_scope,
            child_task_id=self.child_task_id,
            cancel_event=self.cancel_event,
            emit_event=self.emit_event,
            extra=self.extra,
            checkpoint_state=self.checkpoint_state,
            runtime_cache=self.runtime_cache,
        )


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler
    strict: bool = True
    status_label: str | None = None
    status_detail: ToolStatusDetail = None
    runtime_handler: str | None = None
    exclusive: bool = False
    approval_handler: ToolHandler | None = None
    arguments_model: type[BaseModel] | None = None
    result_model: type[BaseModel] | None = None
    result_presenter: ToolResultPresenter | None = None
    private_result: bool = False
    result_projector: ToolResultProjector | None = None
    execution_scopes: frozenset[str] = frozenset({"root"})
    read_only: bool = False

    def __post_init__(self) -> None:
        if self.approval_handler is not None:
            if self.runtime_handler not in {None, "tool_approval"} or self.private_result:
                raise ValueError(
                    "Approval tools require public results and the tool_approval handler."
                )
            object.__setattr__(self, "runtime_handler", "tool_approval")
            object.__setattr__(self, "exclusive", True)
        if not self.execution_scopes or not self.execution_scopes <= {"root", "child"}:
            raise ValueError("Tool execution_scopes must contain root and/or child.")
        if "child" in self.execution_scopes and (
            not self.read_only or self.runtime_handler is not None or self.exclusive
        ):
            raise ValueError("Child tools must be read-only ordinary tools.")
        if not self.name.strip():
            raise ValueError("Agent tool name must not be empty.")
        if not self.description.strip():
            raise ValueError(f"Agent tool {self.name!r} requires a description.")
        if self.runtime_handler is not None and not self.runtime_handler.strip():
            raise ValueError(f"Agent tool {self.name!r} has an empty runtime handler key.")

    def build_status(self, arguments: Mapping[str, Any]) -> dict[str, str]:
        status = (self.status_label or "").strip()
        if not status:
            return {}
        detail_source = self.status_detail
        if callable(detail_source):
            try:
                detail = detail_source(arguments)
            except Exception:  # noqa: BLE001 - status text must never break execution
                detail = None
        else:
            detail = detail_source
        payload = {"status": status}
        if isinstance(detail, str) and detail.strip():
            payload["detail"] = detail.strip()
        return payload

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self.arguments_model is None:
            return dict(arguments)
        try:
            value = self.arguments_model.model_validate(dict(arguments))
        except ValidationError as exc:
            raise ToolContractError(
                "arguments",
                _validation_message(exc),
            ) from exc
        return value.model_dump(mode="json", exclude_none=True)

    def validate_result(self, result: Any) -> Any:
        if isinstance(result, ToolApproval):
            if self.approval_handler is None:
                raise ToolContractError("result", "This tool has no approval handler.")
            return result
        if self.result_model is None:
            return result
        try:
            value = self.result_model.model_validate(result)
        except ValidationError as exc:
            raise ToolContractError(
                "result",
                _validation_message(exc),
            ) from exc
        return value.model_dump(mode="json", exclude_none=True)

    def present_result(self, result: Any, fallback: str) -> str:
        if self.result_presenter is None:
            return fallback
        try:
            presented = self.result_presenter(result)
        except Exception:  # noqa: BLE001 - display projection must not break a tool run
            return fallback
        return presented.strip() if isinstance(presented, str) and presented.strip() else fallback

    def project_result(self, result: Any) -> Any:
        """Return the public, durable projection used by parts and checkpoints."""

        if self.result_projector is None:
            return None if self.private_result else result
        try:
            return self.result_projector(result)
        except Exception:  # noqa: BLE001 - private results must fail closed
            return None if self.private_result else result

    def to_provider_tool(self) -> dict[str, Any]:
        function: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }
        if self.strict:
            function["strict"] = True
        return {"type": "function", "function": function}


def _validation_message(exc: ValidationError) -> str:
    issues: list[str] = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(item) for item in error.get("loc", ())) or "value"
        issues.append(f"{location}: {error.get('msg', 'invalid value')}")
    return "; ".join(issues) or "invalid tool payload"
