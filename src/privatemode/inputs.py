"""Turn anything a user might reasonably pass into a list of PIL pages.

Accepted source types:

- ``str`` / ``pathlib.Path`` — a file path, or an ``http(s)://`` URL
- ``bytes`` / ``bytearray`` — raw PDF or image content
- ``PIL.Image.Image`` — a single already-loaded page
- a file-like object (anything with ``.read()``)
- a ``list`` / ``tuple`` mixing any of the above

PDFs are rendered locally with pypdfium2 (form fields flattened,
per-page DPI floor — see :mod:`pdf`); nothing but the rendered page
images ever leaves the machine.
"""
from __future__ import annotations

import io
import urllib.request
from pathlib import Path

from PIL import Image

from pdf import is_pdf, pdf_to_images
from schema import _parse_pages


def normalize_pages(pages) -> list[int] | None:
    """Accept `[0, 2]` or `"0-2,5"` (0-based) and return a list of ints."""
    if pages is None:
        return None
    return _parse_pages(pages)


def load_pages(
    source,
    pages: list[int] | str | None = None,
    dpi: int = 300,
) -> list[Image.Image]:
    """Resolve `source` into an ordered list of page images.

    `pages` selects PDF pages (0-based; list or range string like
    ``"0-2,5"``). It is ignored for plain images and for list sources.
    """
    page_list = normalize_pages(pages)

    if isinstance(source, Image.Image):
        return [source]

    if isinstance(source, (list, tuple)):
        out: list[Image.Image] = []
        for item in source:
            out.extend(load_pages(item, pages=None, dpi=dpi))
        return out

    data = _read_bytes(source)
    if is_pdf(data):
        return pdf_to_images(data, pages=page_list, dpi=dpi)

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError(
            f"Source is neither a PDF nor a readable image: {exc}"
        ) from exc
    return [img]


def _read_bytes(source) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)

    if isinstance(source, (str, Path)):
        text = str(source)
        if text.startswith(("http://", "https://")):
            with urllib.request.urlopen(text, timeout=60) as resp:  # noqa: S310
                return resp.read()
        path = Path(source).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"No such file: {path}")
        return path.read_bytes()

    if hasattr(source, "read"):
        data = source.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        return data

    raise TypeError(
        "Unsupported source type: expected a path, URL, bytes, PIL image, "
        f"file-like object, or a list of those — got {type(source).__name__}"
    )
