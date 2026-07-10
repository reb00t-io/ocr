from backends.quality import detect_trailing_repetition, strip_wrapping_fence


class TestDetectTrailingRepetition:
    def test_normal_markdown_passes(self):
        text = "# Invoice\n\n| Item | Price |\n|---|---|\n| A | 1 |\n| B | 2 |\n\nTotal: 3"
        assert detect_trailing_repetition(text) is False

    def test_repeated_phrase_detected(self):
        text = "Some intro text.\n" + "the same phrase " * 30
        assert detect_trailing_repetition(text) is True

    def test_repeated_single_char_detected(self):
        text = "Heading\n" + "a" * 40
        assert detect_trailing_repetition(text) is True

    def test_short_char_runs_are_fine(self):
        # Ellipses, '---' rules, 'aa' etc. are normal typography.
        assert detect_trailing_repetition("Wait for it...") is False
        assert detect_trailing_repetition("Section\n\n---") is False

    def test_repeated_table_row_detected(self):
        row = "| foo | bar |\n"
        text = "| h1 | h2 |\n|---|---|\n" + row * 12
        assert detect_trailing_repetition(text) is True

    def test_whitespace_padding_ignored(self):
        text = "Real content here." + "\n" * 60
        assert detect_trailing_repetition(text) is False

    def test_loop_that_recovers_near_end_detected(self):
        # The loop stops just before the end; the tail-slack recheck
        # must still catch it.
        text = "Intro. " + "loop segment " * 20 + "then a short tail."
        assert detect_trailing_repetition(text) is True

    def test_empty_string(self):
        assert detect_trailing_repetition("") is False


class TestStripWrappingFence:
    def test_markdown_fence_unwrapped(self):
        wrapped = "```markdown\n# Title\n\nBody text.\n```"
        assert strip_wrapping_fence(wrapped) == "# Title\n\nBody text."

    def test_bare_fence_unwrapped(self):
        wrapped = "```\nplain text\n```"
        assert strip_wrapping_fence(wrapped) == "plain text"

    def test_tilde_fence_unwrapped(self):
        wrapped = "~~~md\n# Doc\n~~~"
        assert strip_wrapping_fence(wrapped) == "# Doc"

    def test_content_language_fence_kept(self):
        # A page that IS a code listing must keep its fence.
        code = "```python\nprint('hi')\n```"
        assert strip_wrapping_fence(code) == code

    def test_unfenced_text_untouched(self):
        text = "# Title\n\nBody."
        assert strip_wrapping_fence(text) == text

    def test_inner_code_blocks_survive_unwrapping(self):
        wrapped = "```markdown\n# Doc\n\n```\ncode here\n```\n\nMore text.\n```"
        result = strip_wrapping_fence(wrapped)
        assert result.startswith("# Doc")
        assert "code here" in result
        assert result.endswith("More text.")

    def test_odd_inner_fence_count_untouched(self):
        # Starts and ends with a fence line, but the inner fence count is
        # odd — the outer lines pair up with *inner* fences (real code
        # blocks), they are not a wrapper. Must stay untouched.
        text = "```\nfirst code\n```\nclosing prose"
        text_with_tail_fence = text + "\n```"
        assert strip_wrapping_fence(text_with_tail_fence) == text_with_tail_fence

    def test_fence_in_middle_untouched(self):
        text = "Intro\n```\ncode\n```\nOutro"
        assert strip_wrapping_fence(text) == text

    def test_empty_string(self):
        assert strip_wrapping_fence("") == ""
