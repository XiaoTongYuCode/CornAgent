"""Replaceable request-to-Identity boundary. Never trust a client-supplied user ID."""

import hashlib
import hmac
import secrets
import time
from ipaddress import ip_address
from typing import Protocol
from uuid import UUID

from fastapi import Request, Response

from app.auth.models import LoginSession
from app.persistence.errors import DomainError
from app.persistence.scope import LOCAL_SCOPE, Identity

COOKIE = "cornagent_session"
DEVICE_COOKIE = "cornagent_device"


def denied(code="authentication_required", status=401):
    return DomainError(code, "Authentication could not be completed.", status_code=status)


def client_ip(request: Request) -> str:
    try:
        address = ip_address(request.client.host if request.client else "")
        return str(getattr(address, "ipv4_mapped", None) or address)
    except ValueError:
        return "unknown"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def keyed(settings, value: str) -> str:
    return hmac.new(
        settings.auth_secret.get_secret_value().encode(), value.encode(), "sha256"
    ).hexdigest()


def cookie(response: Response, settings, name: str, value: str, age: int):
    response.set_cookie(
        name,
        value,
        max_age=age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def user_identity(user_id: str) -> Identity:
    return Identity(user_id=user_id, tenant_id=user_id, membership_id=user_id)


class IdentityProvider(Protocol):
    def authenticate(self, request: Request) -> Identity: ...


class BuiltinIdentityProvider:
    def authenticate(self, request: Request) -> Identity:
        settings = request.app.state.settings
        if not settings.users_enabled:
            return LOCAL_SCOPE
        if settings.auth_mode == "invisible":
            token = request.cookies.get(DEVICE_COOKIE, "")
            if not self.valid_device(settings, token):
                raise denied()
            # A changed address deliberately selects another private workspace.
            owner = str(UUID(keyed(settings, f"owner:{token}:{client_ip(request)}")[:32]))
            return user_identity(owner)
        token = request.cookies.get(COOKIE, "")
        if not token or len(token) > 128:
            raise denied()
        with request.app.state.database.session_factory() as db:
            session = db.get(LoginSession, digest(token))
            if session is None or session.expires_at <= time.time():
                raise denied()
            return user_identity(session.user_id)

    @staticmethod
    def valid_device(settings, token):
        if len(token) != 129 or token[64:65] != ".":
            return False
        return hmac.compare_digest(token[65:], keyed(settings, "device:" + token[:64]))

    def bootstrap(self, request: Request, response: Response):
        settings = request.app.state.settings
        if not settings.users_enabled:
            return LOCAL_SCOPE
        if settings.auth_mode == "invisible":
            token = request.cookies.get(DEVICE_COOKIE, "")
            if not self.valid_device(settings, token):
                token = secrets.token_hex(32)
                token += "." + keyed(settings, "device:" + token)
            cookie(response, settings, DEVICE_COOKIE, token, 365 * 86400)
            owner = str(UUID(keyed(settings, f"owner:{token}:{client_ip(request)}")[:32]))
            return user_identity(owner)
        return self.authenticate(request)
