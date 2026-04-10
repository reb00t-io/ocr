"""Extract GitHub-flavoured markdown tables out of an OCR result.

The OCR backend already produces markdown tables when the document
contains a table. This module turns those embedded tables into
structured `{header, rows}` objects so the API can return them
alongside the rendered markdown — without changing the prompt.

The parser is intentionally tolerant:

- Leading/trailing pipes are optional.
- Alignment markers (`:---`, `:---:`, `---:`) are accepted and ignored.
- Cells are stripped of surrounding whitespace.
- Anything that doesn't look like a header + divider + body is left
  alone.
"""
from __future__ import annotations

import re

_DIVIDER_CELL_RE = re.compile(r"^:?-{3,}:?$")


def _split_row(line: str) -> list[str]:
    """Split a single markdown table row into stripped cell strings."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_divider(line: str) -> bool:
    """True if `line` looks like a markdown table divider row.

    A divider row is one or more pipe-separated cells that each match
    `:?---+:?`. The minimum dash count of three matches the GFM spec
    and avoids false positives on horizontal rules like `---`.
    """
    s = line.strip()
    if not s or "|" not in s:
        # GFM allows pipe-less single-column dividers, but we require
        # at least one pipe to make detection unambiguous.
        return False
    cells = _split_row(s)
    if not cells:
        return False
    return all(_DIVIDER_CELL_RE.match(c) for c in cells)


def _looks_like_row(line: str) -> bool:
    return "|" in line and line.strip() != ""


def parse_markdown_tables(text: str) -> list[dict]:
    """Find every GFM-style table in `text` and return them in document order.

    Each entry is `{"header": [str, ...], "rows": [[str, ...], ...]}`.
    Rows are normalised to the header's column count (truncated or
    padded with empty strings) so downstream consumers can iterate
    safely.
    """
    if not text:
        return []

    tables: list[dict] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        # A table starts with a header row immediately followed by a divider.
        if (
            i + 1 < n
            and _looks_like_row(lines[i])
            and _is_divider(lines[i + 1])
        ):
            header = _split_row(lines[i])
            ncols = len(header)
            rows: list[list[str]] = []
            j = i + 2
            while j < n and _looks_like_row(lines[j]) and not _is_divider(lines[j]):
                row = _split_row(lines[j])
                # Normalise to header width.
                if len(row) < ncols:
                    row = row + [""] * (ncols - len(row))
                elif len(row) > ncols:
                    row = row[:ncols]
                rows.append(row)
                j += 1
            tables.append({"header": header, "rows": rows})
            i = j
        else:
            i += 1

    return tables
