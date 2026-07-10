import base64
import os
from io import BytesIO

from PIL import Image


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw else default


# Sizing guardrails applied to every image sent to the VLM:
#
# - MIN_IMAGE_DIM: small scans (phone photos of receipts, thumbnails)
#   are upscaled so the shorter side is at least this many pixels.
#   VLM text recognition degrades sharply below ~1000 px; LANCZOS
#   upscaling is cheap and recovers most of it. Set to 0 to disable.
# - MAX_IMAGE_PIXELS: total-pixel cap (default 3072×2048 ≈ 6.3 MP).
#   Beyond this, vision encoders downsample anyway — sending more
#   just wastes upload bytes and tokens. Set to 0 to disable.
MIN_IMAGE_DIM = _env_int("OCR_MIN_IMAGE_DIM", 1024)
MAX_IMAGE_PIXELS = _env_int("OCR_MAX_IMAGE_PIXELS", 3072 * 2048)


def _resize_for_ocr(
    img: Image.Image,
    max_long: int | None,
    max_short: int | None,
    min_dim: int,
    max_pixels: int,
) -> Image.Image:
    """Apply OCR sizing rules, preserving aspect ratio throughout.

    Order matters: explicit caller caps (max_long/max_short) first, then
    the min-side upscale floor, then the total-pixel cap. The pixel cap
    runs last so nothing can push the image back over it. When the
    caller passes explicit caps they want a *small* image (previews),
    so the OCR upscale floor is skipped in that case.
    """
    width, height = img.size
    aspect_ratio = width / height

    long_side, short_side = (width, height) if width >= height else (height, width)
    if max_long and long_side > max_long:
        scale = max_long / long_side
        long_side, short_side = max_long, round(short_side * scale)
    if max_short and short_side > max_short:
        scale = max_short / short_side
        short_side, long_side = max_short, round(long_side * scale)
    width, height = (long_side, short_side) if aspect_ratio >= 1 else (short_side, long_side)

    if max_long or max_short:
        min_dim = 0

    if min_dim and min(width, height) < min_dim:
        scale = min_dim / min(width, height)
        width, height = round(width * scale), round(height * scale)

    if max_pixels and width * height > max_pixels:
        scale = (max_pixels / (width * height)) ** 0.5
        width, height = max(1, int(width * scale)), max(1, int(height * scale))

    if (width, height) == img.size:
        return img
    return img.resize((width, height), Image.Resampling.LANCZOS)


def _encode(
    img: Image.Image,
    max_long: int | None,
    max_short: int | None,
    quality: int,
    min_dim: int,
    max_pixels: int,
) -> str:
    if img.mode != "RGB":
        img = img.convert("RGB")
    resized = _resize_for_ocr(img, max_long, max_short, min_dim, max_pixels)
    buffer = BytesIO()
    resized.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def encode_jpeg_image(
    image_path: str,
    max_long: int | None = None,
    max_short: int | None = None,
    quality: int = 92,
    min_dim: int = MIN_IMAGE_DIM,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> str:
    """Load an image from disk, apply OCR sizing rules, and return a base64-encoded JPEG string."""
    with Image.open(image_path) as img:
        return _encode(img, max_long, max_short, quality, min_dim, max_pixels)


def encode_jpeg_bytes(
    image_bytes: bytes,
    max_long: int | None = None,
    max_short: int | None = None,
    quality: int = 92,
    min_dim: int = MIN_IMAGE_DIM,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> str:
    """Same as encode_jpeg_image but accepts raw image bytes instead of a file path."""
    with Image.open(BytesIO(image_bytes)) as img:
        return _encode(img, max_long, max_short, quality, min_dim, max_pixels)
