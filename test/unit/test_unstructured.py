from backends.unstructured import (
    derive_unstructured_url,
    elements_to_markdown_by_page,
)


class TestDeriveUrl:
    # The Privatemode proxy mounts the Unstructured-compatible partition
    # endpoint at the *root* of the host (not under `/v1`), and the path is
    # `/unstructured/general/v0/general` — note the extra `/general/`.
    def test_v1_base(self):
        assert (
            derive_unstructured_url("http://localhost:8080/v1")
            == "http://localhost:8080/unstructured/general/v0/general"
        )

    def test_v1_base_with_trailing_slash(self):
        assert (
            derive_unstructured_url("http://localhost:8080/v1/")
            == "http://localhost:8080/unstructured/general/v0/general"
        )

    def test_bare_host(self):
        assert (
            derive_unstructured_url("http://localhost:8080")
            == "http://localhost:8080/unstructured/general/v0/general"
        )

    def test_remote_host(self):
        assert (
            derive_unstructured_url("https://api.example.com/v1")
            == "https://api.example.com/unstructured/general/v0/general"
        )


class TestElementsToMarkdown:
    def test_groups_by_page_number(self):
        elements = [
            {"type": "Title",         "text": "Invoice", "metadata": {"page_number": 1}},
            {"type": "NarrativeText", "text": "ACME",    "metadata": {"page_number": 1}},
            {"type": "Title",         "text": "Detail",  "metadata": {"page_number": 2}},
            {"type": "ListItem",      "text": "Widget",  "metadata": {"page_number": 2}},
        ]
        out = elements_to_markdown_by_page(elements)
        assert set(out.keys()) == {1, 2}
        assert "# Invoice" in out[1]
        assert "ACME" in out[1]
        assert "# Detail" in out[2]
        assert "- Widget" in out[2]

    def test_table_uses_text_as_html(self):
        elements = [{
            "type": "Table",
            "text": "Item Qty\nWidget 3",
            "metadata": {
                "page_number": 1,
                "text_as_html": "<table><tr><th>Item</th><th>Qty</th></tr><tr><td>Widget</td><td>3</td></tr></table>",
            },
        }]
        out = elements_to_markdown_by_page(elements)
        assert "<table>" in out[1]

    def test_table_falls_back_to_text(self):
        elements = [{"type": "Table", "text": "Item Qty\nWidget 3", "metadata": {"page_number": 1}}]
        out = elements_to_markdown_by_page(elements)
        assert "Widget 3" in out[1]

    def test_default_page_number_is_one(self):
        elements = [{"type": "NarrativeText", "text": "no page", "metadata": {}}]
        out = elements_to_markdown_by_page(elements)
        assert out == {1: "no page"}

    def test_unknown_type_passes_text_through(self):
        elements = [{"type": "Address", "text": "1 Infinite Loop", "metadata": {"page_number": 1}}]
        out = elements_to_markdown_by_page(elements)
        assert "1 Infinite Loop" in out[1]

    def test_pagebreak_is_dropped(self):
        elements = [
            {"type": "NarrativeText", "text": "before", "metadata": {"page_number": 1}},
            {"type": "PageBreak",     "text": "",       "metadata": {"page_number": 1}},
            {"type": "NarrativeText", "text": "after",  "metadata": {"page_number": 1}},
        ]
        out = elements_to_markdown_by_page(elements)
        assert "before" in out[1] and "after" in out[1]
