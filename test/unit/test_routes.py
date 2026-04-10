"""Route tests for /v1/ocr — backend is patched, so no LLM is required."""
import base64
import io
from unittest.mock import patch

import pytest
from PIL import Image


_last_calls: list[dict] = []
_canned_content: list[str] = []


@pytest.fixture()
def client():
    # Patch the backend before importing main, so the module-level
    # PrivatemodeBackend() in routes.ocr never tries to talk to a real LLM.
    _last_calls.clear()
    _canned_content.clear()

    counter = {"i": 0}

    def fake_ocr_single(self, image_path, output_format, language=None):
        i = counter["i"]
        counter["i"] += 1
        _last_calls.append(
            {"path": image_path, "format": output_format, "language": language}
        )
        if _canned_content:
            content = _canned_content[i % len(_canned_content)]
        else:
            content = f"# Page {i}\n\nfake-{output_format}"
        return {"content": content}

    with patch(
        "backends.privatemode.PrivatemodeBackend._ocr_single",
        new=fake_ocr_single,
    ):
        from main import app

        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


def _png_bytes(color: str = "red") -> bytes:
    img = Image.new("RGB", (40, 30), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pdf_bytes(num_pages: int = 2) -> bytes:
    pages = [Image.new("RGB", (180, 240), color="white") for _ in range(num_pages)]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


class TestHealth:
    def test_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


class TestDocs:
    def test_doc_returns_markdown(self, client):
        resp = client.get("/doc")
        assert resp.status_code == 200
        assert resp.mimetype == "text/markdown"
        body = resp.get_data(as_text=True)
        assert "/v1/ocr" in body
        assert body.lstrip().startswith("#")

    def test_docs_returns_html(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "text/html" in resp.content_type
        body = resp.get_data(as_text=True)
        assert "marked" in body  # client-side markdown renderer is referenced
        assert "/doc" in body    # the page fetches /doc


class TestOcrImageRoute:
    def test_single_base64_image(self, client):
        payload = {
            "images": [
                {"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}
            ],
            "output": {"format": "markdown"},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["usage_info"]["pages_processed"] == 1
        assert body["usage_info"]["doc_size_bytes"] > 0
        assert isinstance(body["usage_info"]["processing_ms"], int)
        assert len(body["pages"]) == 1
        page = body["pages"][0]
        assert page["content"].startswith("# Page 0")
        assert page["index"] == 0
        assert isinstance(page["processing_ms"], int)

    def test_multiple_images(self, client):
        payload = {
            "images": [
                {"type": "base64", "value": base64.b64encode(_png_bytes("red")).decode()},
                {"type": "base64", "value": base64.b64encode(_png_bytes("blue")).decode()},
            ]
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["usage_info"]["pages_processed"] == 2
        assert len(body["pages"]) == 2
        assert all("processing_ms" in p for p in body["pages"])

    def test_request_id_is_echoed(self, client):
        payload = {
            "id": "req-abc-123",
            "images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        assert resp.get_json()["id"] == "req-abc-123"

    def test_request_without_id_omits_id(self, client):
        payload = {"images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}]}
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        assert "id" not in resp.get_json()

    def test_language_hint_passed_to_backend(self, client):
        payload = {
            "language": "de",
            "images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        assert _last_calls[-1]["language"] == "de"

    def test_no_language_passes_none(self, client):
        payload = {"images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}]}
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        assert _last_calls[-1]["language"] is None

    def test_empty_body_returns_400(self, client):
        resp = client.post("/v1/ocr", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_invalid_schema_returns_422(self, client):
        resp = client.post("/v1/ocr", json={})
        assert resp.status_code == 422

    def test_conflicting_inputs_returns_422_with_helpful_message(self, client):
        payload = {
            "images":   [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
            "document": {"type": "base64", "value": base64.b64encode(_png_bytes()).decode()},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 422
        msg = resp.get_json()["error"]
        assert "images" in msg and "document" in msg

    def test_missing_inputs_returns_422_with_helpful_message(self, client):
        resp = client.post("/v1/ocr", json={})
        assert resp.status_code == 422
        msg = resp.get_json()["error"]
        assert "images" in msg and "document" in msg

    def test_tables_flag_returns_structured_tables(self, client):
        _canned_content.append(
            "# Invoice\n\n"
            "| Item | Qty | Price |\n"
            "|------|-----|-------|\n"
            "| Widget | 3 | 12.00 |\n"
            "| Gizmo  | 1 | 4.50  |\n"
        )
        payload = {
            "images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
            "output": {"format": "markdown", "tables": True},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        page = resp.get_json()["pages"][0]
        assert "tables" in page
        assert len(page["tables"]) == 1
        t = page["tables"][0]
        assert t["header"] == ["Item", "Qty", "Price"]
        assert t["rows"][0] == ["Widget", "3", "12.00"]
        # The original markdown content is still there.
        assert "Widget" in page["content"]

    def test_tables_flag_off_omits_field(self, client):
        _canned_content.append(
            "# Invoice\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        )
        payload = {
            "images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
            "output": {"format": "markdown"},  # tables defaults to false
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        page = resp.get_json()["pages"][0]
        assert "tables" not in page

    def test_elements_flag_returns_typed_blocks(self, client):
        _canned_content.append(
            "# Invoice\n\nIntro paragraph.\n\n## Items\n\n- Widget\n- Gizmo\n"
        )
        payload = {
            "images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
            "output": {"format": "markdown", "elements": True},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        page = resp.get_json()["pages"][0]
        assert "elements" in page
        types = [e["type"] for e in page["elements"]]
        assert types == [
            "title",
            "paragraph",
            "section_header",
            "list_item",
            "list_item",
        ]
        # The original markdown content is still there.
        assert "# Invoice" in page["content"]

    def test_elements_flag_off_omits_field(self, client):
        _canned_content.append("# Page\n\nbody")
        payload = {
            "images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
            "output": {"format": "markdown"},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        page = resp.get_json()["pages"][0]
        assert "elements" not in page

    def test_tables_and_elements_can_combine(self, client):
        _canned_content.append(
            "# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        )
        payload = {
            "images": [{"type": "base64", "value": base64.b64encode(_png_bytes()).decode()}],
            "output": {"format": "markdown", "tables": True, "elements": True},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        page = resp.get_json()["pages"][0]
        assert page["tables"][0]["rows"] == [["1", "2"]]
        types = [e["type"] for e in page["elements"]]
        assert "title" in types and "table" in types


class TestOcrPdfRoute:
    def test_pdf_document_renders_all_pages(self, client):
        pdf = _pdf_bytes(num_pages=2)
        payload = {
            "document": {"type": "base64", "value": base64.b64encode(pdf).decode()},
            "output": {"format": "markdown"},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["usage_info"]["pages_processed"] == 2
        assert body["usage_info"]["doc_size_bytes"] == len(pdf)
        assert [r["index"] for r in body["pages"]] == [0, 1]

    def test_pdf_page_selection(self, client):
        pdf = _pdf_bytes(num_pages=3)
        payload = {
            "document": {"type": "base64", "value": base64.b64encode(pdf).decode()},
            "pages": [0, 2],
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["usage_info"]["pages_processed"] == 2

    def test_pdf_page_selection_via_range_string(self, client):
        pdf = _pdf_bytes(num_pages=4)
        payload = {
            "document": {"type": "base64", "value": base64.b64encode(pdf).decode()},
            "pages": "0-1,3",
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["usage_info"]["pages_processed"] == 3
        assert [p["index"] for p in body["pages"]] == [0, 1, 2]  # post-selection indices

    def test_pdf_out_of_range_returns_422(self, client):
        pdf = _pdf_bytes(num_pages=1)
        payload = {
            "document": {"type": "base64", "value": base64.b64encode(pdf).decode()},
            "pages": [99],
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 422

    def test_image_document_treated_as_single_image(self, client):
        png = _png_bytes()
        payload = {
            "document": {"type": "base64", "value": base64.b64encode(png).decode()},
        }
        resp = client.post("/v1/ocr", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["usage_info"]["pages_processed"] == 1
        assert body["usage_info"]["doc_size_bytes"] == len(png)
