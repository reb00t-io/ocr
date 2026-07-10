"""The `OCR` engine: local document handling, any LLM backend.

All PDF/image processing (rendering, form flattening, sizing) happens
on this machine; the only thing sent over the network is one JPEG per
page to whatever LLM you point it at — an OpenAI-compatible endpoint by
default, or any model at all via the ``llm=`` callable.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PIL import Image

from backends.privatemode import MAX_RETRIES, PrivatemodeBackend, build_prompt
from backends.quality import detect_trailing_repetition, strip_wrapping_fence
from privatemode.inputs import load_pages
from privatemode.result import Document, Page
from schema import VALID_FORMATS

logger = logging.getLogger(__name__)

#: Signature for a custom LLM: takes the OCR prompt and one page image,
#: returns the model's raw text output.
LLMCallable = Callable[[str, Image.Image], str]


class OCR:
    """OCR documents locally, sending only page images to an LLM.

    Args:
        base_url: OpenAI-compatible endpoint (default: ``LLM_BASE_URL``
            env var, falling back to ``http://localhost:8080/v1``).
        api_key: API key for that endpoint (default: ``LLM_API_KEY``).
        model: Model name (default: ``LLM_MODEL``).
        llm: Escape hatch for *any* LLM — a callable
            ``(prompt: str, image: PIL.Image) -> str``. When given, the
            OpenAI-style arguments above are ignored. Output-quality
            guards (repetition retries, fence stripping, JSON parsing)
            still apply.
        dpi: PDF render resolution (300 recommended for OCR).
        threads: Pages OCRed concurrently.
        max_retries: Retries per page on degenerate output. Defaults to
            the ``OCR_MAX_RETRIES`` env knob.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        *,
        llm: LLMCallable | None = None,
        dpi: int = 300,
        threads: int = 4,
        max_retries: int | None = None,
    ):
        self.dpi = dpi
        self.threads = threads
        self.max_retries = MAX_RETRIES if max_retries is None else max_retries
        self._llm = llm
        if llm is not None:
            self._backend = None
            self.model = getattr(llm, "__name__", "custom")
        else:
            kwargs: dict = {}
            if base_url is not None:
                kwargs["base_url"] = base_url
            if api_key is not None:
                kwargs["api_key"] = api_key
            if model is not None:
                kwargs["model"] = model
            self._backend = PrivatemodeBackend(**kwargs)
            self.model = self._backend.model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        source: Any,
        *,
        format: str = "markdown",
        pages: list[int] | str | None = None,
        language: str | None = None,
        prompt: str | None = None,
        describe_images: bool = False,
        on_page: Callable[[Page], None] | None = None,
    ) -> Document:
        """OCR `source` and return the complete :class:`Document`.

        Args:
            source: Path, URL, bytes, PIL image, file-like object, or a
                list of those.
            format: ``markdown`` (default), ``text`` or ``json``.
            pages: PDF page selection — 0-based list or range string
                like ``"0-2,5"``.
            language: BCP-47 hint biasing the model on non-English docs.
            prompt: Free-form instruction merged into the OCR prompt as
                the primary directive (e.g. "summarize each page").
            describe_images: Append an "Image Descriptions" section per
                page listing figures/charts.
            on_page: Called with each finished :class:`Page`, in page
                order, from the calling thread — safe for printing
                progress or incremental writes.
        """
        t0 = time.monotonic()
        doc = Document(model=self.model, format=format)
        for page in self.iter_pages(
            source,
            format=format,
            pages=pages,
            language=language,
            prompt=prompt,
            describe_images=describe_images,
        ):
            doc.pages.append(page)
            if on_page is not None:
                on_page(page)
        doc.processing_ms = int((time.monotonic() - t0) * 1000)
        return doc

    def iter_pages(
        self,
        source: Any,
        *,
        format: str = "markdown",
        pages: list[int] | str | None = None,
        language: str | None = None,
        prompt: str | None = None,
        describe_images: bool = False,
    ) -> Iterator[Page]:
        """Like :meth:`process`, but yields pages in order as they finish.

        All pages are OCRed concurrently (``threads`` wide); the iterator
        hands out page N as soon as it — and every page before it — is
        done. Ideal for showing progress on long documents without
        waiting for the slowest page.
        """
        if format not in VALID_FORMATS:
            raise ValueError(f"format must be one of {VALID_FORMATS}, got: {format!r}")

        images = load_pages(source, pages=pages, dpi=self.dpi)
        if not images:
            return

        with ThreadPoolExecutor(max_workers=min(self.threads, len(images))) as ex:
            futures = [
                ex.submit(self._ocr_page, i, img, format, language, describe_images, prompt)
                for i, img in enumerate(images)
            ]
            for future in futures:
                yield future.result()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ocr_page(
        self,
        index: int,
        image: Image.Image,
        output_format: str,
        language: str | None,
        describe_images: bool,
        user_prompt: str | None,
    ) -> Page:
        t0 = time.monotonic()
        try:
            if self._llm is not None:
                result = self._ocr_with_callable(
                    image, output_format, language, describe_images, user_prompt
                )
            else:
                result = self._backend._ocr_single(
                    image, output_format, language, describe_images, user_prompt
                )
            return Page(
                index=index,
                content=result.get("content"),
                warning=result.get("warning"),
                processing_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as exc:
            logger.error("OCR failed for page %d: %s", index, exc)
            return Page(
                index=index,
                content=None,
                error=str(exc),
                processing_ms=int((time.monotonic() - t0) * 1000),
            )

    def _ocr_with_callable(
        self,
        image: Image.Image,
        output_format: str,
        language: str | None,
        describe_images: bool,
        user_prompt: str | None,
    ) -> dict:
        """Run one page through the user-supplied LLM callable.

        The callable is a black box (we can't steer its temperature),
        but the same output-quality guards apply as for the built-in
        backend: fence stripping, repetition detection with retries,
        and JSON parsing with retries. Many callables are stochastic,
        so a plain re-call often clears a degenerate output.
        """
        prompt = build_prompt(output_format, language, describe_images, user_prompt)

        last_content: str | None = None
        last_warning = ""
        for attempt in range(self.max_retries + 1):
            raw = self._llm(prompt, image) or ""

            if output_format == "json":
                try:
                    return {"content": json.loads(strip_wrapping_fence(raw))}
                except json.JSONDecodeError:
                    last_content = raw
                    last_warning = "model returned invalid JSON"
                    if attempt < self.max_retries:
                        logger.warning(
                            "Invalid JSON from llm callable (attempt %d/%d), retrying",
                            attempt + 1, self.max_retries + 1,
                        )
                        continue
                    raise RuntimeError(
                        f"model returned invalid JSON after {attempt + 1} attempts"
                    )

            content = strip_wrapping_fence(raw)
            if not detect_trailing_repetition(content):
                return {"content": content}

            last_content = content
            last_warning = "output ends in a repetition loop"
            if attempt < self.max_retries:
                logger.warning(
                    "Degenerate output from llm callable (attempt %d/%d), retrying",
                    attempt + 1, self.max_retries + 1,
                )

        logger.warning("Returning degraded OCR output: %s", last_warning)
        return {"content": last_content, "warning": last_warning}


def ocr(
    source: Any,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    llm: LLMCallable | None = None,
    dpi: int = 300,
    threads: int = 4,
    max_retries: int | None = None,
    **process_options: Any,
) -> Document:
    """One-liner convenience: ``ocr("doc.pdf").markdown``.

    Constructs a throwaway :class:`OCR` (all constructor arguments
    accepted here) and forwards everything else to
    :meth:`OCR.process`.
    """
    engine = OCR(
        base_url=base_url, api_key=api_key, model=model,
        llm=llm, dpi=dpi, threads=threads, max_retries=max_retries,
    )
    return engine.process(source, **process_options)
