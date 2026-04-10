"""Tests for the AUTH_PASSWORD-gated HTTP Basic auth middleware."""
import base64

import pytest


def _basic(password: str, user: str = "user") -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.fixture()
def app_with_auth(monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "letmein")
    from main import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def app_without_auth(monkeypatch):
    # Belt-and-braces — the conftest autouse fixture already deletes it.
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    from main import app
    app.config["TESTING"] = True
    return app.test_client()


class TestAuthEnabled:
    def test_demo_returns_401_without_credentials(self, app_with_auth):
        resp = app_with_auth.get("/demo")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate", "").startswith("Basic")

    def test_demo_accepts_correct_password(self, app_with_auth):
        resp = app_with_auth.get("/demo", headers={"Authorization": _basic("letmein")})
        assert resp.status_code == 200

    def test_username_is_ignored(self, app_with_auth):
        # Any username is fine; only the password is checked.
        resp = app_with_auth.get("/demo", headers={"Authorization": _basic("letmein", user="alice")})
        assert resp.status_code == 200
        resp = app_with_auth.get("/demo", headers={"Authorization": _basic("letmein", user="")})
        assert resp.status_code == 200

    def test_wrong_password_rejected(self, app_with_auth):
        resp = app_with_auth.get("/demo", headers={"Authorization": _basic("nope")})
        assert resp.status_code == 401

    def test_malformed_header_rejected(self, app_with_auth):
        resp = app_with_auth.get("/demo", headers={"Authorization": "Bearer letmein"})
        assert resp.status_code == 401
        resp = app_with_auth.get("/demo", headers={"Authorization": "Basic !!!not-base64!!!"})
        assert resp.status_code == 401
        resp = app_with_auth.get("/demo", headers={"Authorization": "Basic"})
        assert resp.status_code == 401

    def test_health_bypasses_auth(self, app_with_auth):
        resp = app_with_auth.get("/health")
        assert resp.status_code == 200

    def test_v1_ocr_requires_auth(self, app_with_auth):
        resp = app_with_auth.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
        )
        assert resp.status_code == 401

    def test_doc_requires_auth(self, app_with_auth):
        resp = app_with_auth.get("/doc")
        assert resp.status_code == 401
        resp = app_with_auth.get("/doc", headers={"Authorization": _basic("letmein")})
        assert resp.status_code == 200


class TestAuthDisabled:
    def test_demo_open_when_no_password(self, app_without_auth):
        resp = app_without_auth.get("/demo")
        assert resp.status_code == 200

    def test_health_open(self, app_without_auth):
        resp = app_without_auth.get("/health")
        assert resp.status_code == 200

    def test_doc_open(self, app_without_auth):
        resp = app_without_auth.get("/doc")
        assert resp.status_code == 200
