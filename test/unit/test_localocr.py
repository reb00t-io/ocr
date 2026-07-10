"""Tests for the localocr package, using an in-process fake LLM callable
so no network or model is required."""
import io
import json

import pytest
from PIL import Image

from localocr import Document, LocalOCR, Page, ocr


def _image(width: int = 1200, height: int = 900, color: str = "white") -> Image.Image:
    return Image.new("RGB", (width, height), color=color)


def _pdf_bytes(num_pages: int = 3) -> bytes:
    pages = [Image.new("RGB", (200, 280), "white") for _ in range(num_pages)]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


def _fake_llm(reply: str = "# Page"):
    """An llm callable that records its invocations."""
    calls: list[str] = []

    def llm(prompt: str, image: Image.Image) -> str:
        calls.append(prompt)
        return reply

    llm.calls = calls
    return llm


class TestOcrOneLiner:
    def test_single_pil_image(self):
        doc = ocr(_image(), llm=_fake_llm("# Hello"))
        assert isinstance(doc, Document)
        assert len(doc) == 1
        assert doc.pages[0].content == "# Hello"
        assert doc.markdown == "# Hello"
        assert doc.ok

    def test_pdf_bytes_all_pages(self):
        doc = ocr(_pdf_bytes(3), llm=_fake_llm("page md"))
        assert len(doc) == 3
        assert [p.index for p in doc] == [0, 1, 2]
        assert doc.markdown == "page md\n\npage md\n\npage md"

    def test_page_selection_string(self):
        doc = ocr(_pdf_bytes(4), llm=_fake_llm(), pages="1,3")
        assert len(doc) == 2

    def test_file_path_source(self, tmp_path):
        path = tmp_path / "scan.png"
        _image().save(path)
        doc = ocr(str(path), llm=_fake_llm("from file"))
        assert doc.pages[0].content == "from file"

    def test_file_like_source(self):
        buf = io.BytesIO()
        _image().save(buf, format="PNG")
        buf.seek(0)
        doc = ocr(buf, llm=_fake_llm("from buffer"))
        assert doc.pages[0].content == "from buffer"

    def test_list_source_mixes_types(self, tmp_path):
        path = tmp_path / "a.png"
        _image().save(path)
        doc = ocr([str(path), _image(), _pdf_bytes(2)], llm=_fake_llm("x"))
        assert len(doc) == 4  # 1 file + 1 PIL + 2 PDF pages

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            ocr("/nonexistent/file.pdf", llm=_fake_llm())

    def test_unsupported_source_raises(self):
        with pytest.raises(TypeError, match="Unsupported source"):
            ocr(12345, llm=_fake_llm())

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="format"):
            ocr(_image(), llm=_fake_llm(), format="html")


class TestEngineOptions:
    def test_language_and_prompt_reach_the_llm(self):
        llm = _fake_llm()
        ocr(_image(), llm=llm, language="de", prompt="summarize")
        assert "de" in llm.calls[0]
        assert "summarize" in llm.calls[0]

    def test_describe_images_reaches_the_llm(self):
        llm = _fake_llm()
        ocr(_image(), llm=llm, describe_images=True)
        assert "Image Descriptions" in llm.calls[0]

    def test_on_page_called_in_order(self):
        seen: list[int] = []
        ocr(_pdf_bytes(3), llm=_fake_llm(), on_page=lambda p: seen.append(p.index))
        assert seen == [0, 1, 2]

    def test_iter_pages_streams_in_order(self):
        engine = LocalOCR(llm=_fake_llm("s"))
        indices = [p.index for p in engine.iter_pages(_pdf_bytes(3))]
        assert indices == [0, 1, 2]


class TestQualityGuardsWithCallable:
    def test_fence_stripped(self):
        doc = ocr(_image(), llm=_fake_llm("```markdown\n# Doc\n```"))
        assert doc.pages[0].content == "# Doc"

    def test_repetition_retried(self):
        replies = iter(["Intro\n" + "loop " * 40, "# Clean"])

        def llm(prompt, image):
            return next(replies)

        doc = ocr(_image(), llm=llm)
        assert doc.pages[0].content == "# Clean"
        assert doc.pages[0].warning is None

    def test_repetition_exhausted_returns_warning(self):
        degenerate = "Intro\n" + "loop " * 40
        doc = ocr(_image(), llm=_fake_llm(degenerate), max_retries=1)
        assert doc.pages[0].warning is not None
        assert "repetition" in doc.pages[0].warning
        assert doc.pages[0].content == degenerate
        assert doc.ok  # warning, not error

    def test_json_format_parsed(self):
        payload = {"title": "T", "content": "C", "sections": []}
        doc = ocr(_image(), llm=_fake_llm(json.dumps(payload)), format="json")
        assert doc.pages[0].content == payload
        assert doc.data == [payload]

    def test_json_wrapped_in_fence_parsed(self):
        payload = {"title": "T", "content": "C", "sections": []}
        doc = ocr(_image(), llm=_fake_llm(f"```json\n{json.dumps(payload)}\n```"),
                  format="json")
        assert doc.pages[0].content == payload

    def test_invalid_json_exhausted_is_page_error(self):
        doc = ocr(_image(), llm=_fake_llm("not json {"), format="json", max_retries=1)
        assert not doc.ok
        assert "invalid JSON" in doc.pages[0].error

    def test_llm_exception_becomes_page_error(self):
        def llm(prompt, image):
            raise RuntimeError("model exploded")

        doc = ocr(_pdf_bytes(2), llm=llm)
        assert not doc.ok
        assert len(doc.errors) == 2
        assert "model exploded" in doc.pages[0].error


class TestDocument:
    def _doc(self) -> Document:
        return Document(
            pages=[
                Page(index=0, content="# One\n\n| a | b |\n|---|---|\n| 1 | 2 |"),
                Page(index=1, content="Two"),
                Page(index=2, content=None, error="boom"),
            ],
            model="m", format="markdown", processing_ms=5,
        )

    def test_merged_skips_failed_pages(self):
        assert self._doc().merged() == "# One\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nTwo"

    def test_merged_paginated(self):
        merged = self._doc().merged(paginate=True)
        assert "<!-- page 0 -->" in merged
        assert "<!-- page 1 -->" in merged

    def test_page_tables_and_elements(self):
        page = self._doc().pages[0]
        tables = page.tables()
        assert tables == [{"header": ["a", "b"], "rows": [["1", "2"]]}]
        assert page.elements()[0] == {"type": "title", "text": "One", "level": 1}

    def test_to_dict_roundtrips_through_json(self):
        d = json.loads(json.dumps(self._doc().to_dict()))
        assert d["usage_info"]["pages_processed"] == 3
        assert d["pages"][2]["error"] == "boom"

    def test_save_markdown(self, tmp_path):
        out = tmp_path / "doc.md"
        self._doc().save(out)
        assert "Two" in out.read_text()

    def test_save_json_by_suffix(self, tmp_path):
        out = tmp_path / "doc.json"
        self._doc().save(out)
        assert json.loads(out.read_text())["model"] == "m"

    def test_iteration_and_indexing(self):
        doc = self._doc()
        assert len(doc) == 3
        assert doc[1].content == "Two"
        assert [p.index for p in doc] == [0, 1, 2]
