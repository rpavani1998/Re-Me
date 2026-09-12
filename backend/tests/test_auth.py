from datetime import timedelta
import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.domain.models import Account, LoginSession, now
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    config = Settings(database_url=f"sqlite:///{tmp_path}/auth.db", demo_mode=True,
                      google_client_id="test-client", _env_file=None)
    with TestClient(create_app(config)) as client:
        yield client


def signup(client, email="person@example.com"):
    response = client.post("/api/auth/signup", json={"email": email, "password": "a long test password"})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_login_expiry_logout_and_hashed_storage(client):
    token = signup(client, "Person@Example.com")
    response = client.get("/api/auth/me", headers=headers(token))
    assert response.json()["email"] == "person@example.com"
    assert response.headers["cache-control"] == "no-store"
    with client.app.state.sessions() as db:
        account = db.scalar(select(Account))
        assert account.password_hash != "a long test password"
        session = db.scalar(select(LoginSession))
        assert session.token_hash == hashlib.sha256(token.encode()).hexdigest()
        session.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/memories", headers=headers(token)).status_code == 401
    response = client.post("/api/auth/login", json={"email": "person@example.com", "password": "a long test password"})
    assert response.status_code == 200
    token = response.json()["token"]
    assert client.get("/api/memories", headers=headers(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=headers(token)).status_code == 204
    assert client.get("/api/memories", headers=headers(token)).status_code == 401
    assert client.get("/api/memories", headers=headers("")).status_code == 401


def test_bad_credentials_duplicate_and_validation(client):
    signup(client)
    for email in ("person@example.com", "unknown@example.com"):
        response = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password."
    assert client.post("/api/auth/signup", json={"email": "PERSON@example.com", "password": "a long test password"}).status_code == 409
    assert client.post("/api/auth/signup", json={"email": "another@example.com", "password": "short"}).status_code == 422
    assert client.post("/api/auth/signup", json={"email": "invalid", "password": "a long test password"}).status_code == 422


def test_accounts_are_isolated_and_demo_reset_preserves_login(client):
    first, second = signup(client), signup(client, "second@example.com")
    response = client.post("/api/captures", headers=headers(first), json={"request_id": "one", "visible_text": "Korean restaurant in Hyderabad.", "page_title": "Seoul Kitchen"})
    assert response.status_code == 201, response.text
    memory_id = response.json()["id"]
    assert client.get("/api/memories", headers=headers(second)).json() == []
    assert client.get(f"/api/memories/{memory_id}", headers=headers(second)).status_code == 404
    assert client.post("/api/demo/reset", headers=headers(first)).status_code == 200
    assert client.get("/api/auth/me", headers=headers(first)).status_code == 200
    assert client.post("/api/auth/login", json={"email": "person@example.com", "password": "a long test password"}).status_code == 200


def test_extension_session_has_independent_logout(client):
    token = signup(client)
    response = client.post("/api/auth/extension-session", headers=headers(token))
    extension_token = response.json()["token"]
    assert extension_token != token
    client.post("/api/auth/logout", headers=headers(extension_token))
    assert client.get("/api/auth/me", headers=headers(extension_token)).status_code == 401
    assert client.get("/api/auth/me", headers=headers(token)).status_code == 200
    assert client.post("/api/auth/extension-session").status_code == 401


def test_rate_limit(client):
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "wrong"}).status_code == 401
    response = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "wrong"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_google_login_and_link_require_verified_identity(client, monkeypatch):
    claims = {"sub": "google-user", "email": "person@example.com", "email_verified": True}
    def verify(credential, audience):
        assert audience == "test-client"
        if credential != "verified":
            raise ValueError("bad signature")
        return claims
    monkeypatch.setattr("app.api.auth.verify_google", verify)
    assert client.post("/api/auth/google", json={"credential": "forged"}).status_code == 401
    response = client.post("/api/auth/google", json={"credential": "verified"})
    assert response.status_code == 200
    token = response.json()["token"]
    user_id = client.get("/api/auth/me", headers=headers(token)).json()["id"]
    response = client.post("/api/auth/google", json={"credential": "verified"})
    assert client.get("/api/auth/me", headers=headers(response.json()["token"])).json()["id"] == user_id
    assert client.post("/api/auth/login", json={"email": "person@example.com", "password": "unused-password"}).status_code == 401
    claims["email_verified"] = False
    assert client.post("/api/auth/google", json={"credential": "verified"}).status_code == 401


def test_google_does_not_silently_take_over_password_account(client, monkeypatch):
    token = signup(client)
    monkeypatch.setattr("app.api.auth.verify_google", lambda *args: {"sub": "google-user", "email": "person@example.com", "email_verified": True})
    body = {"credential": "verified"}
    assert client.post("/api/auth/google", json=body).status_code == 409
    assert client.post("/api/auth/google/link", json=body).status_code == 401
    assert client.post("/api/auth/google/link", json=body, headers=headers(token)).status_code == 200
    response = client.post("/api/auth/google", json=body)
    assert response.status_code == 200
    assert client.get("/api/auth/me", headers=headers(response.json()["token"])).json() == client.get("/api/auth/me", headers=headers(token)).json()


def test_google_disabled_without_client_id(client):
    client.app.state.config.google_client_id = ""
    assert client.get("/api/auth/config").json() == {"google_client_id": ""}
    assert client.post("/api/auth/google", json={"credential": "anything"}).status_code == 503
