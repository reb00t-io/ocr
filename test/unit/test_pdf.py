import io

import pytest
from PIL import Image

from pdf import is_pdf, pdf_to_images


def _make_pdf(num_pages: int = 2) -> bytes:
    """Build a tiny multi-page PDF in memory using PIL."""
    pages = [
        Image.new("RGB", (200, 280), color=("white" if i % 2 == 0 else "lightgray"))
        for i in range(num_pages)
    ]
    buf = io.BytesIO()
    pages[0].save(
        buf,
        format="PDF",
        save_all=True,
        append_images=pages[1:] if len(pages) > 1 else [],
    )
    return buf.getvalue()


class TestIsPdf:
    def test_recognises_pdf_magic(self):
        assert is_pdf(b"%PDF-1.7\n...") is True

    def test_rejects_non_pdf(self):
        assert is_pdf(b"\xff\xd8\xff\xe0JFIF") is False

    def test_short_buffer(self):
        assert is_pdf(b"%PD") is False


class TestPdfToImages:
    def test_returns_one_image_per_page(self):
        data = _make_pdf(num_pages=3)
        images = pdf_to_images(data, dpi=72)
        assert len(images) == 3
        for img in images:
            assert isinstance(img, Image.Image)
            assert img.size[0] > 0 and img.size[1] > 0

    def test_page_selection(self):
        data = _make_pdf(num_pages=3)
        images = pdf_to_images(data, pages=[0, 2], dpi=72)
        assert len(images) == 2

    def test_out_of_range_raises(self):
        data = _make_pdf(num_pages=2)
        with pytest.raises(ValueError, match="out of range"):
            pdf_to_images(data, pages=[5], dpi=72)

    def test_small_page_floored_to_min_dim(self):
        # A 200x280 pt page at 72 dpi would render 200 px wide — far too
        # small for OCR. The renderer must raise the effective DPI so the
        # short side hits min_page_dim.
        data = _make_pdf(num_pages=1)
        (img,) = pdf_to_images(data, dpi=72)
        assert min(img.size) >= 1024

    def test_min_page_dim_zero_disables_floor(self):
        data = _make_pdf(num_pages=1)
        (img,) = pdf_to_images(data, dpi=72, min_page_dim=0)
        assert img.size == (200, 280)

    def test_render_scales_with_dpi(self):
        data = _make_pdf(num_pages=1)
        (img,) = pdf_to_images(data, dpi=300)
        # 200 pt * 300/72 ≈ 833 < 1024 floor → floor wins on this page.
        assert min(img.size) >= 1024
        assert img.width / img.height == pytest.approx(200 / 280, rel=0.02)
