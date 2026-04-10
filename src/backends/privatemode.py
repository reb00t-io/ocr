import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import APIConnectionError, APIStatusError, OpenAI

from backends.image import encode_jpeg_image

logger = logging.getLogger(__name__)


def _describe_openai_error(exc: Exception) -> str:
    """Turn an OpenAI client exception into a human-readable one-liner.

    The OpenAI Python client wraps upstream HTTP failures in ``APIStatusError``
    and network failures in ``APIConnectionError``. By default ``str(exc)``
    just echoes the response body (e.g. the bare string ``404 page not
    found`` that the Go proxy returns when the path doesn't route), which
    doesn't tell you *which URL* was hit. This helper pulls the request URL,
    HTTP method and status code off the exception so logs carry enough
    context to diagnose "wrong base URL" / "wrong path" failures quickly.
    """
    try:
        if isinstance(exc, APIStatusError):
            req = getattr(exc, "request", None)
            resp = getattr(exc, "response", None)
            url = getattr(req, "url", None) if req is not None else None
            method = getattr(req, "method", None) if req is not None else None
            status = getattr(resp, "status_code", None) if resp is not None else None
            body = ""
            if resp is not None:
                try:
                    body = resp.text or ""
                except Exception:  # noqa: BLE001
                    body = ""
                if len(body) > 300:
                    body = body[:300] + "…"
            parts = [f"{type(exc).__name__}"]
            if method and url:
                parts.append(f"{method} {url}")
            elif url:
                parts.append(str(url))
            if status is not None:
                parts.append(f"HTTP {status}")
            if body:
                parts.append(f"body={body!r}")
            return " — ".join(parts)
        if isinstance(exc, APIConnectionError):
            req = getattr(exc, "request", None)
            url = getattr(req, "url", None) if req is not None else None
            cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
            return f"{type(exc).__name__} — {url or '<unknown url>'} — {cause or exc}"
    except Exception:  # noqa: BLE001
        pass
    return f"{type(exc).__name__}: {exc}"

def _env_str(name: str, default: str) -> str:
    """Read a string env var, treating empty string the same as unset."""
    val = os.environ.get(name, "")
    return val if val else default


LLM_BASE_URL = _env_str("LLM_BASE_URL", "http://localhost:8080/v1")
LLM_API_KEY = _env_str("LLM_API_KEY", "dummy")
LLM_MODEL = _env_str("LLM_MODEL", "gemma-3-27b")

_PROMPTS = {
    "markdown": (
        "Convert this document image to markdown. "
        "Preserve all structure: headings, lists, tables, code blocks, and formatting. "
        "Return only the markdown content, no preamble."
    ),
    "text": (
        "Extract all text from this image exactly as it appears. "
        "Return plain text only, preserving line breaks. No markdown, no commentary."
    ),
    "json": (
        "Extract the content from this document image and return it as JSON. "
        "The JSON must have the fields: "
        '"title" (string, document title or empty string), '
        '"content" (string, full extracted text), '
        '"sections" (array of objects with "heading" and "content" string fields). '
        "Return only valid JSON, nothing else."
    ),
}

# Suffix appended to the markdown / text prompts when `describe_images=True`.
# Asks the model to add a clearly-labelled section that lists every figure,
# photo, chart or diagram in the page with a short natural-language
# description, in the order they appear in the document.
_DESCRIBE_IMAGES_SUFFIX = (
    " If the document contains any figures, photos, charts, diagrams, "
    "logos or other non-text images, append a final section titled "
    "'## Image Descriptions' to your output. Inside that section list one "
    "numbered entry per image (e.g. '1. ...', '2. ...') describing what "
    "each image shows in one or two sentences, in the order the images "
    "appear in the document. If there are no images, omit the section."
)

# JSON schema used with structured output when format == "json"
_OCR_JSON_SCHEMA = {
    "name": "ocr_result",
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["heading", "content"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "content", "sections"],
        "additionalProperties": False,
    },
}


class PrivatemodeBackend:
    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        api_key: str = LLM_API_KEY,
        model: str = LLM_MODEL,
    ):
        self.model = model
        self.base_url = base_url
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        logger.info(
            "PrivatemodeBackend configured: base_url=%s model=%s api_key=%s",
            base_url, model,
            "<set>" if api_key and api_key != "dummy" else api_key or "<empty>",
        )

    def _ocr_single(
        self,
        image_path: str,
        output_format: str,
        language: str | None = None,
        describe_images: bool = False,
        user_prompt: str | None = None,
    ) -> dict:
        base64_image = encode_jpeg_image(image_path)
        prompt = _PROMPTS[output_format]
        if language:
            prompt = f"{prompt} The document language is {language}."
        if describe_images and output_format != "json":
            # The JSON prompt has a strict schema; tacking on a free-form
            # section would break the response. Markdown / text are fine.
            prompt = f"{prompt}{_DESCRIBE_IMAGES_SUFFIX}"
        if user_prompt and output_format != "json":
            # Merge the caller's instruction as the *primary* directive.
            # Placing it after the defaults and explicitly flagging it
            # as overriding them makes the model follow the user's
            # intent (e.g. "summarize each page") even when it conflicts
            # with "preserve all structure" in the base prompt. The
            # defaults still apply to everything the user didn't
            # override (format, output-only constraint, etc.). JSON
            # format is skipped because the strict schema doesn't leave
            # room for free-form changes.
            prompt = (
                f"{prompt}\n\n"
                f"Additional instruction from the user "
                f"(treat this as the primary task and override the "
                f"defaults above where they conflict): {user_prompt}"
            )

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        kwargs: dict = {"model": self.model, "messages": messages}
        if output_format == "json":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": _OCR_JSON_SCHEMA,
            }

        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Re-raise with a descriptive message so callers (and test
            # fixtures) see the actual URL / status / body instead of just
            # the bare HTTP error string.
            detail = _describe_openai_error(exc)
            logger.warning(
                "LLM call failed: base_url=%s model=%s — %s",
                self.base_url, self.model, detail,
            )
            raise RuntimeError(detail) from exc

        raw = response.choices[0].message.content

        if output_format == "json":
            return {"content": json.loads(raw)}
        return {"content": raw}

    def process_images(
        self,
        image_paths: list[str],
        output_format: str = "markdown",
        threads: int = 4,
        language: str | None = None,
        describe_images: bool = False,
        user_prompt: str | None = None,
    ) -> list[dict]:
        """Process a list of images in parallel and return results in original order."""
        results: list[dict | None] = [None] * len(image_paths)

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {
                executor.submit(
                    self._ocr_single,
                    path,
                    output_format,
                    language,
                    describe_images,
                    user_prompt,
                ): i
                for i, path in enumerate(image_paths)
            }
            for future in as_completed(futures):
                i = futures[future]
                try:
                    results[i] = {"index": i, **future.result()}
                except Exception as exc:
                    logger.error("OCR failed for %s: %s", image_paths[i], exc)
                    results[i] = {"index": i, "content": None, "error": str(exc)}

        return results  # type: ignore[return-value]
