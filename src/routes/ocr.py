import base64
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import Blueprint, jsonify, request

from backends.privatemode import PrivatemodeBackend
from elements import parse_markdown_elements
from pdf import is_pdf, pdf_to_images
from schema import DocumentInput, ImageInput, OCRRequest
from tables import parse_markdown_tables

logger = logging.getLogger(__name__)

ocr_bp = Blueprint("ocr", __name__)
_backend = PrivatemodeBackend()

# Worker threads used to OCR images / PDF pages in parallel. Not exposed
# through the API — this is a server-side knob. Tune via this constant if
# your inference backend has more (or fewer) free slots.
OCR_THREADS = 4


def _read_input_bytes(payload: ImageInput | DocumentInput) -> bytes:
    """Decode base64 or download a URL to raw bytes."""
    if payload.type == "base64":
        return base64.b64decode(payload.value)
    if payload.type == "url":
        with urllib.request.urlopen(payload.value, timeout=30) as resp:  # noqa: S310
            return resp.read()
    raise ValueError(f"Unknown input type: {payload.type!r}")


def _bytes_to_tempfile(data: bytes, suffix: str = ".jpg") -> str:
    tmp = NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _pdf_pages_to_tempfiles(pdf_bytes: bytes, pages: list[int] | None) -> list[str]:
    """Render selected PDF pages as JPEGs on disk and return their paths."""
    images = pdf_to_images(pdf_bytes, pages=pages)
    paths: list[str] = []
    for img in images:
        tmp = NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        # convert RGBA → RGB if needed before JPEG save
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(tmp.name, format="JPEG", quality=92)
        paths.append(tmp.name)
    return paths


@ocr_bp.post("/v1/ocr")
def ocr():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400

    try:
        req = OCRRequest.from_dict(data)
    except (ValueError, KeyError) as exc:
        return jsonify({"error": str(exc)}), 422

    temp_paths: list[str] = []
    doc_size_bytes = 0
    try:
        if req.document is not None:
            doc_bytes = _read_input_bytes(req.document)
            doc_size_bytes = len(doc_bytes)
            if is_pdf(doc_bytes):
                temp_paths = _pdf_pages_to_tempfiles(doc_bytes, req.pages)
            else:
                # Single image document
                temp_paths = [_bytes_to_tempfile(doc_bytes)]
        else:
            for img in req.images:
                img_bytes = _read_input_bytes(img)
                doc_size_bytes += len(img_bytes)
                temp_paths.append(_bytes_to_tempfile(img_bytes))

        # Run each page through OCR in parallel and capture per-page timings.
        page_results: list[dict | None] = [None] * len(temp_paths)
        page_ms: list[int] = [0] * len(temp_paths)

        def _run(i: int, path: str) -> None:
            t0 = time.monotonic()
            try:
                page_results[i] = {
                    "index": i,
                    **_backend._ocr_single(
                        path,
                        req.output.format,
                        req.language,
                        req.output.describe_images,
                    ),
                }
            except Exception as exc:
                logger.error("OCR failed for index %d: %s", i, exc)
                page_results[i] = {"index": i, "content": None, "error": str(exc)}
            finally:
                page_ms[i] = int((time.monotonic() - t0) * 1000)

        t_start = time.monotonic()
        if temp_paths:
            with ThreadPoolExecutor(max_workers=min(OCR_THREADS, len(temp_paths))) as ex:
                list(ex.map(lambda args: _run(*args), enumerate(temp_paths)))
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
    except (ValueError, ImportError) as exc:
        logger.exception("Bad input during OCR")
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        logger.exception("Unexpected error during OCR")
        return jsonify({"error": str(exc)}), 500
    finally:
        for p in temp_paths:
            Path(p).unlink(missing_ok=True)

    # Attach per-page processing time and (optionally) parsed tables / elements.
    pages_out: list[dict] = []
    for i, r in enumerate(page_results):
        assert r is not None
        page = {**r, "processing_ms": page_ms[i]}
        content = page.get("content")
        if req.output.tables and isinstance(content, str):
            page["tables"] = parse_markdown_tables(content)
        if req.output.elements and isinstance(content, str):
            page["elements"] = parse_markdown_elements(content)
        pages_out.append(page)

    response: dict = {
        "model": _backend.model,
        "pages": pages_out,
        "usage_info": {
            "pages_processed": len(temp_paths),
            "doc_size_bytes": doc_size_bytes,
            "processing_ms": elapsed_ms,
        },
    }
    if req.id is not None:
        response["id"] = req.id

    return jsonify(response)
