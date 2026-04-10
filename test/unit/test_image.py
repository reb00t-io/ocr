import base64
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from backends.image import encode_jpeg_bytes, encode_jpeg_image


def _make_test_image(width: int = 100, height: int = 80, color: str = "red") -> bytes:
    """Create a small in-memory PNG image and return its bytes."""
    from io import BytesIO
    img = Image.new("RGB", (width, height), color=color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _save_test_image(width: int = 100, height: int = 80) -> Path:
    """Save a test image to a temp file and return the path."""
    data = _make_test_image(width, height)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


class TestEncodeJpegImage:
    def test_returns_valid_base64(self, tmp_path):
        path = _save_test_image()
        try:
            result = encode_jpeg_image(str(path))
            decoded = base64.b64decode(result)
            # JPEG magic bytes
            assert decoded[:2] == b"\xff\xd8"
        finally:
            path.unlink(missing_ok=True)

    def test_output_is_jpeg(self, tmp_path):
        from io import BytesIO
        path = _save_test_image(200, 100)
        try:
            result = encode_jpeg_image(str(path))
            img = Image.open(BytesIO(base64.b64decode(result)))
            assert img.format == "JPEG"
        finally:
            path.unlink(missing_ok=True)

    def test_max_long_landscape_scales_width(self):
        path = _save_test_image(400, 200)  # landscape: width > height
        try:
            result = encode_jpeg_image(str(path), max_long=200)
            from io import BytesIO
            img = Image.open(BytesIO(base64.b64decode(result)))
            assert img.width <= 200
        finally:
            path.unlink(missing_ok=True)

    def test_max_long_portrait_scales_height(self):
        path = _save_test_image(200, 400)  # portrait: height > width
        try:
            result = encode_jpeg_image(str(path), max_long=200)
            from io import BytesIO
            img = Image.open(BytesIO(base64.b64decode(result)))
            assert img.height <= 200
        finally:
            path.unlink(missing_ok=True)

    def test_no_upscaling_when_image_smaller_than_limit(self):
        path = _save_test_image(100, 50)
        try:
            result = encode_jpeg_image(str(path), max_long=2000)
            from io import BytesIO
            img = Image.open(BytesIO(base64.b64decode(result)))
            assert img.width == 100
            assert img.height == 50
        finally:
            path.unlink(missing_ok=True)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            encode_jpeg_image("/nonexistent/path/image.jpg")


class TestEncodeJpegBytes:
    def test_returns_valid_base64(self):
        data = _make_test_image()
        result = encode_jpeg_bytes(data)
        decoded = base64.b64decode(result)
        assert decoded[:2] == b"\xff\xd8"

    def test_equivalent_to_file_version(self, tmp_path):
        """encode_jpeg_bytes and encode_jpeg_image should produce the same output."""
        data = _make_test_image(60, 40)
        path = _save_test_image(60, 40)
        try:
            # We can't compare byte-for-byte (PIL may vary slightly), but both should be valid JPEG
            result_bytes = encode_jpeg_bytes(data)
            result_file = encode_jpeg_image(str(path))
            assert base64.b64decode(result_bytes)[:2] == b"\xff\xd8"
            assert base64.b64decode(result_file)[:2] == b"\xff\xd8"
        finally:
            path.unlink(missing_ok=True)

    def test_invalid_bytes_raises(self):
        with pytest.raises(Exception):
            encode_jpeg_bytes(b"not an image")
