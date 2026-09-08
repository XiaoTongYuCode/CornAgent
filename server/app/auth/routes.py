"""Self-contained account ceremonies; all challenges and sessions are server-owned."""

import hmac
import json
import secrets
import time
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.auth.models import Challenge, LoginSession, Passkey, RateBucket, User
from app.auth.provider import (
    COOKIE,
    BuiltinIdentityProvider,
    client_ip,
    cookie,
    denied,
    digest,
    keyed,
)
from app.persistence.errors import DomainError

router = APIRouter(prefix="/auth", tags=["authentication"])
passwords = PasswordHasher()
DUMMY_PASSWORD = passwords.hash(secrets.token_urlsafe(32))
CHALLENGE_COOKIE = "cornagent_challenge"


class EmailInput(BaseModel):
    email: EmailStr = Field(max_length=254)

    @property
    def normalized_email(self):
        return str(self.email).casefold()


class PasswordInput(EmailInput):
    password: str = Field(min_length=1, max_length=128)


class VerifyCodeInput(BaseModel):
    challenge_id: str = Field(min_length=32, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")
    password: str | None = Field(default=None, min_length=15, max_length=128)


class CredentialInput(BaseModel):
    challenge_id: str = Field(min_length=32, max_length=64)
    credential: dict


def account_settings(request):
    s = request.app.state.settings
    if (
        not s.users_enabled
        or s.auth_mode != "account"
        or not isinstance(request.app.state.identity_provider, BuiltinIdentityProvider)
    ):
        raise denied("authentication_disabled", 404)
    return s


def insert_once(db, model, values, key):
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    db.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=[key]))


def throttle(request, action, subject="", limit=20):
    """Database counters serialize across processes; expiry bounds retained rows."""
    s = account_settings(request)
    now = int(time.time())
    window = now // 600
    with request.app.state.database.session_factory() as db:
        db.execute(delete(RateBucket).where(RateBucket.expires_at < now))
        db.execute(delete(Challenge).where(Challenge.expires_at < now))
        db.execute(delete(LoginSession).where(LoginSession.expires_at < now))
        for target in (
            ("ip:" + client_ip(request), "subject:" + subject)
            if subject
            else ("ip:" + client_ip(request),)
        ):
            key = keyed(s, f"rate:{action}:{target}:{window}")
            insert_once(
                db, RateBucket, dict(id=key, attempts=0, expires_at=(window + 1) * 600), "id"
            )
            row = db.scalar(select(RateBucket).where(RateBucket.id == key).with_for_update())
            if row.attempts >= limit:
                db.commit()
                raise denied("authentication_rate_limited", 429)
            row.attempts += 1
        db.commit()


def session_result(request, identity):
    return {
        "enabled": request.app.state.settings.users_enabled,
        "mode": request.app.state.settings.auth_mode
        if request.app.state.settings.users_enabled
        and isinstance(request.app.state.identity_provider, BuiltinIdentityProvider)
        else None,
        "user_id": identity.user_id if identity else None,
    }


@router.post("/session")
def bootstrap(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    provider = request.app.state.identity_provider
    try:
        identity = (
            provider.bootstrap(request, response)
            if hasattr(provider, "bootstrap")
            else provider.authenticate(request)
        )
    except DomainError as error:
        if error.status_code != 401:
            raise
        identity = None
    return session_result(request, identity)


def issue_session(request, response, db, user):
    s = request.app.state.settings
    old = request.cookies.get(COOKIE, "")
    if old:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(old)))
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=digest(token),
            user_id=user.id,
            expires_at=int(time.time()) + s.auth_session_seconds,
            authenticated_at=int(time.time()),
        )
    )
    db.commit()
    cookie(response, s, COOKIE, token, s.auth_session_seconds)
    return {"user_id": user.id}


@router.post("/logout")
def logout(request: Request, response: Response):
    account_settings(request)
    with request.app.state.database.session_factory() as db:
        db.execute(
            delete(LoginSession).where(
                LoginSession.token_hash == digest(request.cookies.get(COOKIE, ""))
            )
        )
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/email/code")
def send_code(body: EmailInput, request: Request, response: Response):
    s = account_settings(request)
    throttle(request, "email", body.normalized_email, limit=5)
    code = f"{secrets.randbelow(1000000):06d}"
    challenge_id = secrets.token_hex(32)
    binding = secrets.token_urlsafe(32)
    with request.app.state.database.session_factory() as db:
        db.add(
            Challenge(
                id=challenge_id,
                kind="email",
                subject=body.normalized_email,
                secret=keyed(s, f"{challenge_id}:{code}:{binding}"),
                expires_at=int(time.time()) + 600,
            )
        )
        db.commit()
    try:
        request.app.state.auth_email_sender.send_code(body.normalized_email, code)
    except Exception:
        with request.app.state.database.session_factory() as db:
            db.execute(delete(Challenge).where(Challenge.id == challenge_id))
            db.commit()
        raise denied("email_delivery_failed", 503) from None
    cookie(response, s, CHALLENGE_COOKIE, binding, 600)
    return {"challenge_id": challenge_id}


@router.post("/email/verify")
def verify_code(body: VerifyCodeInput, request: Request, response: Response):
    s = account_settings(request)
    throttle(request, "verify")
    with request.app.state.database.session_factory() as db:
        challenge = db.scalar(
            select(Challenge).where(Challenge.id == body.challenge_id).with_for_update()
        )
        if (
            not challenge
            or challenge.kind != "email"
            or challenge.expires_at <= time.time()
            or challenge.attempts >= 5
        ):
            raise denied("invalid_verification")
        challenge.attempts += 1
        binding = request.cookies.get(CHALLENGE_COOKIE, "")
        if not binding or not hmac.compare_digest(
            challenge.secret, keyed(s, f"{body.challenge_id}:{body.code}:{binding}")
        ):
            db.commit()
            raise denied("invalid_verification")
        email = challenge.subject
        db.delete(challenge)
        insert_once(db, User, {"email": email}, "email")
        user = db.scalar(select(User).where(User.email == email).with_for_update())
        if body.password is not None:
            user.password_hash = passwords.hash(body.password)
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        result = issue_session(request, response, db, user)
    response.delete_cookie(CHALLENGE_COOKIE, path="/")
    return result


@router.post("/password/login")
def password_login(body: PasswordInput, request: Request, response: Response):
    account_settings(request)
    throttle(request, "password", body.normalized_email)
    with request.app.state.database.session_factory() as db:
        user = db.scalar(select(User).where(User.email == body.normalized_email).with_for_update())
        try:
            passwords.verify(
                user.password_hash if user and user.password_hash else DUMMY_PASSWORD, body.password
            )
        except VerificationError:
            raise denied("invalid_credentials") from None
        if not user or not user.password_hash:
            raise denied("invalid_credentials")
        return issue_session(request, response, db, user)


def create_ceremony(request, response, kind, subject, options):
    challenge_id = secrets.token_hex(32)
    with request.app.state.database.session_factory() as db:
        db.add(
            Challenge(
                id=challenge_id,
                kind=kind,
                subject=subject,
                secret=bytes_to_base64url(options.challenge),
                expires_at=int(time.time()) + 300,
            )
        )
        db.commit()
    cookie(response, request.app.state.settings, CHALLENGE_COOKIE, challenge_id, 300)
    return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}


def consume_ceremony(request, body, kind):
    if request.cookies.get(CHALLENGE_COOKIE) != body.challenge_id:
        raise denied("invalid_verification")
    with request.app.state.database.session_factory() as db:
        row = db.scalar(
            select(Challenge).where(Challenge.id == body.challenge_id).with_for_update()
        )
        if not row or row.kind != kind or row.expires_at <= time.time():
            raise denied("invalid_verification")
        result = (row.subject, base64url_to_bytes(row.secret))
        db.delete(row)
        db.commit()
        return result


def require_recent_login(request, db):
    session = db.scalar(
        select(LoginSession)
        .where(LoginSession.token_hash == digest(request.cookies.get(COOKIE, "")))
        .with_for_update()
    )
    if (
        not session
        or session.expires_at <= time.time()
        or session.authenticated_at < time.time() - 600
    ):
        raise denied("reauthentication_required")


@router.post("/passkeys/register/options")
def registration_options(request: Request, response: Response):
    s = account_settings(request)
    identity = request.app.state.identity_provider.authenticate(request)
    throttle(request, "passkey-register", identity.user_id)
    with request.app.state.database.session_factory() as db:
        require_recent_login(request, db)
        user = db.get(User, identity.user_id)
        keys = db.scalars(select(Passkey).where(Passkey.user_id == user.id)).all()
        options = generate_registration_options(
            rp_id=urlsplit(s.auth_origin).hostname,
            rp_name="CornAgent",
            user_name=user.email,
            user_id=user.id.encode(),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(k.id)) for k in keys
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
    return create_ceremony(request, response, "register", identity.user_id, options)


@router.post("/passkeys/register/verify")
def registration_verify(body: CredentialInput, request: Request):
    s = account_settings(request)
    identity = request.app.state.identity_provider.authenticate(request)
    subject, challenge = consume_ceremony(request, body, "register")
    if subject != identity.user_id:
        raise denied("invalid_verification")
    try:
        result = verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=urlsplit(s.auth_origin).hostname,
            expected_origin=s.auth_origin,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise denied("invalid_verification") from None
    with request.app.state.database.session_factory() as db:
        require_recent_login(request, db)
        key_id = bytes_to_base64url(result.credential_id)
        # A credential cannot silently transfer ownership.
        if db.get(Passkey, key_id):
            raise denied("invalid_verification")
        db.add(
            Passkey(
                id=key_id,
                user_id=subject,
                public_key=bytes_to_base64url(result.credential_public_key),
                sign_count=result.sign_count,
                transports=[],
            )
        )
        db.commit()
    return {"ok": True}


@router.post("/passkeys/login/options")
def authentication_options(request: Request, response: Response):
    s = account_settings(request)
    throttle(request, "passkey-login")
    options = generate_authentication_options(
        rp_id=urlsplit(s.auth_origin).hostname,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return create_ceremony(request, response, "login", "", options)


@router.post("/passkeys/login/verify")
def authentication_verify(body: CredentialInput, request: Request, response: Response):
    s = account_settings(request)
    _, challenge = consume_ceremony(request, body, "login")
    with request.app.state.database.session_factory() as db:
        key = db.scalar(
            select(Passkey).where(Passkey.id == body.credential.get("id", "")).with_for_update()
        )
        if not key:
            raise denied("invalid_verification")
        try:
            result = verify_authentication_response(
                credential=body.credential,
                expected_challenge=challenge,
                expected_rp_id=urlsplit(s.auth_origin).hostname,
                expected_origin=s.auth_origin,
                credential_public_key=base64url_to_bytes(key.public_key),
                credential_current_sign_count=key.sign_count,
                require_user_verification=True,
            )
            handle = body.credential.get("response", {}).get("userHandle")
            if not handle or base64url_to_bytes(handle) != key.user_id.encode():
                raise ValueError("Invalid user handle")
        except (WebAuthnException, ValueError, KeyError, TypeError):
            raise denied("invalid_verification") from None
        key.sign_count = result.new_sign_count
        user = db.scalar(select(User).where(User.id == key.user_id).with_for_update())
        return issue_session(request, response, db, user)
