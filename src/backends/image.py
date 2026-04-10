import base64
from io import BytesIO

from PIL import Image


def encode_jpeg_image(image_path: str, max_long: int | None = None, max_short: int | None = None, quality: int = 92) -> str:
    """Load an image from disk, optionally resize it, and return a base64-encoded JPEG string."""
    with Image.open(image_path) as img:
        width, height = img.size
        aspect_ratio = width / height

        if width > height:  # Landscape
            if max_long and width > max_long:
                width = max_long
                height = int(max_long / aspect_ratio)
            if max_short and height > max_short:
                height = max_short
                width = int(max_short * aspect_ratio)
        else:  # Portrait or square
            if max_long and height > max_long:
                height = max_long
                width = int(max_long * aspect_ratio)
            if max_short and width > max_short:
                width = max_short
                height = int(max_short / aspect_ratio)

        resized = img.resize((width, height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        resized.save(buffer, format="JPEG", quality=quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


def encode_jpeg_bytes(image_bytes: bytes, max_long: int | None = None, max_short: int | None = None, quality: int = 92) -> str:
    """Same as encode_jpeg_image but accepts raw image bytes instead of a file path."""
    with Image.open(BytesIO(image_bytes)) as img:
        width, height = img.size
        aspect_ratio = width / height

        if width > height:
            if max_long and width > max_long:
                width = max_long
                height = int(max_long / aspect_ratio)
            if max_short and height > max_short:
                height = max_short
                width = int(max_short * aspect_ratio)
        else:
            if max_long and height > max_long:
                height = max_long
                width = int(max_long * aspect_ratio)
            if max_short and width > max_short:
                width = max_short
                height = int(max_short / aspect_ratio)

        resized = img.resize((width, height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        resized.save(buffer, format="JPEG", quality=quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
