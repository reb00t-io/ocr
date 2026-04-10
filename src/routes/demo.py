"""Demo viewer: upload a PDF and see page images side-by-side with extracted markdown."""
from __future__ import annotations

import base64
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, render_template, request

from backends.privatemode import PrivatemodeBackend
from backends.unstructured import (
    UnstructuredBackend,
    elements_to_markdown_by_page,
)
from pdf import is_pdf, pdf_to_images
from schema import _parse_pages

logger = logging.getLogger(__name__)

demo_bp = Blueprint("demo", __name__)
_backend = PrivatemodeBackend()
_unstructured = UnstructuredBackend()

PREVIEW_DPI = 144  # web preview — good visual quality, modest payload size
OCR_DPI = 220      # higher resolution sent to the model for better OCR


def _image_to_data_url(img, *, fmt: str = "JPEG", quality: int = 85) -> str:
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=quality, optimize=True)
    mime = "image/jpeg" if fmt == "JPEG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


@demo_bp.get("/")
@demo_bp.get("/demo")
def demo_index():
    return render_template("demo.html")


def _load_preview_images(raw: bytes):
    """Decode the upload into a list of PIL preview images and the source kind."""
    if is_pdf(raw):
        return pdf_to_images(raw, dpi=PREVIEW_DPI), "pdf"
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    img.load()
    return [img], "image"


@demo_bp.post("/demo/preview")
def demo_preview():
    """Step 1: rasterise the upload into page previews. No OCR runs here."""
    upload = request.files.get("file")
    if upload is None or upload.filename == "":
        return jsonify({"error": "No file uploaded"}), 400

    raw = upload.read()
    if not raw:
        return jsonify({"error": "Empty file"}), 400

    t_render_start = time.monotonic()
    try:
        preview_images, _ = _load_preview_images(raw)
    except Exception as exc:
        logger.exception("Failed to read uploaded document")
        return jsonify({"error": f"Could not parse document: {exc}"}), 422
    render_ms = int((time.monotonic() - t_render_start) * 1000)

    pages = [
        {"index": i, "image": _image_to_data_url(img, fmt="JPEG", quality=82)}
        for i, img in enumerate(preview_images)
    ]
    return jsonify({
        "pages": pages,
        "stats": {"render_ms": render_ms, "pages": len(pages)},
    })


@demo_bp.post("/demo/process")
def demo_process():
    """Step 2: OCR the upload, optionally restricted to a 0-based `pages` selection."""
    upload = request.files.get("file")
    if upload is None or upload.filename == "":
        return jsonify({"error": "No file uploaded"}), 400

    raw = upload.read()
    if not raw:
        return jsonify({"error": "Empty file"}), 400

    pages_str = (request.form.get("pages") or "").strip()
    selection: list[int] | None = None
    if pages_str:
        try:
            selection = _parse_pages(pages_str)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422

    t_total_start = time.monotonic()

    # ---- Phase 1: render images at OCR resolution ------------------------
    t_render_start = time.monotonic()
    try:
        if is_pdf(raw):
            ocr_images = pdf_to_images(raw, pages=selection, dpi=OCR_DPI)
        else:
            if selection is not None and selection != [0]:
                return jsonify({"error": "Page selection only applies to PDF documents"}), 422
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            img.load()
            ocr_images = [img]
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        logger.exception("Failed to read uploaded document")
        return jsonify({"error": f"Could not parse document: {exc}"}), 422
    render_ms = int((time.monotonic() - t_render_start) * 1000)

    # ---- Phase 2: per-page OCR with individual timings -------------------
    import tempfile
    from pathlib import Path

    tmp_paths: list[str] = []
    try:
        for img in ocr_images:
            if img.mode != "RGB":
                img = img.convert("RGB")
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            img.save(tmp.name, format="JPEG", quality=92)
            tmp_paths.append(tmp.name)

        results: list[dict] = [None] * len(tmp_paths)  # type: ignore[list-item]
        page_ms: list[int] = [0] * len(tmp_paths)

        def _run(i: int, path: str) -> None:
            t0 = time.monotonic()
            try:
                results[i] = {"index": i, **_backend._ocr_single(path, "markdown")}
            except Exception as exc:
                logger.error("OCR failed for slot %d: %s", i, exc)
                results[i] = {"index": i, "content": None, "error": str(exc)}
            finally:
                page_ms[i] = int((time.monotonic() - t0) * 1000)

        t_ocr_start = time.monotonic()
        if tmp_paths:
            with ThreadPoolExecutor(max_workers=min(4, len(tmp_paths))) as ex:
                list(ex.map(lambda args: _run(*args), enumerate(tmp_paths)))
        ocr_wall_ms = int((time.monotonic() - t_ocr_start) * 1000)
    finally:
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)

    total_ms = int((time.monotonic() - t_total_start) * 1000)

    # Map results back to *original* page indices so the viewer can match
    # them up with the previews it already rendered.
    pages = []
    for slot, result in enumerate(results):
        original_index = selection[slot] if selection is not None else slot
        if result is None:
            result = {"content": None, "error": "no result"}
        pages.append({
            "index": original_index,
            "markdown": result.get("content") or "",
            "error": result.get("error"),
            "ocr_ms": page_ms[slot] if slot < len(page_ms) else None,
        })

    n = len(page_ms)
    ocr_sum_ms = sum(page_ms)
    stats = {
        "total_ms": total_ms,
        "render_ms": render_ms,
        "ocr_wall_ms": ocr_wall_ms,   # wall-clock time across parallel OCR
        "ocr_sum_ms": ocr_sum_ms,     # summed per-page OCR work
        "ocr_avg_ms": int(ocr_sum_ms / n) if n else 0,
        "ocr_max_ms": max(page_ms) if page_ms else 0,
        "pages": n,
    }

    return jsonify({"model": _backend.model, "pages": pages, "stats": stats})


def _detect_content_type(raw: bytes) -> str:
    if is_pdf(raw):
        return "application/pdf"
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        img.load()
        fmt = (img.format or "").lower()
        return f"image/{fmt}" if fmt else "image/jpeg"
    except Exception:
        return "application/octet-stream"


@demo_bp.post("/demo/unstructured")
def demo_process_unstructured():
    """OCR via the Unstructured-compatible backend.

    Same input shape as `/demo/process`: multipart `file`, optional
    `pages` (0-based, list or range string). Returns the same response
    envelope so the viewer doesn't care which backend ran.
    """
    upload = request.files.get("file")
    if upload is None or upload.filename == "":
        return jsonify({"error": "No file uploaded"}), 400

    raw = upload.read()
    if not raw:
        return jsonify({"error": "Empty file"}), 400

    pages_str = (request.form.get("pages") or "").strip()
    selection: list[int] | None = None
    if pages_str:
        try:
            selection = _parse_pages(pages_str)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422

    t_total_start = time.monotonic()

    # *** Single round trip — Unstructured handles PDF rasterisation
    # server-side, so we hand it the whole document exactly once and
    # filter the response by page number afterwards. Do NOT introduce a
    # per-page loop here: even with a 200-page selection we send the PDF
    # one time. ***
    content_type = _detect_content_type(raw)
    logger.info(
        "Unstructured request: file=%r bytes=%d selection=%s (single upload)",
        upload.filename, len(raw),
        "all" if selection is None else selection,
    )
    t_ocr_start = time.monotonic()
    try:
        elements = _unstructured.partition(raw, upload.filename, content_type)
    except Exception as exc:
        logger.exception("Unstructured backend failure")
        return jsonify({"error": f"Unstructured backend error: {exc}"}), 502
    ocr_wall_ms = int((time.monotonic() - t_ocr_start) * 1000)

    by_page = elements_to_markdown_by_page(elements)
    # Page numbers in Unstructured are 1-based; the rest of the API is 0-based.
    available_zero_based = sorted({p - 1 for p in by_page.keys()})

    if selection is None:
        target_indices = available_zero_based or [0]
    else:
        target_indices = list(selection)

    pages = []
    for idx in target_indices:
        md = by_page.get(idx + 1, "")
        pages.append({
            "index": idx,
            "markdown": md,
            "error": None if md else "no elements returned for this page",
            # Unstructured does one POST for the whole document, so per-page
            # timings aren't available; the UI shows wall-clock under stats.
            "ocr_ms": None,
        })

    n = len(pages)
    total_ms = int((time.monotonic() - t_total_start) * 1000)
    stats = {
        "total_ms": total_ms,
        "render_ms": 0,                # Unstructured does its own rasterisation
        "ocr_wall_ms": ocr_wall_ms,
        "ocr_sum_ms": ocr_wall_ms,
        "ocr_avg_ms": int(ocr_wall_ms / n) if n else 0,
        "ocr_max_ms": ocr_wall_ms,
        "pages": n,
    }

    return jsonify({
        "model": "unstructured",
        "backend": "unstructured",
        "pages": pages,
        "stats": stats,
    })
