"""
Integration test: real LLM call against localhost:8080/v1.

Run with:
    pytest test/integration/ -v

Skipped automatically if the LLM server is not reachable.
"""
from pathlib import Path

import pytest

SAMPLE_IMAGE = Path(__file__).parent.parent.parent / "data" / "sample_small.jpeg"

# Words that are unambiguously visible in the sample image.
# A correct text extraction must contain all of them.
EXPECTED_WORDS = [
    "dishwasher",
    "rubbish",
    "hoover",
    "shopping",
    "cooking",
    "sister",
]


def _llm_reachable() -> bool:
    import urllib.error
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:8080/v1/models", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture(scope="module", autouse=False)
def require_llm():
    if not _llm_reachable():
        pytest.skip("LLM server not reachable at localhost:8080")


@pytest.mark.integration
def test_image_to_text(require_llm):
    from backends.privatemode import PrivatemodeBackend

    backend = PrivatemodeBackend()
    results = backend.process_images([str(SAMPLE_IMAGE)], output_format="text", threads=1)

    assert len(results) == 1
    result = results[0]

    assert result.get("error") is None, f"OCR returned an error: {result.get('error')}"

    content: str = result["content"]
    assert isinstance(content, str)
    assert len(content) > 50, "Expected substantial text output"

    content_lower = content.lower()
    missing = [w for w in EXPECTED_WORDS if w.lower() not in content_lower]
    assert not missing, (
        f"Expected words not found in output: {missing}\n\nFull output:\n{content}"
    )


@pytest.mark.integration
def test_image_to_markdown(require_llm):
    from backends.privatemode import PrivatemodeBackend

    backend = PrivatemodeBackend()
    results = backend.process_images([str(SAMPLE_IMAGE)], output_format="markdown", threads=1)

    assert len(results) == 1
    result = results[0]

    assert result.get("error") is None
    content: str = result["content"]
    assert isinstance(content, str)
    assert len(content) > 50

    content_lower = content.lower()
    missing = [w for w in EXPECTED_WORDS if w.lower() not in content_lower]
    assert not missing, (
        f"Expected words not found in markdown output: {missing}\n\nFull output:\n{content}"
    )
