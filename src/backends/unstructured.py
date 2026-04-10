"""Unstructured-compatible OCR backend.

Sends a document (PDF or image bytes) to a `POST /general/v0/general`-style
endpoint that follows the Unstructured Partition API shape, and returns
the typed element list grouped per page.

The default URL is derived from `LLM_BASE_URL` — we strip the trailing
``/v1`` (the OpenAI-compatible chat path) and append
``/unstructured/v0/general/`` so the same Privatemode proxy serves both.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name, "")
    return val if val else default


LLM_BASE_URL = _env_str("LLM_BASE_URL", "http://localhost:8080/v1")
LLM_API_KEY  = _env_str("LLM_API_KEY", "dummy")


UNSTRUCTURED_PATH = "/unstructured/general/v0/general"


def derive_unstructured_url(base_url: str) -> str:
    """Sibling URL for the Privatemode proxy's Unstructured endpoint.

    The proxy mounts the Unstructured-compatible partition handler at the
    *root* of its host, not under the `/v1` chat-completions prefix. We
    strip a trailing `/v1` from the base URL (if present) and append
    `UNSTRUCTURED_PATH`.

    >>> derive_unstructured_url("http://localhost:8080/v1")
    'http://localhost:8080/unstructured/general/v0/general'
    >>> derive_unstructured_url("http://localhost:8080/v1/")
    'http://localhost:8080/unstructured/general/v0/general'
    >>> derive_unstructured_url("http://localhost:8080")
    'http://localhost:8080/unstructured/general/v0/general'
    >>> derive_unstructured_url("https://api.example.com/v1")
    'https://api.example.com/unstructured/general/v0/general'
    """
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base + UNSTRUCTURED_PATH


class UnstructuredBackend:
    """Thin client for an Unstructured-compatible partition endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str = LLM_API_KEY,
        timeout: float = 600.0,
    ):
        self.url = derive_unstructured_url(base_url or LLM_BASE_URL)
        self.api_key = api_key
        self.timeout = timeout

    def partition(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        *,
        # `fast` skips OCR entirely and only extracts the digital text
        # layer — by far the quickest strategy. `auto` and `hi_res` both
        # invoke the full layout + OCR pipeline and are far too slow for
        # an interactive comparison demo. Pass `strategy="hi_res"`
        # explicitly if you really want the slow path.
        strategy: str = "fast",
    ) -> list[dict]:
        """POST `file_bytes` and return the JSON element list."""
        files = {"files": (filename or "document", file_bytes, content_type)}
        data = {
            "strategy": strategy,
            "coordinates": "true",
            "pdf_infer_table_structure": "true",
        }
        # Send the API key in both header styles so we work whether the
        # proxy uses the OpenAI-style Authorization header or the
        # Unstructured-style `unstructured-api-key`.
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "unstructured-api-key": self.api_key,
        }
        logger.info(
            "Unstructured POST %s file=%r type=%s bytes=%d strategy=%s",
            self.url, filename, content_type, len(file_bytes), strategy,
        )
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.url, files=files, data=data, headers=headers)
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Unstructured backend unreachable at {self.url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            snippet = (resp.text or "").strip()
            if len(snippet) > 500:
                snippet = snippet[:500] + "…"
            logger.warning(
                "Unstructured backend HTTP %d at %s — body=%s",
                resp.status_code, self.url, snippet,
            )
            raise RuntimeError(
                f"Unstructured backend returned HTTP {resp.status_code} from "
                f"{self.url}: {snippet or '(empty body)'}"
            )

        try:
            payload = resp.json()
        except Exception as exc:
            snippet = (resp.text or "")[:200]
            raise RuntimeError(
                f"Unstructured backend at {self.url} returned non-JSON "
                f"(content-type={resp.headers.get('content-type', 'unknown')}): "
                f"{snippet!r} — {exc}"
            ) from exc
        if not isinstance(payload, list):
            raise RuntimeError(
                f"Unstructured backend at {self.url} returned unexpected shape: "
                f"{type(payload).__name__} — expected a JSON array of elements"
            )
        return payload


# ---------------------------------------------------------------------------
# Element list → per-page markdown
# ---------------------------------------------------------------------------

def elements_to_markdown_by_page(elements: list[dict]) -> dict[int, str]:
    """Group Unstructured elements by 1-based page number; return one markdown blob per page."""
    by_page: dict[int, list[dict]] = {}
    for el in elements:
        meta = el.get("metadata") or {}
        page = meta.get("page_number") or 1
        by_page.setdefault(page, []).append(el)

    return {p: _render_page(elems) for p, elems in by_page.items()}


def _render_page(elems: list[dict]) -> str:
    lines: list[str] = []
    for el in elems:
        t = (el.get("type") or "").strip()
        text = (el.get("text") or "").strip()
        meta = el.get("metadata") or {}

        if t == "PageBreak":
            continue
        if not text and t != "Image":
            continue

        if t == "Title":
            lines.append(f"# {text}")
        elif t in ("Header", "Subtitle"):
            lines.append(f"## {text}")
        elif t == "ListItem":
            lines.append(f"- {text}")
        elif t == "Table":
            html = meta.get("text_as_html")
            if html:
                lines.append(html)
            else:
                lines.append(text)
        elif t == "Footer":
            lines.append(f"*{text}*")
        elif t == "FigureCaption":
            lines.append(f"*{text}*")
        elif t == "CodeSnippet":
            lang = (meta.get("language") or "").strip()
            lines.append(f"```{lang}\n{text}\n```")
        elif t == "Formula":
            lines.append(f"`{text}`")
        elif t == "Image":
            alt = text or "image"
            lines.append(f"![{alt}](#)")
        else:
            # NarrativeText, UncategorizedText, Address, EmailAddress, …
            lines.append(text)

        lines.append("")  # blank separator between blocks

    return "\n".join(lines).strip()
