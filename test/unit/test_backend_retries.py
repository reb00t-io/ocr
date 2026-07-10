"""Tests for the generation-robustness layer in PrivatemodeBackend:
deterministic sampling, degenerate-output retries, transient-error
retries, and output fence stripping."""
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

import backends.privatemode as pm
from backends.privatemode import PrivatemodeBackend


def _make_backend() -> PrivatemodeBackend:
    return PrivatemodeBackend(base_url="http://localhost:9999/v1", api_key="test", model="test-model")


def _completion(content: str, finish_reason: str = "stop") -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _status_error(status: int, body: str = "err"):
    from openai import APIStatusError
    req = httpx.Request("POST", "http://llm/v1/chat/completions")
    resp = httpx.Response(status, content=body.encode(), request=req)
    return APIStatusError(message=body, response=resp, body=None)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(pm.time, "sleep", lambda _s: None)


class TestSampling:
    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_first_attempt_is_deterministic(self, _enc):
        backend = _make_backend()
        create = MagicMock(return_value=_completion("# Doc"))
        backend.client.chat.completions.create = create

        backend._ocr_single("/fake.jpg", "markdown")

        kwargs = create.call_args.kwargs
        assert kwargs["temperature"] == 0.0
        assert kwargs["top_p"] == 0.1
        assert kwargs["max_tokens"] == pm.MAX_OUTPUT_TOKENS


class TestDegenerateOutputRetries:
    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_repetition_retried_with_higher_temperature(self, _enc):
        backend = _make_backend()
        degenerate = "Intro\n" + "same phrase " * 40
        create = MagicMock(side_effect=[_completion(degenerate), _completion("# Clean")])
        backend.client.chat.completions.create = create

        result = backend._ocr_single("/fake.jpg", "markdown")

        assert result == {"content": "# Clean"}
        assert create.call_count == 2
        retry_kwargs = create.call_args_list[1].kwargs
        assert retry_kwargs["temperature"] == pytest.approx(0.2)
        assert retry_kwargs["top_p"] == 0.95

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_exhausted_retries_return_content_with_warning(self, _enc):
        backend = _make_backend()
        degenerate = "Intro\n" + "same phrase " * 40
        create = MagicMock(return_value=_completion(degenerate))
        backend.client.chat.completions.create = create

        result = backend._ocr_single("/fake.jpg", "markdown")

        assert create.call_count == pm.MAX_RETRIES + 1
        assert result["content"] == degenerate.strip() or result["content"] == degenerate
        assert "repetition" in result["warning"]

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_truncation_without_repetition_retries_once(self, _enc):
        backend = _make_backend()
        create = MagicMock(
            return_value=_completion("A genuinely long document…", finish_reason="length")
        )
        backend.client.chat.completions.create = create

        result = backend._ocr_single("/fake.jpg", "markdown")

        # One retry only — a genuinely long page won't shrink.
        assert create.call_count == 2
        assert "truncated" in result["warning"]
        assert result["content"] == "A genuinely long document…"

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_clean_output_not_retried(self, _enc):
        backend = _make_backend()
        create = MagicMock(return_value=_completion("# Doc\n\nBody."))
        backend.client.chat.completions.create = create

        result = backend._ocr_single("/fake.jpg", "markdown")

        assert create.call_count == 1
        assert result == {"content": "# Doc\n\nBody."}


class TestFenceStripping:
    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_wrapping_fence_removed(self, _enc):
        backend = _make_backend()
        create = MagicMock(return_value=_completion("```markdown\n# Doc\n\nBody.\n```"))
        backend.client.chat.completions.create = create

        result = backend._ocr_single("/fake.jpg", "markdown")
        assert result == {"content": "# Doc\n\nBody."}


class TestErrorRetries:
    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_transient_error_then_success(self, _enc):
        backend = _make_backend()
        create = MagicMock(side_effect=[_status_error(503), _completion("# Doc")])
        backend.client.chat.completions.create = create

        result = backend._ocr_single("/fake.jpg", "markdown")

        assert result == {"content": "# Doc"}
        assert create.call_count == 2

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_permanent_error_raises_immediately(self, _enc):
        backend = _make_backend()
        create = MagicMock(side_effect=_status_error(404, "404 page not found"))
        backend.client.chat.completions.create = create

        with pytest.raises(RuntimeError, match="404"):
            backend._ocr_single("/fake.jpg", "markdown")
        assert create.call_count == 1

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_transient_error_exhausted_raises(self, _enc):
        backend = _make_backend()
        create = MagicMock(side_effect=_status_error(503))
        backend.client.chat.completions.create = create

        with pytest.raises(RuntimeError):
            backend._ocr_single("/fake.jpg", "markdown")
        assert create.call_count == pm.MAX_RETRIES + 1


class TestJsonRetries:
    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_invalid_json_retried_then_parsed(self, _enc):
        backend = _make_backend()
        payload = {"title": "T", "content": "C", "sections": []}
        create = MagicMock(
            side_effect=[_completion("not json {"), _completion(json.dumps(payload))]
        )
        backend.client.chat.completions.create = create

        result = backend._ocr_single("/fake.jpg", "json")
        assert result == {"content": payload}
        assert create.call_count == 2

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_invalid_json_exhausted_raises(self, _enc):
        backend = _make_backend()
        create = MagicMock(return_value=_completion("not json {"))
        backend.client.chat.completions.create = create

        with pytest.raises(RuntimeError, match="invalid JSON"):
            backend._ocr_single("/fake.jpg", "json")
        assert create.call_count == pm.MAX_RETRIES + 1
