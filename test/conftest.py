import sys
from pathlib import Path

import pytest

# Allow bare imports like `from backends.image import ...` in tests,
# mirroring the runtime environment where CWD is src/.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def _disable_auth_by_default(monkeypatch):
    """Most tests run in dev mode (no auth gate). The auth-specific tests
    set AUTH_PASSWORD themselves via their own monkeypatch fixture, which
    runs after this autouse fixture and therefore wins for that test."""
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
