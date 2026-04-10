import base64
from unittest.mock import MagicMock, patch

import pytest

from backends.mistral import MistralBackend, MistralNotConfigured


def _mock_post(status_code: int = 200, body: dict | None = None, text: str | None = None):
    """Build a MagicMock httpx.Client whose .post returns a canned response."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": "application/json"}
    if body is not None:
        response.json.return_value = body
        response.text = ""
    if text is not None:
        response.json.side_effect = ValueError("not json")
        response.text = text
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response
    return client, response


class TestConfiguration:
    def test_explicit_api_key_wins(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        backend = MistralBackend(api_key="explicit-key")
        assert backend.api_key == "explicit-key"
        assert backend.configured

    def test_env_var_used_when_no_arg(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "env-key")
        backend = MistralBackend()
        assert backend.api_key == "env-key"
        assert backend.configured

    def test_unconfigured_when_neither(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        backend = MistralBackend()
        assert backend.api_key is None
        assert not backend.configured

    def test_unconfigured_raises_on_process(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        backend = MistralBackend()
        with pytest.raises(MistralNotConfigured):
            backend.process(b"data", "application/pdf")


class TestRequestShape:
    def test_pdf_uses_document_url(self):
        backend = MistralBackend(api_key="test-key")
        client, _ = _mock_post(200, {
            "model": "mistral-ocr-latest",
            "pages": [{"index": 0, "markdown": "Hello"}],
        })
        with patch("backends.mistral.httpx.Client", return_value=client):
            backend.process(b"%PDF-1.4 fake", "application/pdf")

        body = client.post.call_args.kwargs["json"]
        assert body["model"] == "mistral-ocr-latest"
        assert body["document"]["type"] == "document_url"
        assert body["document"]["document_url"].startswith("data:application/pdf;base64,")
        # Decoded content matches what we sent.
        b64 = body["document"]["document_url"].split(",", 1)[1]
        assert base64.b64decode(b64) == b"%PDF-1.4 fake"

    def test_image_uses_image_url(self):
        backend = MistralBackend(api_key="test-key")
        client, _ = _mock_post(200, {"model": "m", "pages": []})
        with patch("backends.mistral.httpx.Client", return_value=client):
            backend.process(b"\x89PNG\r\n", "image/png")

        body = client.post.call_args.kwargs["json"]
        assert body["document"]["type"] == "image_url"
        assert body["document"]["image_url"].startswith("data:image/png;base64,")

    def test_pages_field_forwarded(self):
        backend = MistralBackend(api_key="test-key")
        client, _ = _mock_post(200, {"model": "m", "pages": []})
        with patch("backends.mistral.httpx.Client", return_value=client):
            backend.process(b"x", "application/pdf", pages=[0, 2, 4])
        body = client.post.call_args.kwargs["json"]
        assert body["pages"] == [0, 2, 4]

    def test_no_pages_field_when_unset(self):
        backend = MistralBackend(api_key="test-key")
        client, _ = _mock_post(200, {"model": "m", "pages": []})
        with patch("backends.mistral.httpx.Client", return_value=client):
            backend.process(b"x", "application/pdf")
        body = client.post.call_args.kwargs["json"]
        assert "pages" not in body

    def test_authorization_header(self):
        backend = MistralBackend(api_key="bearer-token")
        client, _ = _mock_post(200, {"model": "m", "pages": []})
        with patch("backends.mistral.httpx.Client", return_value=client):
            backend.process(b"x", "application/pdf")
        headers = client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer bearer-token"
        assert headers["Content-Type"] == "application/json"

    def test_include_image_base64_default_false(self):
        backend = MistralBackend(api_key="x")
        client, _ = _mock_post(200, {"model": "m", "pages": []})
        with patch("backends.mistral.httpx.Client", return_value=client):
            backend.process(b"x", "application/pdf")
        body = client.post.call_args.kwargs["json"]
        assert body["include_image_base64"] is False


class TestErrorHandling:
    def test_non_200_raises_with_url_and_body(self):
        backend = MistralBackend(api_key="x")
        response = MagicMock()
        response.status_code = 401
        response.text = "Unauthorized"
        response.headers = {"content-type": "application/json"}
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = response
        with patch("backends.mistral.httpx.Client", return_value=client):
            with pytest.raises(RuntimeError, match="HTTP 401"):
                backend.process(b"x", "application/pdf")

    def test_unparseable_json_raises_with_snippet(self):
        backend = MistralBackend(api_key="x")
        client, _ = _mock_post(200, text="<html>not json</html>")
        with patch("backends.mistral.httpx.Client", return_value=client):
            with pytest.raises(RuntimeError, match="non-JSON"):
                backend.process(b"x", "application/pdf")

    def test_missing_pages_field_raises(self):
        backend = MistralBackend(api_key="x")
        client, _ = _mock_post(200, {"model": "m", "results": []})  # wrong key
        with patch("backends.mistral.httpx.Client", return_value=client):
            with pytest.raises(RuntimeError, match="missing 'pages'"):
                backend.process(b"x", "application/pdf")

    def test_returns_payload_on_success(self):
        backend = MistralBackend(api_key="x")
        payload = {
            "model": "mistral-ocr-latest",
            "pages": [{"index": 0, "markdown": "# Page"}, {"index": 1, "markdown": "# Two"}],
            "usage_info": {"pages_processed": 2, "doc_size_bytes": 100},
        }
        client, _ = _mock_post(200, payload)
        with patch("backends.mistral.httpx.Client", return_value=client):
            result = backend.process(b"x", "application/pdf")
        assert result == payload
