import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backends.privatemode import PrivatemodeBackend, _describe_openai_error


def _make_backend() -> PrivatemodeBackend:
    return PrivatemodeBackend(base_url="http://localhost:9999/v1", api_key="test", model="test-model")


def _mock_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    completion = MagicMock()
    completion.choices = [choice]
    return completion


class TestOcrSingle:
    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_markdown_returns_content_string(self, mock_encode):
        backend = _make_backend()
        backend.client.chat.completions.create = MagicMock(
            return_value=_mock_completion("# Hello\n\nWorld")
        )

        result = backend._ocr_single("/fake/image.jpg", "markdown")

        assert result == {"content": "# Hello\n\nWorld"}
        mock_encode.assert_called_once_with("/fake/image.jpg")

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_text_returns_content_string(self, mock_encode):
        backend = _make_backend()
        backend.client.chat.completions.create = MagicMock(
            return_value=_mock_completion("Hello World")
        )

        result = backend._ocr_single("/fake/image.jpg", "text")
        assert result == {"content": "Hello World"}

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_json_parses_structured_output(self, mock_encode):
        backend = _make_backend()
        payload = {"title": "Invoice", "content": "Total: 100", "sections": []}
        backend.client.chat.completions.create = MagicMock(
            return_value=_mock_completion(json.dumps(payload))
        )

        result = backend._ocr_single("/fake/image.jpg", "json")
        assert result == {"content": payload}

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_json_format_sets_response_format(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(
            return_value=_mock_completion(json.dumps({"title": "", "content": "x", "sections": []}))
        )
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "json")

        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_markdown_does_not_set_response_format(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(return_value=_mock_completion("# Doc"))
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "markdown")

        call_kwargs = create_mock.call_args.kwargs
        assert "response_format" not in call_kwargs

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_image_embedded_as_base64_url(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(return_value=_mock_completion("text"))
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "text")

        messages = create_mock.call_args.kwargs["messages"]
        image_part = messages[0]["content"][0]
        assert image_part["type"] == "image_url"
        assert image_part["image_url"]["url"] == "data:image/jpeg;base64,base64data"

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_language_hint_appended_to_prompt(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(return_value=_mock_completion("text"))
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "markdown", language="de")

        text_part = create_mock.call_args.kwargs["messages"][0]["content"][1]
        assert "de" in text_part["text"]
        assert "language" in text_part["text"].lower()

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_no_language_means_no_hint(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(return_value=_mock_completion("text"))
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "markdown")

        text_part = create_mock.call_args.kwargs["messages"][0]["content"][1]
        assert "language" not in text_part["text"].lower()

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_describe_images_appends_section_instruction(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(return_value=_mock_completion("text"))
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "markdown", describe_images=True)

        prompt = create_mock.call_args.kwargs["messages"][0]["content"][1]["text"]
        assert "Image Descriptions" in prompt
        assert "figures" in prompt.lower() or "images" in prompt.lower()

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_describe_images_default_off(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(return_value=_mock_completion("text"))
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "markdown")

        prompt = create_mock.call_args.kwargs["messages"][0]["content"][1]["text"]
        assert "Image Descriptions" not in prompt

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_describe_images_skipped_for_json_format(self, mock_encode):
        backend = _make_backend()
        import json as _json
        create_mock = MagicMock(
            return_value=_mock_completion(_json.dumps({"title": "", "content": "x", "sections": []}))
        )
        backend.client.chat.completions.create = create_mock

        # JSON has a strict schema; the suffix would corrupt it.
        backend._ocr_single("/fake/image.jpg", "json", describe_images=True)

        prompt = create_mock.call_args.kwargs["messages"][0]["content"][1]["text"]
        assert "Image Descriptions" not in prompt

    @patch("backends.privatemode.encode_jpeg_image", return_value="base64data")
    def test_describe_images_combines_with_language(self, mock_encode):
        backend = _make_backend()
        create_mock = MagicMock(return_value=_mock_completion("text"))
        backend.client.chat.completions.create = create_mock

        backend._ocr_single("/fake/image.jpg", "markdown", language="de", describe_images=True)

        prompt = create_mock.call_args.kwargs["messages"][0]["content"][1]["text"]
        assert "de" in prompt
        assert "Image Descriptions" in prompt


class TestProcessImages:
    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_results_in_original_order(self, mock_encode):
        backend = _make_backend()

        def side_effect(path, fmt, language=None, describe_images=False):
            return {"content": f"result-for-{path}"}

        backend._ocr_single = MagicMock(side_effect=side_effect)
        paths = ["/img/a.jpg", "/img/b.jpg", "/img/c.jpg"]
        results = backend.process_images(paths, "markdown", threads=3)

        assert len(results) == 3
        assert results[0] == {"index": 0, "content": "result-for-/img/a.jpg"}
        assert results[1] == {"index": 1, "content": "result-for-/img/b.jpg"}
        assert results[2] == {"index": 2, "content": "result-for-/img/c.jpg"}

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_failed_image_records_error(self, mock_encode):
        backend = _make_backend()

        def side_effect(path, fmt, language=None, describe_images=False):
            if "bad" in path:
                raise RuntimeError("LLM timeout")
            return {"content": "ok"}

        backend._ocr_single = MagicMock(side_effect=side_effect)
        results = backend.process_images(["/good.jpg", "/bad.jpg"], "markdown", threads=2)

        good = next(r for r in results if r["index"] == 0)
        bad = next(r for r in results if r["index"] == 1)
        assert good["content"] == "ok"
        assert "error" in bad
        assert bad["content"] is None

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_single_image(self, mock_encode):
        backend = _make_backend()
        backend._ocr_single = MagicMock(return_value={"content": "hello"})
        results = backend.process_images(["/only.jpg"], "text", threads=1)
        assert results == [{"index": 0, "content": "hello"}]

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_empty_list_returns_empty(self, mock_encode):
        backend = _make_backend()
        results = backend.process_images([], "markdown", threads=2)
        assert results == []


class TestErrorDescribing:
    def _status_error(self, status: int, body: str, method: str = "POST", url: str = "http://llm/v1/chat/completions"):
        """Build a real openai.APIStatusError around a fake httpx response."""
        from openai import APIStatusError
        req = httpx.Request(method, url)
        resp = httpx.Response(status, content=body.encode(), request=req)
        return APIStatusError(message=body, response=resp, body=None)

    def test_status_error_includes_url_and_status(self):
        exc = self._status_error(404, "404 page not found")
        msg = _describe_openai_error(exc)
        assert "POST" in msg
        assert "http://llm/v1/chat/completions" in msg
        assert "HTTP 404" in msg
        assert "404 page not found" in msg

    def test_status_error_truncates_large_body(self):
        body = "x" * 1000
        exc = self._status_error(500, body)
        msg = _describe_openai_error(exc)
        assert "HTTP 500" in msg
        assert "…" in msg  # body was truncated

    def test_non_openai_exception_passes_through(self):
        exc = ValueError("something else")
        msg = _describe_openai_error(exc)
        assert "ValueError" in msg
        assert "something else" in msg

    @patch("backends.privatemode.encode_jpeg_image", return_value="b64")
    def test_ocr_single_wraps_openai_errors_with_url(self, mock_encode):
        backend = _make_backend()
        exc = TestErrorDescribing()._status_error(404, "404 page not found")
        backend.client.chat.completions.create = MagicMock(side_effect=exc)

        with pytest.raises(RuntimeError) as exc_info:
            backend._ocr_single("/fake.jpg", "markdown")

        msg = str(exc_info.value)
        assert "POST" in msg
        assert "http://llm/v1/chat/completions" in msg
        assert "HTTP 404" in msg
