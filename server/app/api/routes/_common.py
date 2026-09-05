from typing import Annotated

from fastapi import Header

from app.persistence.errors import DomainError

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=160)]


def require_idempotency_key(value: str | None) -> str:
    if not value or not value.strip():
        raise DomainError(
            "idempotency_key_required", "Idempotency-Key is required.", status_code=400
        )
    return value
