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
# HTTP Basic auth gate
# ---------------------------------------------------------------------------
# Enabled when the `AUTH_PASSWORD` env var is set. When unset, the gate is a
# no-op (dev mode). The username field in the prompt is ignored — only the
# password is checked. `/health` always bypasses so liveness probes work
# without credentials.

_AUTH_BYPASS_PATHS = {"/health"}


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


@app.before_request
def _gate_with_basic_auth():
    expected = os.environ.get("AUTH_PASSWORD")
    if not expected:
        return None  # dev mode — no auth
    if request.path in _AUTH_BYPASS_PATHS:
        return None
    if _check_basic_auth_header(request.headers.get("Authorization"), expected):
        return None
    return Response(
        "Authentication required\n",
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="OCR Viewer", charset="UTF-8"'},
        mimetype="text/plain",
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok", "version": VERSION})


if __name__ == "__main__":
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi

    print(f"ocr v{VERSION} (deployed {DEPLOY_DATE})", flush=True)
    port = int(os.environ["PORT"])
    uvicorn.run(WsgiToAsgi(app), host="0.0.0.0", port=port, log_level="info", lifespan="off")
