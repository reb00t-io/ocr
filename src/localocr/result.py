"""Result types returned by :mod:`localocr`.

A :class:`Document` is a list of :class:`Page` objects plus convenience
accessors for the merged output. Both are plain dataclasses — cheap to
inspect, serialize and test against.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from elements import parse_markdown_elements
from tables import parse_markdown_tables


@dataclass
class Page:
    """OCR result for a single page / image."""

    index: int
    #: str for markdown/text output, dict for json output, None on error.
    content: str | dict | None
    #: Set when the page failed entirely; `content` is None then.
    error: str | None = None
    #: Set when content is best-effort (repetition loop / truncation
    #: survived all retries). The content is still usable — inspect the
    #: tail before trusting it.
    warning: str | None = None
    #: Wall-clock milliseconds spent OCRing this page.
    processing_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None

    def tables(self) -> list[dict]:
        """Markdown tables on this page as `{header, rows}` dicts."""
        if isinstance(self.content, str):
            return parse_markdown_tables(self.content)
        return []

    def elements(self) -> list[dict]:
        """Typed block elements (`title`, `paragraph`, `table`, …) on this page."""
        if isinstance(self.content, str):
            return parse_markdown_elements(self.content)
        return []


@dataclass
class Document:
    """Full OCR result: ordered pages plus merged-output helpers."""

    pages: list[Page] = field(default_factory=list)
    model: str = ""
    format: str = "markdown"
    #: Wall-clock milliseconds for the whole (parallel) OCR pass.
    processing_ms: int = 0

    def __iter__(self):
        return iter(self.pages)

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, i: int) -> Page:
        return self.pages[i]

    @property
    def ok(self) -> bool:
        """True when every page succeeded (warnings still count as ok)."""
        return all(p.ok for p in self.pages)

    @property
    def errors(self) -> list[Page]:
        return [p for p in self.pages if not p.ok]

    @property
    def markdown(self) -> str:
        """All pages merged into one markdown string."""
        return self.merged()

    @property
    def text(self) -> str:
        """All pages merged into one plain-text string."""
        return self.merged()

    @property
    def data(self) -> list[dict]:
        """Structured per-page dicts (json format); [] for text formats."""
        return [p.content for p in self.pages if isinstance(p.content, dict)]

    def merged(self, separator: str = "\n\n", paginate: bool = False) -> str:
        """Join string page contents.

        With ``paginate=True`` each page is preceded by an HTML comment
        marker (``<!-- page 3 -->``) so page boundaries survive the merge.
        Failed pages are skipped (see :attr:`errors`).
        """
        parts: list[str] = []
        for p in self.pages:
            if not isinstance(p.content, str):
                continue
            if paginate:
                parts.append(f"<!-- page {p.index} -->\n{p.content}")
            else:
                parts.append(p.content)
        return separator.join(parts)

    def to_dict(self) -> dict:
        """JSON-serializable representation of the whole result."""
        pages = []
        for p in self.pages:
            d: dict = {"index": p.index, "content": p.content}
            if p.error is not None:
                d["error"] = p.error
            if p.warning is not None:
                d["warning"] = p.warning
            d["processing_ms"] = p.processing_ms
            pages.append(d)
        return {
            "model": self.model,
            "format": self.format,
            "pages": pages,
            "usage_info": {
                "pages_processed": len(self.pages),
                "processing_ms": self.processing_ms,
            },
        }

    def save(self, path: str | Path, paginate: bool = False) -> Path:
        """Write the merged result to `path`.

        ``.json`` paths (or json format) get the full structured result;
        anything else gets the merged markdown / text.
        """
        path = Path(path)
        if path.suffix == ".json" or self.format == "json":
            path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        else:
            path.write_text(self.merged(paginate=paginate))
        return path
