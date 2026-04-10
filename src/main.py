import os
from pathlib import Path

from flask import Flask, jsonify

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


@app.get("/health")
def health():
    return jsonify({"status": "ok", "version": VERSION})


if __name__ == "__main__":
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi

    print(f"ocr v{VERSION} (deployed {DEPLOY_DATE})", flush=True)
    port = int(os.environ["PORT"])
    uvicorn.run(WsgiToAsgi(app), host="0.0.0.0", port=port, log_level="info", lifespan="off")
