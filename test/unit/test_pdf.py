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
