"""Tests for the AUTH_PASSWORD (HTTP Basic) and API_KEY auth gates.

Two independent layers:

- ``AUTH_PASSWORD`` → HTTP Basic on HTML pages (``/``, ``/demo``, ``/docs``).
- ``API_KEY`` → ``X-API-Key`` (or ``Authorization: Bearer``) on data
  endpoints (``/v1/ocr``, ``/demo/process``, ``/demo/preview``,
  ``/demo/unstructured``, ``/demo/mistral``, ``/doc``).

``/health`` is always public; in dev mode (neither var set) everything
passes through.
"""
import base64

import pytest


def _basic(password: str, user: str = "user") -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


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


# ---------------------------------------------------------------------------
# AUTH_PASSWORD — HTTP Basic on HTML pages only
# ---------------------------------------------------------------------------

class TestBasicAuthOnHtmlPages:
    def test_demo_returns_401_without_credentials(self, app_with_basic):
        resp = app_with_basic.get("/demo")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate", "").startswith("Basic")

    def test_demo_accepts_correct_password(self, app_with_basic):
        resp = app_with_basic.get("/demo", headers={"Authorization": _basic("letmein")})
        assert resp.status_code == 200

    def test_username_is_ignored(self, app_with_basic):
        for user in ("user", "alice", ""):
            resp = app_with_basic.get("/demo", headers={"Authorization": _basic("letmein", user=user)})
            assert resp.status_code == 200, f"username={user!r}"

    def test_wrong_password_rejected(self, app_with_basic):
        resp = app_with_basic.get("/demo", headers={"Authorization": _basic("nope")})
        assert resp.status_code == 401

    def test_malformed_header_rejected(self, app_with_basic):
        for header in ("Bearer letmein", "Basic !!!not-base64!!!", "Basic"):
            resp = app_with_basic.get("/demo", headers={"Authorization": header})
            assert resp.status_code == 401, f"header={header!r}"

    def test_root_also_gated(self, app_with_basic):
        # `/` is the same view as `/demo`.
        resp = app_with_basic.get("/")
        assert resp.status_code == 401

    def test_docs_also_gated(self, app_with_basic):
        resp = app_with_basic.get("/docs")
        assert resp.status_code == 401
        resp = app_with_basic.get("/docs", headers={"Authorization": _basic("letmein")})
        assert resp.status_code == 200

    def test_health_bypasses_basic(self, app_with_basic):
        resp = app_with_basic.get("/health")
        assert resp.status_code == 200

    def test_data_endpoints_open_when_only_basic_set(self, app_with_basic):
        # AUTH_PASSWORD without API_KEY does not lock the data endpoints —
        # they're a separate gate. (Real deploys should set both.)
        resp = app_with_basic.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
        )
        # 401 would be wrong here; we expect the request to reach the
        # route, which will fail later for unrelated reasons (the LLM
        # mock isn't installed in this fixture). Anything other than 401
        # is fine.
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# API_KEY — header check on data endpoints only
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
        # We don't care about the downstream response shape — only that
        # the auth gate didn't 401 us.
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

    def test_demo_html_open_when_only_api_key_set(self, app_with_api_key):
        # The HTML pages are not gated by API_KEY — only by AUTH_PASSWORD.
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
    def test_demo_html_needs_basic(self, app_with_both):
        resp = app_with_both.get("/demo")
        assert resp.status_code == 401

    def test_demo_html_with_basic_carries_api_key_in_template(self, app_with_both):
        resp = app_with_both.get("/demo", headers={"Authorization": _basic("letmein")})
        assert resp.status_code == 200
        assert 'name="api-key" content="secret-token"' in resp.get_data(as_text=True)

    def test_v1_ocr_needs_api_key(self, app_with_both):
        resp = app_with_both.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
        )
        assert resp.status_code == 401

    def test_v1_ocr_with_basic_alone_still_rejected(self, app_with_both):
        # Basic auth doesn't unlock data endpoints; you need the API key.
        resp = app_with_both.post(
            "/v1/ocr",
            json={"images": [{"type": "base64", "value": "abc"}]},
            headers={"Authorization": _basic("letmein")},
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

    def test_template_has_empty_api_key(self, app_without_auth):
        resp = app_without_auth.get("/demo")
        body = resp.get_data(as_text=True)
        assert 'name="api-key" content=""' in body
