from __future__ import annotations

from PIL import Image

_PDF_MAGIC = b"%PDF"


def is_pdf(data: bytes) -> bool:
    return data[:4] == _PDF_MAGIC


def pdf_to_images(pdf_bytes: bytes, pages: list[int] | None = None, dpi: int = 300) -> list[Image.Image]:
    """Convert PDF bytes to a list of PIL Images.

    Args:
        pdf_bytes: Raw PDF file content.
        pages: 0-based page indices to extract. None means all pages.
        dpi: Render resolution. 300 is recommended for OCR quality.

    Returns:
        Ordered list of PIL Images, one per selected page.

    Raises:
        ImportError: If pdf2image / poppler is not installed.
        ValueError: If any requested page index is out of range.
    """
    try:
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise ImportError(
            "pdf2image is required for PDF support. "
            "Install it with: pip install pdf2image  "
            "and install poppler: apt-get install poppler-utils  (or brew install poppler)"
        ) from exc

    all_images: list[Image.Image] = convert_from_bytes(pdf_bytes, dpi=dpi)

    if pages is None:
        return all_images

    out_of_range = [p for p in pages if p >= len(all_images) or p < 0]
    if out_of_range:
        raise ValueError(
            f"Page indices {out_of_range} are out of range for a {len(all_images)}-page document"
        )

    return [all_images[p] for p in pages]
