import os
from pathlib import Path

from flask import Flask, render_template

app = Flask(__name__)

VERSION = Path("VERSION").read_text().strip()
DEPLOY_DATE = os.environ.get("DEPLOY_DATE", "unknown")


@app.route("/")
def hello():
    return render_template("hello.html", version=VERSION, deploy_date=DEPLOY_DATE)


if __name__ == "__main__":
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi

    print(f"eat v{VERSION} (deployed {DEPLOY_DATE})", flush=True)
    port = int(os.environ["PORT"])
    uvicorn.run(WsgiToAsgi(app), host="0.0.0.0", port=port, log_level="info", lifespan="off")
