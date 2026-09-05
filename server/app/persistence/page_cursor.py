from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.persistence.errors import DomainError

_MAX_SIGNED_CURSOR_LENGTH = 4096


def encode_signed_cursor(payload: Mapping[str, Any], *, secret: bytes) -> str:
    """Encode an opaque, tamper-evident cursor payload.

    Scope, identity, query and expiry bindings intentionally remain payload
    concerns so every cursor consumer can define its own fail-closed contract.
    """

    if not secret:
        raise ValueError("cursor signing secret must not be empty")
    encoded_payload = _base64url_encode(
        json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def decode_signed_cursor(
    value: str,
    *,
    secret: bytes,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    """Decode a signed cursor, mapping every malformed/tampered input to 422."""

    try:
        if not secret or not value or len(value) > _MAX_SIGNED_CURSOR_LENGTH:
            raise ValueError
        encoded_payload, encoded_signature = value.split(".", 1)
        expected = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        supplied = _base64url_decode(encoded_signature)
        if not hmac.compare_digest(expected, supplied):
            raise ValueError
        payload = json.loads(_base64url_decode(encoded_payload))
        if not isinstance(payload, dict):
            raise ValueError
    except (
        AttributeError,
        binascii.Error,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise DomainError(error_code, error_message, status_code=422) from None
    return payload


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    encoded = value.encode("ascii")
    encoded += b"=" * (-len(encoded) % 4)
    decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
    if _base64url_encode(decoded) != value:
        raise ValueError("cursor base64 is not canonical")
    return decoded


def encode_page_cursor(
    kind: str,
    occurred_at: datetime,
    resource_id: str,
    *,
    scope: str,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "kind": kind,
            "scope": scope,
            "at": occurred_at.isoformat(),
            "id": resource_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_page_cursor(
    value: str,
    *,
    kind: str,
    scope: str,
    error_code: str,
    error_message: str,
) -> tuple[datetime, str]:
    try:
        encoded = value.encode("ascii")
        encoded += b"=" * (-len(encoded) % 4)
        payload = json.loads(base64.b64decode(encoded, altchars=b"-_", validate=True))
        occurred_at = datetime.fromisoformat(payload["at"])
        resource_id = payload["id"]
        if (
            payload.get("v") != 1
            or payload.get("kind") != kind
            or payload.get("scope") != scope
            or not isinstance(resource_id, str)
            or not resource_id
        ):
            raise ValueError
    except (
        AttributeError,
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
    ):
        raise DomainError(error_code, error_message, status_code=422) from None
    return occurred_at, resource_id


def normalize_cursor_time(value: datetime, *, dialect_name: str) -> datetime:
    if dialect_name == "sqlite":
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
