"""Tests for the AUTH_PASSWORD (HTML login + session cookie) and API_KEY gates.

Two independent layers:

- ``AUTH_PASSWORD`` → HTML login form at ``/login`` backed by a signed
  session cookie. Unauthed requests to ``/``, ``/demo``, ``/docs`` or
  ``/compare`` get redirected to ``/login?next=<path>``.
- ``API_KEY`` → ``X-API-Key`` (or ``Authorization: Bearer``) on data
  endpoints (``/v1/ocr``, ``/demo/process``, ``/demo/preview``,
  ``/demo/unstructured``, ``/demo/mistral``, ``/doc``, ``/comparison``).

``/health``, ``/login`` and ``/logout`` are always public; in dev mode
(neither env var set) every gate is a no-op.
"""
from urllib.parse import urlparse

import pytest


def _client():
    from main import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def app_with_basic(monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "letmein")
    monkeypatch.delenv("API_KEY", raising=False)
    return _client()


@pytest.fixture()
def app_with_api_key(monkeypatch):
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.setenv("API_KEY", "secret-token")
    return _client()


@pytest.fixture()
def app_with_both(monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "letmein")
    monkeypatch.setenv("API_KEY", "secret-token")
    return _client()


@pytest.fixture()
def app_without_auth(monkeypatch):
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    return _client()


def _login(client, password: str, next_url: str = "/demo"):
    return client.post(
        "/login",
        data={"password": password, "next": next_url},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# AUTH_PASSWORD — HTML login form + session cookie
# ---------------------------------------------------------------------------

class TestLoginForm:
    def test_login_get_returns_form(self, app_with_basic):
        resp = app_with_basic.get("/login")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "<form" in body and 'name="password"' in body
        assert 'name="next"' in body

    def test_login_get_accepts_next(self, app_with_basic):
        resp = app_with_basic.get("/login?next=/docs")
        assert resp.status_code == 200
        assert 'value="/docs"' in resp.get_data(as_text=True)

    def test_login_get_bypasses_auth_when_password_set(self, app_with_basic):
        # You must be able to reach /login without already being authed,
        # otherwise there's no way to sign in.
        resp = app_with_basic.get("/login")
        assert resp.status_code == 200

    def test_login_post_with_correct_password_sets_session_and_redirects(self, app_with_basic):
        resp = _login(app_with_basic, "letmein", "/demo")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/demo"

    def test_login_post_with_wrong_password_shows_error(self, app_with_basic):
        resp = _login(app_with_basic, "nope", "/demo")
        assert resp.status_code == 401
        body = resp.get_data(as_text=True)
        assert "Wrong password" in body

    def test_login_post_open_redirect_is_blocked(self, app_with_basic):
        # next= containing an absolute URL or //host/… falls back to /demo.
        for danger in ("https://evil.com/", "//evil.com/", "ftp://x"):
            resp = _login(app_with_basic, "letmein", danger)
            assert resp.status_code == 302
            assert urlparse(resp.headers["Location"]).path == "/demo"

    def test_login_post_preserves_internal_path(self, app_with_basic):
        resp = _login(app_with_basic, "letmein", "/docs")
        assert urlparse(resp.headers["Location"]).path == "/docs"


class TestHtmlPageGating:
    def test_demo_redirects_to_login_when_unauthed(self, app_with_basic):
        resp = app_with_basic.get("/demo")
        assert resp.status_code == 302
        loc = urlparse(resp.headers["Location"])
        assert loc.path == "/login"
        # Accept either encoded (%2Fdemo) or unencoded (/demo) forms — both
        # are valid in a query string and the server accepts both on the
        # /login GET side.
        assert "next=/demo" in (loc.query or "") or "next=%2Fdemo" in (loc.query or "")

    def test_root_redirects_to_login_when_unauthed(self, app_with_basic):
        resp = app_with_basic.get("/")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/login"

    def test_docs_redirects_to_login_when_unauthed(self, app_with_basic):
        resp = app_with_basic.get("/docs")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/login"

    def test_compare_redirects_to_login_when_unauthed(self, app_with_basic):
        resp = app_with_basic.get("/compare")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/login"

    def test_demo_accessible_after_login(self, app_with_basic):
        login_resp = _login(app_with_basic, "letmein", "/demo")
        assert login_resp.status_code == 302
        # Flask's test client shares cookies across calls.
        resp = app_with_basic.get("/demo")
        assert resp.status_code == 200

    def test_logout_clears_session(self, app_with_basic):
        _login(app_with_basic, "letmein", "/demo")
        resp = app_with_basic.get("/demo")
        assert resp.status_code == 200

        logout_resp = app_with_basic.get("/logout")
        assert logout_resp.status_code == 302
        assert urlparse(logout_resp.headers["Location"]).path == "/login"

        resp = app_with_basic.get("/demo")
        assert resp.status_code == 302  # back to the gate

    def test_login_already_authed_short_circuits(self, app_with_basic):
        _login(app_with_basic, "letmein", "/demo")
        # Visiting /login again should just bounce to the `next` target.
        resp = app_with_basic.get("/login?next=/docs")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/docs"

    def test_health_bypasses_login_gate(self, app_with_basic):
        resp = app_with_basic.get("/health")
        assert resp.status_code == 200

    def test_data_endpoints_open_when_only_basic_set(self, app_with_basic):
        # AUTH_PASSWORD without API_KEY does not lock the data endpoints —
        # they're a separate gate. (Real deploys should set both.)
        resp = app_with_basic.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
        )
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# API_KEY — header check on data endpoints only (unchanged from Basic-era)
# ---------------------------------------------------------------------------

class TestApiKeyOnDataEndpoints:
    def test_v1_ocr_returns_401_without_key(self, app_with_api_key):
        resp = app_with_api_key.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
        )
        assert resp.status_code == 401
        assert "API key" in resp.get_json()["error"]

    def test_v1_ocr_accepts_x_api_key(self, app_with_api_key):
        resp = app_with_api_key.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
            headers={"X-API-Key": "secret-token"},
        )
        assert resp.status_code != 401

    def test_v1_ocr_accepts_bearer(self, app_with_api_key):
        resp = app_with_api_key.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert resp.status_code != 401

    def test_wrong_key_rejected(self, app_with_api_key):
        resp = app_with_api_key.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
            headers={"X-API-Key": "wrong"},
        )
        assert resp.status_code == 401

    def test_doc_requires_key(self, app_with_api_key):
        resp = app_with_api_key.get("/doc")
        assert resp.status_code == 401
        resp = app_with_api_key.get("/doc", headers={"X-API-Key": "secret-token"})
        assert resp.status_code == 200

    def test_comparison_requires_key(self, app_with_api_key):
        resp = app_with_api_key.get("/comparison")
        assert resp.status_code == 401
        resp = app_with_api_key.get("/comparison", headers={"X-API-Key": "secret-token"})
        assert resp.status_code == 200

    def test_demo_html_open_when_only_api_key_set(self, app_with_api_key):
        # HTML pages are not gated by API_KEY — only by AUTH_PASSWORD.
        resp = app_with_api_key.get("/demo")
        assert resp.status_code == 200

    def test_health_bypasses_api_key(self, app_with_api_key):
        resp = app_with_api_key.get("/health")
        assert resp.status_code == 200

    def test_html_template_embeds_api_key(self, app_with_api_key):
        resp = app_with_api_key.get("/demo")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'name="api-key" content="secret-token"' in body


# ---------------------------------------------------------------------------
# Both gates simultaneously — the recommended deploy posture
# ---------------------------------------------------------------------------

class TestBothGates:
    def test_demo_html_redirects_to_login(self, app_with_both):
        resp = app_with_both.get("/demo")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/login"

    def test_demo_html_after_login_embeds_api_key(self, app_with_both):
        _login(app_with_both, "letmein", "/demo")
        resp = app_with_both.get("/demo")
        assert resp.status_code == 200
        assert 'name="api-key" content="secret-token"' in resp.get_data(as_text=True)

    def test_v1_ocr_needs_api_key(self, app_with_both):
        resp = app_with_both.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
        )
        assert resp.status_code == 401

    def test_v1_ocr_after_session_login_still_rejected(self, app_with_both):
        # Session login does NOT grant API access; the API key is required.
        _login(app_with_both, "letmein", "/demo")
        resp = app_with_both.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
        )
        assert resp.status_code == 401

    def test_v1_ocr_with_api_key_passes(self, app_with_both):
        resp = app_with_both.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
            headers={"X-API-Key": "secret-token"},
        )
        assert resp.status_code != 401

    def test_health_open(self, app_with_both):
        resp = app_with_both.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Dev mode — no env vars, everything open
# ---------------------------------------------------------------------------

class TestDevMode:
    def test_demo_open(self, app_without_auth):
        resp = app_without_auth.get("/demo")
        assert resp.status_code == 200

    def test_docs_open(self, app_without_auth):
        resp = app_without_auth.get("/docs")
        assert resp.status_code == 200

    def test_doc_open(self, app_without_auth):
        resp = app_without_auth.get("/doc")
        assert resp.status_code == 200

    def test_health_open(self, app_without_auth):
        resp = app_without_auth.get("/health")
        assert resp.status_code == 200

    def test_login_get_open(self, app_without_auth):
        resp = app_without_auth.get("/login")
        assert resp.status_code == 200

    def test_login_post_with_any_password_succeeds_in_dev(self, app_without_auth):
        resp = _login(app_without_auth, "anything", "/demo")
        assert resp.status_code == 302

    def test_template_has_empty_api_key(self, app_without_auth):
        resp = app_without_auth.get("/demo")
        body = resp.get_data(as_text=True)
        assert 'name="api-key" content=""' in body
