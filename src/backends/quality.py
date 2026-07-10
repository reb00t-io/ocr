"""Output-quality guards for VLM-based OCR.

Two failure modes show up with general-purpose vision LLMs that classic
OCR engines don't have:

1. **Degenerate repetition loops** — the model gets stuck emitting the
   same character run, table row or phrase until it hits the token
   limit. `detect_trailing_repetition` spots this so the caller can
   retry with different sampling instead of returning garbage.

2. **Chat-style wrapping** — the model wraps the whole answer in a
   markdown code fence (```` ```markdown … ``` ````) despite being told
   not to. `strip_wrapping_fence` unwraps it.
"""
from __future__ import annotations


def detect_trailing_repetition(
    text: str,
    base_max_repeats: int = 4,
    max_unit_len: int = 250,
    scaling_factor: float = 3.0,
    tail_slack: int = 50,
) -> bool:
    """True if `text` ends in a degenerate repetition loop.

    For every candidate unit length 1..`max_unit_len`, take the suffix
    of that length and count how many times it repeats back-to-back at
    the end of the string. Short units need proportionally more repeats
    to count as degenerate (a trailing "..." or "aa" is normal): the
    threshold is ``base_max_repeats * (1 + scaling_factor / unit_len)``,
    i.e. ~16 repeats for a 1-char unit, ~4 for long units.

    Whitespace-only units are ignored — trailing newline padding is
    harmless and common in legitimate markdown.

    The check runs twice: on the full text and with the last
    `tail_slack` chars cut off, so a loop that "recovers" right before
    the token limit is still caught.
    """
    if _repeats_at_end(text, base_max_repeats, max_unit_len, scaling_factor):
        return True
    if len(text) > tail_slack:
        return _repeats_at_end(
            text[:-tail_slack], base_max_repeats, max_unit_len, scaling_factor
        )
    return False


def _repeats_at_end(
    text: str, base_max_repeats: int, max_unit_len: int, scaling_factor: float
) -> bool:
    n = len(text)
    for unit_len in range(1, max_unit_len + 1):
        if unit_len > n:
            break
        unit = text[n - unit_len:]
        if unit.isspace():
            continue
        max_repeats = int(base_max_repeats * (1 + scaling_factor / unit_len))
        count = 0
        pos = n - unit_len
        while pos >= 0 and text[pos:pos + unit_len] == unit:
            count += 1
            pos -= unit_len
        if count > max_repeats:
            return True
    return False


def strip_wrapping_fence(text: str) -> str:
    """Remove a code fence that wraps the *entire* output.

    Only unwraps when the first line is an opening fence (``` or ~~~,
    optionally with a language tag like ``markdown``) and the last line
    is the matching closing fence. Fences inside the document — actual
    code blocks the OCR produced — are left untouched.
    """
    stripped = text.strip()
    if not stripped:
        return text

    lines = stripped.splitlines()
    if len(lines) < 2:
        return text

    first = lines[0].strip()
    fence = None
    for marker in ("```", "~~~"):
        if first.startswith(marker):
            tag = first[len(marker):].strip().lower()
            # Only unwrap when the tag names our *output format* (or is
            # empty). A content-language tag like ```python means the
            # page itself is a code listing, not chat wrapping.
            if tag in ("", "markdown", "md", "text", "plaintext", "json"):
                fence = marker
            break
    if fence is None or lines[-1].strip() != fence:
        return text

    body = lines[1:-1]
    # A wrapped document may legitimately contain code blocks of its
    # own — those come in *pairs*. An odd number of inner fence lines
    # means the outer pair is actually part of the content (e.g. the
    # document itself ends with a code block); leave it alone then.
    inner_fences = sum(1 for line in body if line.strip().startswith(fence))
    if inner_fences % 2 == 1:
        return text

    return "\n".join(body).strip()
