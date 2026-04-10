"""Regression tests for empty-string env vars on startup.

CI sometimes passes ``-e VAR=`` (no value) for optional secrets that
weren't configured in the GitHub repo settings. The container must
treat an empty value as "use the default" — `int("")` exploding inside
``main.py`` once cost us a deploy.

The helper functions are unit-tested in process. The full
"does main.py import without crashing when every optional var is
empty" check spawns a fresh Python interpreter so it doesn't pollute
``sys.modules`` for the rest of the test run.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Helper functions — test in-process, no module reload needed.
# ---------------------------------------------------------------------------

class TestEnvIntHelper:
    def test_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("OCR_MAX_UPLOAD_MB", raising=False)
        from main import _env_int
        assert _env_int("OCR_MAX_UPLOAD_MB", 50) == 50

    def test_empty_string_returns_default(self, monkeypatch):
        # The original crash: int("") raises ValueError on import.
        monkeypatch.setenv("OCR_MAX_UPLOAD_MB", "")
        from main import _env_int
        assert _env_int("OCR_MAX_UPLOAD_MB", 50) == 50

    def test_value_parsed(self, monkeypatch):
        monkeypatch.setenv("OCR_MAX_UPLOAD_MB", "123")
        from main import _env_int
        assert _env_int("OCR_MAX_UPLOAD_MB", 50) == 123

    def test_garbage_raises(self, monkeypatch):
        monkeypatch.setenv("OCR_MAX_UPLOAD_MB", "garbage")
        from main import _env_int
        with pytest.raises(ValueError):
            _env_int("OCR_MAX_UPLOAD_MB", 50)


class TestPrivatemodeEnvStr:
    def test_unset_and_empty_both_default(self, monkeypatch):
        from backends.privatemode import _env_str
        monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
        assert _env_str("DOES_NOT_EXIST", "fallback") == "fallback"
        monkeypatch.setenv("DOES_NOT_EXIST", "")
        assert _env_str("DOES_NOT_EXIST", "fallback") == "fallback"
        monkeypatch.setenv("DOES_NOT_EXIST", "value")
        assert _env_str("DOES_NOT_EXIST", "fallback") == "value"


class TestUnstructuredEnvStr:
    def test_unset_and_empty_both_default(self, monkeypatch):
        from backends.unstructured import _env_str
        monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
        assert _env_str("DOES_NOT_EXIST", "fallback") == "fallback"
        monkeypatch.setenv("DOES_NOT_EXIST", "")
        assert _env_str("DOES_NOT_EXIST", "fallback") == "fallback"


class TestMistralEnvStr:
    def test_unset_and_empty_both_default(self, monkeypatch):
        from backends.mistral import _env_str
        monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
        assert _env_str("DOES_NOT_EXIST", "fallback") == "fallback"
        monkeypatch.setenv("DOES_NOT_EXIST", "")
        assert _env_str("DOES_NOT_EXIST", "fallback") == "fallback"

    def test_backend_unconfigured_when_llm_api_key_empty(self, monkeypatch):
        # Real-world bug: CI passes -e LLM_API_KEY= for the optional secret.
        monkeypatch.setenv("LLM_API_KEY", "")
        from backends.mistral import MistralBackend
        backend = MistralBackend()
        assert backend.api_key is None
        assert not backend.configured

    def test_backend_url_falls_back_when_base_empty(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "")
        monkeypatch.setenv("LLM_API_KEY", "k")
        from backends.mistral import MistralBackend
        backend = MistralBackend()
        # _env_str returns the LLM_BASE_URL default ("http://localhost:8080/v1"),
        # then derive_mistral_url appends /ocr.
        assert backend.url == "http://localhost:8080/v1/ocr"


# ---------------------------------------------------------------------------
# Full-startup smoke test in a subprocess so we don't taint sys.modules.
# ---------------------------------------------------------------------------

def test_main_imports_with_every_optional_env_var_empty():
    """Bulletproof regression: spawn a fresh interpreter and verify main.py
    imports cleanly when CI passes ``-e VAR=`` for every optional knob.

    This is the exact failure mode that took down the deploy: the
    container restarted on a loop because ``int("")`` raised in
    ``app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get(...)) * ...``
    before uvicorn could even bind a port.
    """
    env = {
        # Strip pytest's own PYTHONPATH so it doesn't import the test
        # harness; we only want src/ on sys.path.
        **{k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)},
        "PYTHONPATH": str(SRC),
        # Every optional value set to the empty string — same shape CI
        # passes via `-e VAR=` for unset GitHub Actions secrets.
        "LLM_BASE_URL": "",
        "LLM_API_KEY": "",
        "LLM_MODEL": "",
        "MISTRAL_OCR_MODEL": "",
        "AUTH_PASSWORD": "",
        "API_KEY": "",
        "OCR_MAX_UPLOAD_MB": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import main; print(main.app.config['MAX_CONTENT_LENGTH'])"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=15,
    )
    assert result.returncode == 0, (
        f"main.py crashed on import:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert int(result.stdout.strip()) == 50 * 1024 * 1024
