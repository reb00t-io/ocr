from __future__ import annotations

from PIL import Image

_PDF_MAGIC = b"%PDF"

# Small pages (slides, receipts, A6 inserts) rendered at the nominal DPI
# can come out below the resolution VLMs need to read text reliably.
# The renderer raises the effective DPI per page so the shorter side is
# at least this many pixels.
MIN_PAGE_DIM = 1024


def is_pdf(data: bytes) -> bool:
    return data[:4] == _PDF_MAGIC


def pdf_to_images(
    pdf_bytes: bytes,
    pages: list[int] | None = None,
    dpi: int = 300,
    min_page_dim: int = MIN_PAGE_DIM,
) -> list[Image.Image]:
    """Convert PDF bytes to a list of PIL Images.

    Interactive form fields and annotations are flattened into the page
    before rendering, so filled-in form values (text fields, checkboxes)
    appear in the raster instead of silently disappearing.

    Args:
        pdf_bytes: Raw PDF file content.
        pages: 0-based page indices to extract. None means all pages.
        dpi: Nominal render resolution. 300 is recommended for OCR quality.
        min_page_dim: Per-page floor on the shorter side in pixels; the
            effective DPI is raised for pages that would render smaller.

    Returns:
        Ordered list of PIL Images, one per selected page.

    Raises:
        ImportError: If pypdfium2 is not installed.
        ValueError: If any requested page index is out of range.
    """
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
    except ImportError as exc:
        raise ImportError(
            "pypdfium2 is required for PDF support. "
            "Install it with: pip install pypdfium2"
        ) from exc

    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        n_pages = len(doc)
        if pages is None:
            selected = list(range(n_pages))
        else:
            out_of_range = [p for p in pages if p >= n_pages or p < 0]
            if out_of_range:
                raise ValueError(
                    f"Page indices {out_of_range} are out of range "
                    f"for a {n_pages}-page document"
                )
            selected = pages

        # Load form data so field values are part of the page content.
        # Some PDFs have no AcroForm; init_forms is a no-op then.
        doc.init_forms()

        images: list[Image.Image] = []
        for idx in selected:
            page = doc[idx]
            # Bake annotations / filled form fields into the page. A
            # failure here is non-fatal — the page still renders, just
            # without the annotation layer. Re-load the page afterwards:
            # flattening rewrites the page content tree and a stale
            # handle can render the pre-flatten state.
            pdfium_c.FPDFPage_Flatten(page, pdfium_c.FLAT_NORMALDISPLAY)
            page = doc[idx]

            width_pt, height_pt = page.get_size()
            scale = dpi / 72
            short_side_px = min(width_pt, height_pt) * scale
            if min_page_dim and short_side_px < min_page_dim:
                scale *= min_page_dim / short_side_px

            images.append(page.render(scale=scale).to_pil().convert("RGB"))
        return images
    finally:
        doc.close()
