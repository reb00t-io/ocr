"""API documentation endpoints.

`GET /doc`  → raw markdown (text/markdown)
`GET /docs` → rendered HTML viewer (uses marked.js client-side)
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, render_template

doc_bp = Blueprint("doc", __name__)

_DOC_PATH = Path(__file__).resolve().parent.parent / "api_doc.md"


def _load_doc() -> str:
    return _DOC_PATH.read_text(encoding="utf-8")


@doc_bp.get("/doc")
def doc_markdown():
    body = _load_doc()
    return Response(body, mimetype="text/markdown")


@doc_bp.get("/docs")
def doc_view():
    return render_template("docs.html")
