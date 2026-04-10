import pytest

from schema import ImageInput, OCRRequest, OutputOptions, _parse_pages


class TestImageInput:
    def test_valid_base64(self):
        img = ImageInput.from_dict({"type": "base64", "value": "abc123"})
        assert img.type == "base64"
        assert img.value == "abc123"

    def test_valid_url(self):
        img = ImageInput.from_dict({"type": "url", "value": "https://example.com/img.png"})
        assert img.type == "url"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="image type"):
            ImageInput.from_dict({"type": "file", "value": "something"})

    def test_missing_type_raises(self):
        with pytest.raises(ValueError):
            ImageInput.from_dict({"value": "abc"})

    def test_empty_value_raises(self):
        with pytest.raises(ValueError, match="value"):
            ImageInput.from_dict({"type": "base64", "value": ""})


class TestOutputOptions:
    def test_defaults_to_markdown(self):
        opt = OutputOptions.from_dict(None)
        assert opt.format == "markdown"

    def test_empty_dict_defaults(self):
        opt = OutputOptions.from_dict({})
        assert opt.format == "markdown"

    def test_text_format(self):
        opt = OutputOptions.from_dict({"format": "text"})
        assert opt.format == "text"

    def test_json_format(self):
        opt = OutputOptions.from_dict({"format": "json"})
        assert opt.format == "json"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="format"):
            OutputOptions.from_dict({"format": "xml"})

    def test_tables_default_false(self):
        opt = OutputOptions.from_dict({})
        assert opt.tables is False

    def test_tables_true(self):
        opt = OutputOptions.from_dict({"tables": True})
        assert opt.tables is True

    def test_tables_non_bool_raises(self):
        with pytest.raises(ValueError, match="tables"):
            OutputOptions.from_dict({"tables": "yes"})

    def test_elements_default_false(self):
        opt = OutputOptions.from_dict({})
        assert opt.elements is False

    def test_elements_true(self):
        opt = OutputOptions.from_dict({"elements": True})
        assert opt.elements is True

    def test_elements_non_bool_raises(self):
        with pytest.raises(ValueError, match="elements"):
            OutputOptions.from_dict({"elements": 1})

    def test_describe_images_default_false(self):
        opt = OutputOptions.from_dict({})
        assert opt.describe_images is False

    def test_describe_images_true(self):
        opt = OutputOptions.from_dict({"describe_images": True})
        assert opt.describe_images is True

    def test_describe_images_non_bool_raises(self):
        with pytest.raises(ValueError, match="describe_images"):
            OutputOptions.from_dict({"describe_images": "yes"})


class TestOCRRequest:
    def _valid_payload(self, **overrides):
        base = {
            "images": [{"type": "base64", "value": "abc"}],
            "output": {"format": "markdown"},
        }
        base.update(overrides)
        return base

    def test_parses_correctly(self):
        req = OCRRequest.from_dict(self._valid_payload())
        assert len(req.images) == 1
        assert req.images[0].type == "base64"
        assert req.output.format == "markdown"

    def test_defaults_output_to_markdown(self):
        payload = {"images": [{"type": "base64", "value": "x"}]}
        req = OCRRequest.from_dict(payload)
        assert req.output.format == "markdown"

    def test_multiple_images(self):
        payload = {
            "images": [
                {"type": "base64", "value": "aaa"},
                {"type": "url", "value": "https://example.com/b.png"},
            ]
        }
        req = OCRRequest.from_dict(payload)
        assert len(req.images) == 2

    def test_missing_input_message_lists_both_options(self):
        with pytest.raises(ValueError) as exc:
            OCRRequest.from_dict({})
        msg = str(exc.value)
        # Error must name both fields and explain neither was provided.
        assert "images" in msg
        assert "document" in msg
        assert "Neither" in msg or "neither" in msg.lower()

    def test_conflicting_input_message_lists_both_options(self):
        with pytest.raises(ValueError) as exc:
            OCRRequest.from_dict({
                "images": [{"type": "base64", "value": "x"}],
                "document": {"type": "base64", "value": "y"},
            })
        msg = str(exc.value)
        assert "images" in msg
        assert "document" in msg
        assert "both" in msg.lower() or "exactly one" in msg.lower()

    def test_empty_images_raises(self):
        with pytest.raises(ValueError, match="images"):
            OCRRequest.from_dict({"images": []})

    def test_threads_field_no_longer_exists(self):
        # `threads` was removed from the public API. It is configured in
        # routes/ocr.py (OCR_THREADS) and silently ignored if a client sends it.
        req = OCRRequest.from_dict(self._valid_payload(threads=99))
        assert not hasattr(req, "threads")

    def test_invalid_image_propagates(self):
        with pytest.raises(ValueError):
            OCRRequest.from_dict({"images": [{"type": "bad", "value": "x"}]})

    def test_id_default_none(self):
        req = OCRRequest.from_dict(self._valid_payload())
        assert req.id is None

    def test_id_string_is_kept(self):
        req = OCRRequest.from_dict(self._valid_payload(id="req-42"))
        assert req.id == "req-42"

    def test_id_non_string_raises(self):
        with pytest.raises(ValueError, match="id"):
            OCRRequest.from_dict(self._valid_payload(id=42))

    def test_language_default_none(self):
        req = OCRRequest.from_dict(self._valid_payload())
        assert req.language is None

    def test_language_is_stripped(self):
        req = OCRRequest.from_dict(self._valid_payload(language="  de  "))
        assert req.language == "de"

    def test_language_empty_raises(self):
        with pytest.raises(ValueError, match="language"):
            OCRRequest.from_dict(self._valid_payload(language="   "))

    def test_prompt_default_none(self):
        req = OCRRequest.from_dict(self._valid_payload())
        assert req.prompt is None

    def test_prompt_set(self):
        req = OCRRequest.from_dict(self._valid_payload(prompt="summarize each page"))
        assert req.prompt == "summarize each page"

    def test_prompt_is_stripped(self):
        req = OCRRequest.from_dict(self._valid_payload(prompt="  translate to French  "))
        assert req.prompt == "translate to French"

    def test_prompt_empty_string_becomes_none(self):
        # Whitespace-only / empty input is silently treated as unset.
        req = OCRRequest.from_dict(self._valid_payload(prompt=""))
        assert req.prompt is None
        req = OCRRequest.from_dict(self._valid_payload(prompt="   "))
        assert req.prompt is None

    def test_prompt_non_string_raises(self):
        with pytest.raises(ValueError, match="prompt"):
            OCRRequest.from_dict(self._valid_payload(prompt=123))


class TestParsePages:
    def test_list_of_ints(self):
        assert _parse_pages([0, 1, 2]) == [0, 1, 2]

    def test_list_with_string_ints(self):
        assert _parse_pages(["0", "1", "2"]) == [0, 1, 2]

    def test_list_with_invalid_entry_raises(self):
        with pytest.raises(ValueError, match="integers"):
            _parse_pages([0, "abc"])

    def test_simple_range_string(self):
        assert _parse_pages("0-2") == [0, 1, 2]

    def test_single_number_string(self):
        assert _parse_pages("5") == [5]

    def test_mixed_singletons_and_ranges(self):
        assert _parse_pages("0-2,4,7-9") == [0, 1, 2, 4, 7, 8, 9]

    def test_whitespace_tolerant(self):
        assert _parse_pages(" 0 - 2 , 4 , 7 - 9 ") == [0, 1, 2, 4, 7, 8, 9]

    def test_duplicates_preserved(self):
        # We don't dedupe — the user gets exactly what they asked for.
        assert _parse_pages("1,1,2") == [1, 1, 2]

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _parse_pages("")

    def test_whitespace_only_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _parse_pages("   ")

    def test_garbage_string_raises(self):
        with pytest.raises(ValueError, match="invalid page number"):
            _parse_pages("abc")

    def test_garbage_range_raises(self):
        with pytest.raises(ValueError, match="invalid page range"):
            _parse_pages("a-b")

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError, match="reversed"):
            _parse_pages("5-2")

    def test_int_alone_raises(self):
        with pytest.raises(ValueError, match="list of 0-based integers"):
            _parse_pages(7)

    def test_request_with_range_string(self):
        req = OCRRequest.from_dict({
            "document": {"type": "base64", "value": "doc"},
            "pages":    "0-2,5",
        })
        assert req.pages == [0, 1, 2, 5]

    def test_request_with_legacy_list(self):
        req = OCRRequest.from_dict({
            "document": {"type": "base64", "value": "doc"},
            "pages":    [0, 1, 2, 5],
        })
        assert req.pages == [0, 1, 2, 5]
