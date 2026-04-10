"""Parse a page of markdown into a typed list of block-level elements.

This is the cheap, no-LLM version of what tools like Unstructured do
during partitioning. We re-walk the markdown the OCR backend already
produced and label each block by its markdown construct:

- ``title``           — `# heading`        (h1)
- ``section_header``  — `## heading` …     (h2 – h6)
- ``list_item``       — `- foo`, `* foo`, `1. foo`
- ``code``            — fenced code block (``` ``` `` ```)
- ``table``           — pipe table (header + divider + rows)
- ``blockquote``      — `> quoted line`
- ``paragraph``       — anything else, joined across consecutive lines
- ``horizontal_rule`` — `---`, `***`, `___` on its own line

Each element is `{type, text, level?}`. `level` is set on headings
(1–6). The original markdown text is preserved verbatim in `text` for
code blocks and tables; for paragraphs and headings the markdown
markers are stripped.

The parser is intentionally simple — it walks the document line by
line and never recurses. Inline markdown (`**bold**`, `[link](…)`)
is left in place as part of `text`.
"""
from __future__ import annotations

import re

from tables import _is_divider, _looks_like_row  # reuse the table helpers

_HEADING_RE   = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE     = re.compile(r"^(```|~~~)")
_BULLET_RE    = re.compile(r"^\s*([-*+])\s+(.*)$")
_ORDERED_RE   = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_HRULE_RE     = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def parse_markdown_elements(text: str) -> list[dict]:
    """Walk `text` and emit one element dict per markdown block."""
    if not text:
        return []

    elements: list[dict] = []
    lines = text.splitlines()
    n = len(lines)
    i = 0

    def _flush_paragraph(buf: list[str]) -> None:
        if buf:
            elements.append({"type": "paragraph", "text": "\n".join(buf).strip()})

    paragraph_buf: list[str] = []

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Blank line: closes any open paragraph.
        if not stripped:
            _flush_paragraph(paragraph_buf)
            paragraph_buf = []
            i += 1
            continue

        # Fenced code block — collect until matching fence.
        m_fence = _FENCE_RE.match(stripped)
        if m_fence:
            _flush_paragraph(paragraph_buf)
            paragraph_buf = []
            fence = m_fence.group(1)
            language: str | None = stripped[len(fence):].strip() or None
            body: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            if i < n:  # consume the closing fence
                i += 1
            elem: dict = {"type": "code", "text": "\n".join(body)}
            if language:
                elem["language"] = language
            elements.append(elem)
            continue

        # Pipe table — header + divider + body rows.
        if (
            i + 1 < n
            and _looks_like_row(line)
            and _is_divider(lines[i + 1])
        ):
            _flush_paragraph(paragraph_buf)
            paragraph_buf = []
            block: list[str] = [line, lines[i + 1]]
            j = i + 2
            while j < n and _looks_like_row(lines[j]) and not _is_divider(lines[j]):
                block.append(lines[j])
                j += 1
            elements.append({"type": "table", "text": "\n".join(block)})
            i = j
            continue

        # Heading.
        m_h = _HEADING_RE.match(line)
        if m_h:
            _flush_paragraph(paragraph_buf)
            paragraph_buf = []
            level = len(m_h.group(1))
            kind  = "title" if level == 1 else "section_header"
            elements.append({"type": kind, "text": m_h.group(2), "level": level})
            i += 1
            continue

        # Horizontal rule.
        if _HRULE_RE.match(line):
            _flush_paragraph(paragraph_buf)
            paragraph_buf = []
            elements.append({"type": "horizontal_rule", "text": ""})
            i += 1
            continue

        # List item — bullet or ordered.
        m_b = _BULLET_RE.match(line)
        m_o = _ORDERED_RE.match(line)
        if m_b or m_o:
            _flush_paragraph(paragraph_buf)
            paragraph_buf = []
            text_part = (m_b.group(2) if m_b else m_o.group(1)).strip()
            elements.append({"type": "list_item", "text": text_part})
            i += 1
            continue

        # Blockquote — collect contiguous `>`-prefixed lines.
        m_q = _BLOCKQUOTE_RE.match(line)
        if m_q:
            _flush_paragraph(paragraph_buf)
            paragraph_buf = []
            quoted: list[str] = [m_q.group(1)]
            j = i + 1
            while j < n:
                m_q2 = _BLOCKQUOTE_RE.match(lines[j])
                if not m_q2:
                    break
                quoted.append(m_q2.group(1))
                j += 1
            elements.append({"type": "blockquote", "text": "\n".join(quoted).strip()})
            i = j
            continue

        # Plain text — accumulate into the open paragraph.
        paragraph_buf.append(stripped)
        i += 1

    _flush_paragraph(paragraph_buf)
    return elements
