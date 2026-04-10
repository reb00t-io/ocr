import base64
import binascii
import hmac
import os
from pathlib import Path

from flask import Flask, Response, jsonify, request

from routes.demo import demo_bp
from routes.doc import doc_bp
from routes.ocr import ocr_bp

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("OCR_MAX_UPLOAD_MB", "50")) * 1024 * 1024
app.register_blueprint(ocr_bp)
app.register_blueprint(demo_bp)
app.register_blueprint(doc_bp)

_VERSION_CANDIDATES = [Path("VERSION"), Path(__file__).resolve().parent.parent / "VERSION"]
VERSION = next((p.read_text().strip() for p in _VERSION_CANDIDATES if p.exists()), "dev")
DEPLOY_DATE = os.environ.get("DEPLOY_DATE", "unknown")

# ---------------------------------------------------------------------------
# Auth gates
# ---------------------------------------------------------------------------
# Two independent layers, both opt-in via env vars:
#
# 1. AUTH_PASSWORD → HTTP Basic on the human-facing HTML pages (/, /demo,
#    /docs). Browsers handle the prompt natively. Set this so anonymous
#    visitors can't even *see* the demo viewer.
#
# 2. API_KEY → `X-API-Key` header (or `Authorization: Bearer <key>`) on
#    every data endpoint (/v1/ocr, /demo/process, /demo/preview,
#    /demo/unstructured, /demo/mistral, /doc). Set this so anonymous
#    HTTP clients can't actually run OCR.
#
# `/health` is always public so liveness probes work without credentials.
# In dev (neither var set) all gates are no-ops.

_HEALTH_PATH = "/health"
_HTML_PAGE_PATHS = {"/", "/demo", "/docs"}


def _check_basic_auth_header(header: str | None, expected_password: str) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    encoded = header.split(" ", 1)[1].strip()
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    _, _, password = decoded.partition(":")
    return hmac.compare_digest(password, expected_password)


def _check_api_key(expected: str) -> bool:
    """True if the current request carries the right API key.

    Accepts either ``X-API-Key: <key>`` or ``Authorization: Bearer <key>``
    so HTTP clients can use whichever idiom they prefer.
    """
    supplied = request.headers.get("X-API-Key")
    if supplied is None:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth.split(" ", 1)[1].strip()
    if not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


@app.before_request
def _gate_requests():
    if request.path == _HEALTH_PATH:
        return None

    auth_password = os.environ.get("AUTH_PASSWORD")
    api_key = os.environ.get("API_KEY")
    is_html_page = request.path in _HTML_PAGE_PATHS

    # ---- HTML pages: HTTP Basic via AUTH_PASSWORD ------------------------
    if is_html_page and auth_password:
        if not _check_basic_auth_header(request.headers.get("Authorization"), auth_password):
            return Response(
                "Authentication required\n",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="OCR Viewer", charset="UTF-8"'},
                mimetype="text/plain",
            )
        return None

    # ---- Data endpoints: API_KEY header ---------------------------------
    if not is_html_page and api_key:
        if not _check_api_key(api_key):
            return jsonify({
                "error": "Missing or invalid API key. Send X-API-Key: <key> "
                         "or Authorization: Bearer <key>.",
            }), 401
        return None

    # Dev mode (or matching gate not configured): pass through.
    return None


def _api_key_for_template() -> str:
    """Return the API key to embed into HTML page templates so the bundled
    JS can authenticate its backend calls. Empty string when API_KEY is
    not configured (dev mode)."""
    return os.environ.get("API_KEY", "")


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": VERSION,
        "deployed": DEPLOY_DATE,
    })


if __name__ == "__main__":
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi

    print(f"ocr v{VERSION} (deployed {DEPLOY_DATE})", flush=True)
    port = int(os.environ["PORT"])
    uvicorn.run(WsgiToAsgi(app), host="0.0.0.0", port=port, log_level="info", lifespan="off")
