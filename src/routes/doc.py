"""API documentation + comparison endpoints.

- ``GET /doc``        → raw markdown of the API reference
- ``GET /docs``       → HTML viewer that fetches /doc client-side via marked.js
- ``GET /comparison`` → raw markdown of API_COMPARISON.md
- ``GET /compare``    → HTML viewer that fetches /comparison via marked.js

Both viewer pages share `templates/docs.html`; the route hands it the
markdown URL, page title and active-nav slot to render.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, Response, abort, render_template

doc_bp = Blueprint("doc", __name__)

_DOC_PATH = Path(__file__).resolve().parent.parent / "api_doc.md"

# API_COMPARISON.md lives at the project root in dev and is also copied
# next to the rest of the source in the docker image. Try both.
_COMPARISON_CANDIDATES = [
    Path(__file__).resolve().parent.parent.parent / "API_COMPARISON.md",  # dev (./API_COMPARISON.md)
    Path(__file__).resolve().parent.parent / "API_COMPARISON.md",         # docker (/app/API_COMPARISON.md)
]


def _load_doc() -> str:
    return _DOC_PATH.read_text(encoding="utf-8")


def _load_comparison() -> str | None:
    for p in _COMPARISON_CANDIDATES:
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


@doc_bp.get("/doc")
def doc_markdown():
    return Response(_load_doc(), mimetype="text/markdown")


@doc_bp.get("/comparison")
def comparison_markdown():
    body = _load_comparison()
    if body is None:
        abort(404, description="API_COMPARISON.md not found on the server")
    return Response(body, mimetype="text/markdown")


@doc_bp.get("/docs")
def doc_view():
    return render_template(
        "docs.html",
        api_key=os.environ.get("API_KEY", ""),
        page_title="OCR API Docs",
        markdown_url="/doc",
        active_nav="docs",
    )


@doc_bp.get("/compare")
def compare_view():
    return render_template(
        "docs.html",
        api_key=os.environ.get("API_KEY", ""),
        page_title="OCR API Comparison",
        markdown_url="/comparison",
        active_nav="compare",
    )
