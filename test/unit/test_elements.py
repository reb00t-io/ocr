from elements import parse_markdown_elements


def _types(elems):
    return [e["type"] for e in elems]


class TestParseMarkdownElements:
    def test_empty(self):
        assert parse_markdown_elements("") == []
        assert parse_markdown_elements("\n\n") == []

    def test_h1_is_title(self):
        elems = parse_markdown_elements("# Invoice")
        assert elems == [{"type": "title", "text": "Invoice", "level": 1}]

    def test_h2_through_h6_are_section_headers(self):
        md = "## Two\n### Three\n#### Four\n##### Five\n###### Six\n"
        elems = parse_markdown_elements(md)
        assert _types(elems) == ["section_header"] * 5
        assert [e["level"] for e in elems] == [2, 3, 4, 5, 6]

    def test_paragraph(self):
        md = "Hello world.\nThis is a sentence."
        elems = parse_markdown_elements(md)
        assert elems == [{"type": "paragraph", "text": "Hello world.\nThis is a sentence."}]

    def test_paragraphs_separated_by_blank_lines(self):
        md = "first paragraph.\n\nsecond paragraph."
        elems = parse_markdown_elements(md)
        assert _types(elems) == ["paragraph", "paragraph"]
        assert elems[0]["text"] == "first paragraph."
        assert elems[1]["text"] == "second paragraph."

    def test_bullet_list(self):
        md = "- one\n- two\n- three"
        elems = parse_markdown_elements(md)
        assert _types(elems) == ["list_item", "list_item", "list_item"]
        assert [e["text"] for e in elems] == ["one", "two", "three"]

    def test_ordered_list(self):
        md = "1. first\n2. second\n3. third"
        elems = parse_markdown_elements(md)
        assert _types(elems) == ["list_item", "list_item", "list_item"]
        assert [e["text"] for e in elems] == ["first", "second", "third"]

    def test_fenced_code_block(self):
        md = "```python\ndef foo():\n    return 1\n```"
        elems = parse_markdown_elements(md)
        assert len(elems) == 1
        assert elems[0]["type"] == "code"
        assert elems[0]["language"] == "python"
        assert elems[0]["text"] == "def foo():\n    return 1"

    def test_unfenced_code_no_language(self):
        md = "```\nplain code\n```"
        elems = parse_markdown_elements(md)
        assert elems[0]["type"] == "code"
        assert "language" not in elems[0]
        assert elems[0]["text"] == "plain code"

    def test_table_block(self):
        md = (
            "| a | b |\n"
            "|---|---|\n"
            "| 1 | 2 |\n"
        )
        elems = parse_markdown_elements(md)
        assert len(elems) == 1
        assert elems[0]["type"] == "table"
        assert "| a | b |" in elems[0]["text"]
        assert "| 1 | 2 |" in elems[0]["text"]

    def test_blockquote(self):
        md = "> quoted line one\n> quoted line two"
        elems = parse_markdown_elements(md)
        assert elems == [{"type": "blockquote", "text": "quoted line one\nquoted line two"}]

    def test_horizontal_rule(self):
        md = "before\n\n---\n\nafter"
        elems = parse_markdown_elements(md)
        assert _types(elems) == ["paragraph", "horizontal_rule", "paragraph"]

    def test_mixed_document_preserves_order(self):
        md = (
            "# Invoice\n\n"
            "ACME Corp.\n\n"
            "## Items\n\n"
            "- Widget\n"
            "- Gizmo\n\n"
            "| Item | Qty |\n"
            "|------|-----|\n"
            "| Widget | 3 |\n\n"
            "> Net 30 terms\n\n"
            "```python\nprint('hi')\n```\n"
        )
        elems = parse_markdown_elements(md)
        assert _types(elems) == [
            "title",
            "paragraph",
            "section_header",
            "list_item",
            "list_item",
            "table",
            "blockquote",
            "code",
        ]
        assert elems[0]["text"] == "Invoice"
        assert elems[2]["text"] == "Items"
        assert elems[7]["language"] == "python"
