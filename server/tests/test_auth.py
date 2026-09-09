"""Public auth flows, real WebAuthn signatures and cross-user resource boundaries."""

import hashlib
import json
import secrets
import time
from contextlib import contextmanager

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url as b64

from app.auth.models import Challenge, LoginSession, User
from app.auth.provider import COOKIE, DEVICE_COOKIE
from app.main import create_app
from app.settings import Settings
from tests.test_files import pdf_bytes, upload
from tests.test_lifecycle import start, wait_run
from tests.test_runtime import FakeAgentEventStream, FinalAgentModel

ORIGIN = "http://localhost:5173"
PASSWORD = "a long test password!"


class Mailbox:
    def __init__(self):
        self.messages = []

    def send_code(self, recipient, code):
        self.messages.append((recipient, code))


@pytest.fixture
def auth_client(settings):
    settings.users_enabled = True
    settings.auth_secret = SecretStr("test-secret-" * 4)
    settings.auth_cookie_secure = False
    settings.auth_origin = ORIGIN
    mailbox = Mailbox()

    @contextmanager
    def factory(mode="account", ip="127.0.0.1"):
        settings.auth_mode = mode
        app = create_app(
            settings,
            model_client=FinalAgentModel(),
            event_stream=FakeAgentEventStream(),
            email_sender=mailbox,
        )
        with TestClient(app, client=(ip, 1234), headers={"Origin": ORIGIN}) as client:
            client.mailbox = mailbox
            yield client

    return factory


def code_login(client, email="alice@example.com", password=PASSWORD):
    response = client.post("/api/v1/auth/email/code", json={"email": email})
    assert response.status_code == 200, response.text
    body = {"challenge_id": response.json()["challenge_id"], "code": client.mailbox.messages[-1][1]}
    if password is not None:
        body["password"] = password
    response = client.post("/api/v1/auth/email/verify", json=body)
    assert response.status_code == 200, response.text
    return response.json()["user_id"], body


def test_default_disabled_has_no_cookie_and_no_account_api(client_factory):
    with client_factory() as client:
        result = client.post("/api/v1/auth/session")
        assert result.json() == {"enabled": False, "mode": None, "user_id": "local"}
        assert not result.cookies
        assert (
            client.post("/api/v1/auth/email/code", json={"email": "a@example.com"}).status_code
            == 404
        )
        assert client.get("/api/v1/agent/sessions").status_code == 200


def test_invisible_scope_cookie_ip_and_forged_headers(auth_client):
    with auth_client("invisible") as client:
        assert client.get("/api/v1/agent/sessions").status_code == 401
        bootstrap = client.post("/api/v1/auth/session")
        owner = bootstrap.json()["user_id"]
        token = client.cookies[DEVICE_COOKIE]
        assert "HttpOnly" in bootstrap.headers["set-cookie"]
        assert "SameSite=strict" in bootstrap.headers["set-cookie"]
        assert client.post("/api/v1/auth/session").json()["user_id"] == owner
        assert (
            client.post("/api/v1/auth/session", headers={"X-Forwarded-For": "1.2.3.4"}).json()[
                "user_id"
            ]
            == owner
        )
        started = start(client)
        session_id = started["session"]["id"]
        wait_run(client, session_id)
        client.cookies.clear()
        assert client.post("/api/v1/auth/session").json()["user_id"] != owner
        assert client.get(f"/api/v1/agent/sessions/{session_id}").status_code == 404
    with auth_client("invisible", "127.0.0.2") as client:
        client.cookies.set(DEVICE_COOKIE, token)
        assert client.post("/api/v1/auth/session").json()["user_id"] != owner
        assert client.get(f"/api/v1/agent/sessions/{session_id}").status_code == 404
    with auth_client("invisible") as client:
        client.cookies.set(DEVICE_COOKIE, token)
        assert client.get(f"/api/v1/agent/sessions/{session_id}").status_code == 200
        client.cookies.clear()
        client.cookies.set(DEVICE_COOKIE, "a" * 129)
        assert client.get("/api/v1/agent/sessions").status_code == 401


def test_account_password_logout_replay_and_isolation(auth_client):
    with auth_client() as client:
        alice, body = code_login(client)
        token = client.cookies[COOKIE]
        assert client.post("/api/v1/auth/email/verify", json=body).status_code == 401
        file_id = upload(client, pdf_bytes())
        started = start(client)
        session_id, run_id = started["session"]["id"], started["run"]["id"]
        wait_run(client, session_id)
        assert client.post("/api/v1/auth/logout").status_code == 200
        client.cookies.set(COOKIE, token)
        assert client.get("/api/v1/agent/sessions").status_code == 401
        client.cookies.clear()
        bob, _ = code_login(client, "bob@example.com")
        assert bob != alice
        for path in [
            f"agent/sessions/{session_id}",
            f"agent/runs/{run_id}/stream",
            f"files/{file_id}/content",
        ]:
            assert client.get("/api/v1/" + path).status_code == 404
        assert client.delete(f"/api/v1/agent/sessions/{session_id}").status_code == 404
        response = client.post(
            "/api/v1/auth/password/login", json={"email": "alice@example.com", "password": "wrong"}
        )
        assert response.status_code == 401
        response = client.post(
            "/api/v1/auth/password/login", json={"email": "ALICE@example.com", "password": PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == alice
        assert client.get(f"/api/v1/agent/sessions/{session_id}").status_code == 200
        with client.app.state.database.session_factory() as db:
            user = db.get(User, alice)
            assert user.password_hash.startswith("$argon2id$")
            assert PASSWORD not in user.password_hash
            assert all(
                row.token_hash != client.cookies[COOKIE] for row in db.scalars(select(LoginSession))
            )


def test_code_binding_attempt_limit_expiry_and_delivery_throttle(auth_client):
    with auth_client() as client:
        response = client.post("/api/v1/auth/email/code", json={"email": "alice@example.com"})
        challenge = response.json()["challenge_id"]
        correct = client.mailbox.messages[-1][1]
        wrong = "000001" if correct == "000000" else "000000"
        for _ in range(5):
            assert (
                client.post(
                    "/api/v1/auth/email/verify", json={"challenge_id": challenge, "code": wrong}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/v1/auth/email/verify", json={"challenge_id": challenge, "code": correct}
            ).status_code
            == 401
        )
        result = client.post("/api/v1/auth/email/code", json={"email": "alice@example.com"})
        challenge = result.json()["challenge_id"]
        correct = client.mailbox.messages[-1][1]
        saved = dict(client.cookies)
        client.cookies.clear()
        assert (
            client.post(
                "/api/v1/auth/email/verify", json={"challenge_id": challenge, "code": correct}
            ).status_code
            == 401
        )
        client.cookies.update(saved)
        with client.app.state.database.session_factory() as db:
            db.get(Challenge, challenge).expires_at = int(time.time()) - 1
            db.commit()
        assert (
            client.post(
                "/api/v1/auth/email/verify", json={"challenge_id": challenge, "code": correct}
            ).status_code
            == 401
        )
        for _ in range(3):
            assert (
                client.post(
                    "/api/v1/auth/email/code", json={"email": "alice@example.com"}
                ).status_code
                == 200
            )
        assert (
            client.post("/api/v1/auth/email/code", json={"email": "alice@example.com"}).status_code
            == 429
        )


def test_csrf_fail_closed_and_expired_session(auth_client):
    with auth_client() as client:
        assert (
            client.post(
                "/api/v1/auth/session", headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        client.headers.pop("Origin")
        assert client.post("/api/v1/auth/session").status_code == 403
        client.headers["X-CornAgent-Request"] = "1"
        assert client.post("/api/v1/auth/session").status_code == 200
        code_login(client)
        with client.app.state.database.session_factory() as db:
            for session in db.scalars(select(LoginSession)):
                session.expires_at = 0
            db.commit()
        assert client.get("/api/v1/agent/sessions").status_code == 401


def credential(
    options, private_key, credential_id, *, registration, user_id="", origin=ORIGIN, uv=True
):
    client_data = json.dumps(
        {
            "type": "webauthn.create" if registration else "webauthn.get",
            "challenge": options["challenge"],
            "origin": origin,
        }
    ).encode()
    rp_id = options["rp"]["id"] if registration else options["rpId"]
    flags = 1 | (4 if uv else 0) | (64 if registration else 0)
    auth_data = (
        hashlib.sha256(rp_id.encode()).digest()
        + bytes([flags])
        + (0 if registration else 1).to_bytes(4, "big")
    )
    if registration:
        numbers = private_key.public_key().public_numbers()
        cose = cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
        auth_data += bytes(16) + len(credential_id).to_bytes(2, "big") + credential_id + cose
        response = {
            "clientDataJSON": b64(client_data),
            "attestationObject": b64(
                cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
            ),
        }
    else:
        signature = private_key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        response = {
            "clientDataJSON": b64(client_data),
            "authenticatorData": b64(auth_data),
            "signature": b64(signature),
            "userHandle": b64(user_id.encode()),
        }
    return {
        "id": b64(credential_id),
        "rawId": b64(credential_id),
        "type": "public-key",
        "response": response,
        "clientExtensionResults": {},
    }


def test_passkey_real_registration_authentication_and_replay(auth_client):
    with auth_client() as client:
        user_id, _ = code_login(client)
        private_key = ec.generate_private_key(ec.SECP256R1())
        credential_id = secrets.token_bytes(32)
        options = client.post("/api/v1/auth/passkeys/register/options").json()
        body = {
            "challenge_id": options["challenge_id"],
            "credential": credential(
                options["options"], private_key, credential_id, registration=True
            ),
        }
        response = client.post("/api/v1/auth/passkeys/register/verify", json=body)
        assert response.status_code == 200, response.text
        assert client.post("/api/v1/auth/passkeys/register/verify", json=body).status_code == 401
        client.post("/api/v1/auth/logout")
        options = client.post("/api/v1/auth/passkeys/login/options").json()
        body = {
            "challenge_id": options["challenge_id"],
            "credential": credential(
                options["options"], private_key, credential_id, registration=False, user_id=user_id
            ),
        }
        response = client.post("/api/v1/auth/passkeys/login/verify", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == user_id
        assert client.post("/api/v1/auth/passkeys/login/verify", json=body).status_code == 401


@pytest.mark.parametrize("origin,uv", [("https://evil.example", True), (ORIGIN, False)])
def test_passkey_rejects_wrong_origin_or_missing_uv(auth_client, origin, uv):
    with auth_client() as client:
        code_login(client)
        options = client.post("/api/v1/auth/passkeys/register/options").json()
        signed = credential(
            options["options"],
            ec.generate_private_key(ec.SECP256R1()),
            secrets.token_bytes(32),
            registration=True,
            origin=origin,
            uv=uv,
        )
        body = {"challenge_id": options["challenge_id"], "credential": signed}
        assert client.post("/api/v1/auth/passkeys/register/verify", json=body).status_code == 401


def test_enabled_configuration_is_fail_closed():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, users_enabled=True)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            users_enabled=True,
            auth_secret="x" * 32,
            auth_origin="http://example.com",
        )
    assert not Settings(_env_file=None).users_enabled


def test_passkey_registration_requires_recent_login(auth_client):
    with auth_client() as client:
        code_login(client)
        with client.app.state.database.session_factory() as db:
            for session in db.scalars(select(LoginSession)):
                session.authenticated_at = int(time.time()) - 601
            db.commit()
        assert client.post("/api/v1/auth/passkeys/register/options").status_code == 401
        assert client.get("/api/v1/agent/sessions").status_code == 200


def test_password_reset_revokes_other_sessions(auth_client):
    with auth_client() as client:
        user, _ = code_login(client)
        old_cookie = client.cookies[COOKIE]
        new_user, _ = code_login(client, password="a replacement password!")
        assert new_user == user
        client.cookies.clear()
        client.cookies.set(COOKIE, old_cookie)
        assert client.get("/api/v1/agent/sessions").status_code == 401
        assert (
            client.post(
                "/api/v1/auth/password/login",
                json={"email": "alice@example.com", "password": PASSWORD},
            ).status_code
            == 401
        )


def test_concurrent_code_consumption_has_one_winner(auth_client):
    from concurrent.futures import ThreadPoolExecutor

    with auth_client() as client:
        result = client.post("/api/v1/auth/email/code", json={"email": "alice@example.com"})
        body = {
            "challenge_id": result.json()["challenge_id"],
            "code": client.mailbox.messages[-1][1],
        }
        cookies = dict(client.cookies)

        # Independent requests share only the initial browser binding.
        def verify(_):
            other = TestClient(client.app, headers={"Origin": ORIGIN}, cookies=cookies)
            try:
                return other.post("/api/v1/auth/email/verify", json=body).status_code
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(verify, range(2))) == [200, 401]


def test_revocation_during_passkey_verification_prevents_registration(auth_client, monkeypatch):
    from sqlalchemy import delete

    from app.auth import routes

    with auth_client() as client:
        code_login(client)
        options = client.post("/api/v1/auth/passkeys/register/options").json()
        signed = credential(
            options["options"],
            ec.generate_private_key(ec.SECP256R1()),
            secrets.token_bytes(32),
            registration=True,
        )
        original = routes.verify_registration_response

        def revoke(**kwargs):
            result = original(**kwargs)
            with client.app.state.database.session_factory() as db:
                db.execute(delete(LoginSession))
                db.commit()
            return result

        monkeypatch.setattr(routes, "verify_registration_response", revoke)
        assert (
            client.post(
                "/api/v1/auth/passkeys/register/verify",
                json={
                    "challenge_id": options["challenge_id"],
                    "credential": signed,
                },
            ).status_code
            == 401
        )


def test_eight_character_password_registration_and_login(auth_client):
    with auth_client() as client:
        email = "eight@example.com"
        result = client.post("/api/v1/auth/email/code", json={"email": email})
        body = {
            "challenge_id": result.json()["challenge_id"],
            "code": client.mailbox.messages[-1][1],
            "password": "1234567",
        }
        assert client.post("/api/v1/auth/email/verify", json=body).status_code == 422
        body["password"] = "12345678"
        assert client.post("/api/v1/auth/email/verify", json=body).status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 200
        assert client.post(
            "/api/v1/auth/password/login", json={"email": email, "password": "12345678"}
        ).status_code == 200


def test_agent_status_explains_missing_model_independently_of_event_stream(auth_client):
    with auth_client() as client:
        code_login(client)
        runtime = client.app.state.agent_runtime
        runtime.model_client = None
        status = client.get("/api/v1/agent/status").json()
        assert status["available"] is False
        assert status["unavailable_reason"] == "model_not_configured"
