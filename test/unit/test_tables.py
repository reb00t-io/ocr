from tables import parse_markdown_tables


class TestParseMarkdownTables:
    def test_no_tables_returns_empty(self):
        assert parse_markdown_tables("just some text\n\nand a paragraph") == []
        assert parse_markdown_tables("") == []

    def test_simple_table(self):
        md = (
            "| Item | Qty | Price |\n"
            "|------|-----|-------|\n"
            "| Widget | 3 | 12.00 |\n"
            "| Gizmo  | 1 | 4.50  |\n"
        )
        tables = parse_markdown_tables(md)
        assert len(tables) == 1
        t = tables[0]
        assert t["header"] == ["Item", "Qty", "Price"]
        assert t["rows"] == [["Widget", "3", "12.00"], ["Gizmo", "1", "4.50"]]

    def test_table_without_outer_pipes(self):
        md = (
            "Item | Qty | Price\n"
            "---  | --- | ---\n"
            "Widget | 3 | 12.00\n"
        )
        tables = parse_markdown_tables(md)
        assert len(tables) == 1
        assert tables[0]["header"] == ["Item", "Qty", "Price"]
        assert tables[0]["rows"] == [["Widget", "3", "12.00"]]

    def test_alignment_markers_are_ignored(self):
        md = (
            "| left | center | right |\n"
            "| :--- | :---:  | ---:  |\n"
            "| a    | b      | c     |\n"
        )
        tables = parse_markdown_tables(md)
        assert tables[0]["header"] == ["left", "center", "right"]
        assert tables[0]["rows"] == [["a", "b", "c"]]

    def test_short_row_is_padded(self):
        md = (
            "| a | b | c |\n"
            "|---|---|---|\n"
            "| 1 | 2 |\n"
        )
        assert parse_markdown_tables(md)[0]["rows"] == [["1", "2", ""]]

    def test_long_row_is_truncated(self):
        md = (
            "| a | b |\n"
            "|---|---|\n"
            "| 1 | 2 | 3 | 4 |\n"
        )
        assert parse_markdown_tables(md)[0]["rows"] == [["1", "2"]]

    def test_two_tables_with_text_between(self):
        md = (
            "Intro paragraph.\n\n"
            "| a | b |\n"
            "|---|---|\n"
            "| 1 | 2 |\n\n"
            "Some text in between.\n\n"
            "| x | y | z |\n"
            "|---|---|---|\n"
            "| 9 | 8 | 7 |\n"
        )
        tables = parse_markdown_tables(md)
        assert len(tables) == 2
        assert tables[0]["header"] == ["a", "b"]
        assert tables[1]["header"] == ["x", "y", "z"]

    def test_horizontal_rule_is_not_a_divider(self):
        md = "Heading\n\n---\n\nbody text\n"
        # `---` standalone (no pipes) is a horizontal rule, not a table divider.
        assert parse_markdown_tables(md) == []

    def test_pipes_in_text_without_divider_are_not_a_table(self):
        md = "This | is | not a table\nJust prose with pipes.\n"
        assert parse_markdown_tables(md) == []

    def test_empty_body_table(self):
        md = (
            "| a | b |\n"
            "|---|---|\n"
        )
        tables = parse_markdown_tables(md)
        assert tables == [{"header": ["a", "b"], "rows": []}]
