import hashlib
import hmac
import os
import secrets
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)

from routes.demo import demo_bp
from routes.doc import doc_bp
from routes.ocr import ocr_bp


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, treating empty string the same as unset.

    The deploy pipeline often passes ``-e VAR=`` (no value) for optional
    knobs that come from CI secrets, and ``int("")`` would crash startup.
    """
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    return int(raw)


def _derive_secret_key() -> bytes:
    """Session-signing key.

    Order of preference:
    1. ``SECRET_KEY`` env var (for operators that want to rotate the
       session signing key independently of the login password).
    2. A deterministic hash of ``AUTH_PASSWORD`` (so sessions survive a
       container restart as long as the password doesn't change).
    3. A random per-process key (dev mode).
    """
    explicit = os.environ.get("SECRET_KEY", "")
    if explicit:
        return explicit.encode("utf-8")
    pw = os.environ.get("AUTH_PASSWORD", "")
    if pw:
        return hashlib.sha256(("ocr-viewer-session-v1:" + pw).encode("utf-8")).digest()
    return secrets.token_bytes(32)


app = Flask(__name__)
app.secret_key = _derive_secret_key()
app.config["MAX_CONTENT_LENGTH"] = _env_int("OCR_MAX_UPLOAD_MB", 50) * 1024 * 1024
# Session cookie hardening. The HTML login flow lives on the same
# origin as everything else, so Lax is fine for links back to /demo.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="ocr_session",
)
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
# 1. AUTH_PASSWORD → HTML login form at /login backed by a signed session
#    cookie. Unauthed requests to the human-facing HTML pages (/, /demo,
#    /docs, /compare) get redirected to /login?next=<path>.
#
# 2. API_KEY → `X-API-Key` header (or `Authorization: Bearer <key>`) on
#    every data endpoint (/v1/ocr, /demo/process, /demo/preview,
#    /demo/unstructured, /demo/mistral, /doc, /comparison). Set this so
#    anonymous HTTP clients can't actually run OCR.
#
# `/health` is always public so liveness probes work without credentials.
# `/login` is always public (you need to reach it to submit the form).
# In dev (neither var set) all gates are no-ops.

_PUBLIC_PATHS = {"/health", "/login", "/logout"}
_HTML_PAGE_PATHS = {"/", "/demo", "/docs", "/compare"}


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


def _safe_next_path(raw: str) -> str:
    """Return a same-origin path for post-login redirect.

    Prevents open-redirect attacks: only accept paths starting with a
    single slash. Anything else (absolute URLs, protocol-relative
    `//host/…`, empty) falls back to ``/demo``.
    """
    if not raw:
        return "/demo"
    if raw.startswith("//") or "://" in raw:
        return "/demo"
    if not raw.startswith("/"):
        return "/demo"
    return raw


@app.before_request
def _gate_requests():
    if request.path in _PUBLIC_PATHS:
        return None

    auth_password = os.environ.get("AUTH_PASSWORD")
    api_key = os.environ.get("API_KEY")
    is_html_page = request.path in _HTML_PAGE_PATHS

    # ---- HTML pages: signed session cookie via /login -------------------
    if is_html_page and auth_password:
        if session.get("authed") is True:
            return None
        from urllib.parse import quote
        return redirect(f"/login?next={quote(request.full_path if request.query_string else request.path)}")

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


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@app.get("/login")
def login_form():
    next_url = _safe_next_path(request.args.get("next", ""))
    # If already authed, skip the form entirely.
    if session.get("authed") is True:
        return redirect(next_url)
    return render_template("login.html", next=next_url, error=None)


@app.post("/login")
def login_submit():
    expected = os.environ.get("AUTH_PASSWORD", "")
    supplied = request.form.get("password", "") or ""
    next_url = _safe_next_path(request.form.get("next", ""))

    if not expected:
        # Dev mode — no password configured; any submit succeeds.
        session["authed"] = True
        return redirect(next_url)

    if hmac.compare_digest(supplied, expected):
        session.clear()
        session["authed"] = True
        return redirect(next_url)

    return (
        render_template("login.html", next=next_url, error="Wrong password."),
        401,
    )


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": VERSION,
        "deployed": DEPLOY_DATE,
    })


@app.get("/diag")
def diag():
    """Runtime config snapshot. Guarded by API_KEY (like /doc etc.).

    Useful for answering "is LLM_BASE_URL set to what I think it is?"
    from the deployed container without having to SSH in and read logs.
    Secrets are redacted — we only report whether they're set.
    """
    def _flag(name: str) -> str:
        v = os.environ.get(name) or ""
        return "<set>" if v else "<unset>"

    llm_base_url = os.environ.get("LLM_BASE_URL") or "<unset>"
    derived_chat_url = (
        llm_base_url.rstrip("/") + "/chat/completions"
        if llm_base_url != "<unset>"
        else "<unset>"
    )

    return jsonify({
        "version": VERSION,
        "deployed": DEPLOY_DATE,
        "llm": {
            "base_url": llm_base_url,
            "model": os.environ.get("LLM_MODEL") or "<default>",
            "api_key": _flag("LLM_API_KEY"),
            "chat_completions_url": derived_chat_url,
        },
        "mistral": {
            "model": os.environ.get("MISTRAL_OCR_MODEL") or "<default>",
        },
        "auth": {
            "auth_password": _flag("AUTH_PASSWORD"),
            "api_key":       _flag("API_KEY"),
        },
        "upload": {
            "max_mb": _env_int("OCR_MAX_UPLOAD_MB", 50),
        },
    })


if __name__ == "__main__":
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi

    print(f"ocr v{VERSION} (deployed {DEPLOY_DATE})", flush=True)
    port = int(os.environ["PORT"])
    uvicorn.run(WsgiToAsgi(app), host="0.0.0.0", port=port, log_level="info", lifespan="off")
