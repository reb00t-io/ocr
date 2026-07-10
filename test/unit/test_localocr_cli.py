"""CLI tests: patch the engine so no LLM is needed."""
import json
from unittest.mock import patch

from localocr.cli import main
from localocr.result import Document, Page


class _FakeEngine:
    """Stands in for LocalOCR; returns a canned Document."""

    doc = Document(pages=[Page(index=0, content="# Out")], model="m")

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def process(self, source, *, on_page=None, **opts):
        for p in self.doc.pages:
            if on_page:
                on_page(p)
        return self.doc


class TestCli:
    def test_markdown_to_stdout(self, capsys, tmp_path):
        img = tmp_path / "a.png"
        img.write_bytes(b"fake")  # engine is faked; content never read by it
        with patch("localocr.cli.LocalOCR", _FakeEngine):
            rc = main([str(img)])
        captured = capsys.readouterr()
        assert rc == 0
        assert "# Out" in captured.out
        assert "page 0 done" in captured.err

    def test_output_file(self, capsys, tmp_path):
        out = tmp_path / "res.md"
        with patch("localocr.cli.LocalOCR", _FakeEngine):
            rc = main(["input.pdf", "-o", str(out)])
        assert rc == 0
        assert out.read_text().strip() == "# Out"

    def test_quiet_suppresses_progress(self, capsys):
        with patch("localocr.cli.LocalOCR", _FakeEngine):
            main(["input.pdf", "-q"])
        assert capsys.readouterr().err == ""

    def test_json_format_emits_structured_output(self, capsys):
        with patch("localocr.cli.LocalOCR", _FakeEngine):
            rc = main(["input.pdf", "-f", "json", "-q"])
        assert rc == 0
        body = json.loads(capsys.readouterr().out)
        assert body["pages"][0]["content"] == "# Out"

    def test_failed_page_sets_exit_code(self, capsys):
        failing = Document(pages=[Page(index=0, content=None, error="boom")], model="m")
        with patch("localocr.cli.LocalOCR", _FakeEngine), \
                patch.object(_FakeEngine, "doc", failing):
            rc = main(["input.pdf", "-q"])
        assert rc == 1
        assert "failed" in capsys.readouterr().err

    def test_missing_input_exits_2(self, capsys):
        class _Raises(_FakeEngine):
            def process(self, source, **opts):
                raise FileNotFoundError("No such file: nope.pdf")

        with patch("localocr.cli.LocalOCR", _Raises):
            rc = main(["nope.pdf"])
        assert rc == 2
        assert "No such file" in capsys.readouterr().err

    def test_engine_receives_flags(self):
        seen = {}

        class _Records(_FakeEngine):
            def __init__(self, **kwargs):
                seen.update(kwargs)
                super().__init__(**kwargs)

        with patch("localocr.cli.LocalOCR", _Records):
            main(["in.pdf", "--dpi", "220", "--threads", "8",
                  "--model", "gpt-4o", "-q"])
        assert seen["dpi"] == 220
        assert seen["threads"] == 8
        assert seen["model"] == "gpt-4o"
