"""Mistral OCR backend.

Sends a document (PDF or image bytes) to a Mistral-compatible OCR
endpoint as a base64 data URL and returns the parsed response.

We route through the same Privatemode proxy as the VLM and Unstructured
backends — that is, ``${LLM_BASE_URL}/ocr`` (typically
``http://localhost:8080/v1/ocr``) authenticated with ``LLM_API_KEY``.
This way there's only one upstream credential to provision in deploy
and the request still flows through Privatemode's confidential
inference plane.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name, "")
    return val if val else default


LLM_BASE_URL = _env_str("LLM_BASE_URL", "http://localhost:8080/v1")
LLM_API_KEY  = _env_str("LLM_API_KEY", "dummy")
MISTRAL_OCR_MODEL = _env_str("MISTRAL_OCR_MODEL", "mistral-ocr-latest")


def derive_mistral_url(base_url: str) -> str:
    """Sibling URL for the Mistral-compatible OCR endpoint on the LLM proxy.

    Mistral's upstream path is ``/v1/ocr``; our LLM_BASE_URL already
    ends in ``/v1`` (or doesn't), so we just append ``/ocr``.

    >>> derive_mistral_url("http://localhost:8080/v1")
    'http://localhost:8080/v1/ocr'
    >>> derive_mistral_url("http://localhost:8080/v1/")
    'http://localhost:8080/v1/ocr'
    >>> derive_mistral_url("http://localhost:8080")
    'http://localhost:8080/ocr'
    """
    return base_url.rstrip("/") + "/ocr"


class MistralNotConfigured(RuntimeError):
    """Raised when the Mistral backend is invoked without a configured API key."""


class MistralBackend:
    def __init__(
        self,
        api_key: str | None = None,
        url: str | None = None,
        model: str = MISTRAL_OCR_MODEL,
        timeout: float = 600.0,
    ):
        # Read late so tests / runtime config changes are honoured. Empty
        # strings count as unset (CI sometimes passes -e VAR= for unset
        # secrets).
        self.api_key = api_key if api_key is not None else _env_str("LLM_API_KEY", "")
        if not self.api_key:
            self.api_key = None
        base = _env_str("LLM_BASE_URL", LLM_BASE_URL)
        self.url = url if url is not None else derive_mistral_url(base)
        self.model = model or MISTRAL_OCR_MODEL
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        # `dummy` is the conventional placeholder for "no real key" used
        # by the local Privatemode proxy; we treat it as configured
        # because the proxy itself accepts it.
        return bool(self.api_key)

    def process(
        self,
        file_bytes: bytes,
        content_type: str,
        *,
        pages: list[int] | None = None,
    ) -> dict:
        """Send the document to Mistral OCR and return the parsed JSON response.

        `pages` is forwarded to Mistral's `pages` field (0-based) so the
        upstream API itself does the page selection — we don't do it
        client-side and we don't slice the file.
        """
        if not self.api_key:
            raise MistralNotConfigured(
                "LLM_API_KEY is not set on the server. Add it to the "
                "environment to enable the Mistral backend (it goes through "
                "the same LLM proxy as the VLM backend)."
            )

        b64 = base64.b64encode(file_bytes).decode()
        if content_type.startswith("image/"):
            document = {
                "type": "image_url",
                "image_url": f"data:{content_type};base64,{b64}",
            }
        else:
            # Anything that isn't an image gets the document_url shape.
            # Mistral accepts application/pdf inline as a data URL.
            document = {
                "type": "document_url",
                "document_url": f"data:{content_type};base64,{b64}",
            }

        body: dict[str, Any] = {
            "model": self.model,
            "document": document,
            "include_image_base64": False,
        }
        if pages is not None:
            body["pages"] = pages

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "Mistral POST %s model=%s bytes=%d pages=%s (single upload)",
            self.url, self.model, len(file_bytes),
            "all" if pages is None else pages,
        )
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.url, json=body, headers=headers)
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Mistral API unreachable at {self.url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            snippet = (resp.text or "").strip()
            if len(snippet) > 500:
                snippet = snippet[:500] + "…"
            logger.warning(
                "Mistral HTTP %d at %s — body=%s",
                resp.status_code, self.url, snippet,
            )
            raise RuntimeError(
                f"Mistral OCR returned HTTP {resp.status_code} from {self.url}: "
                f"{snippet or '(empty body)'}"
            )

        try:
            payload = resp.json()
        except Exception as exc:
            snippet = (resp.text or "")[:200]
            raise RuntimeError(
                f"Mistral returned non-JSON from {self.url} "
                f"(content-type={resp.headers.get('content-type', 'unknown')}): "
                f"{snippet!r} — {exc}"
            ) from exc
        if not isinstance(payload, dict) or "pages" not in payload:
            raise RuntimeError(
                f"Mistral returned unexpected shape: {type(payload).__name__}; "
                f"missing 'pages' field"
            )
        return payload
