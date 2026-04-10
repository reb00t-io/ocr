import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from backends.image import encode_jpeg_image

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8080/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "dummy")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-3-27b")

_PROMPTS = {
    "markdown": (
        "Convert this document image to markdown. "
        "Preserve all structure: headings, lists, tables, code blocks, and formatting. "
        "Return only the markdown content, no preamble."
    ),
    "text": (
        "Extract all text from this image exactly as it appears. "
        "Return plain text only, preserving line breaks. No markdown, no commentary."
    ),
    "json": (
        "Extract the content from this document image and return it as JSON. "
        "The JSON must have the fields: "
        '"title" (string, document title or empty string), '
        '"content" (string, full extracted text), '
        '"sections" (array of objects with "heading" and "content" string fields). '
        "Return only valid JSON, nothing else."
    ),
}

# Suffix appended to the markdown / text prompts when `describe_images=True`.
# Asks the model to add a clearly-labelled section that lists every figure,
# photo, chart or diagram in the page with a short natural-language
# description, in the order they appear in the document.
_DESCRIBE_IMAGES_SUFFIX = (
    " If the document contains any figures, photos, charts, diagrams, "
    "logos or other non-text images, append a final section titled "
    "'## Image Descriptions' to your output. Inside that section list one "
    "numbered entry per image (e.g. '1. ...', '2. ...') describing what "
    "each image shows in one or two sentences, in the order the images "
    "appear in the document. If there are no images, omit the section."
)

# JSON schema used with structured output when format == "json"
_OCR_JSON_SCHEMA = {
    "name": "ocr_result",
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["heading", "content"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "content", "sections"],
        "additionalProperties": False,
    },
}


class PrivatemodeBackend:
    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        api_key: str = LLM_API_KEY,
        model: str = LLM_MODEL,
    ):
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def _ocr_single(
        self,
        image_path: str,
        output_format: str,
        language: str | None = None,
        describe_images: bool = False,
    ) -> dict:
        base64_image = encode_jpeg_image(image_path)
        prompt = _PROMPTS[output_format]
        if language:
            prompt = f"{prompt} The document language is {language}."
        if describe_images and output_format != "json":
            # The JSON prompt has a strict schema; tacking on a free-form
            # section would break the response. Markdown / text are fine.
            prompt = f"{prompt}{_DESCRIBE_IMAGES_SUFFIX}"

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        kwargs: dict = {"model": self.model, "messages": messages}
        if output_format == "json":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": _OCR_JSON_SCHEMA,
            }

        response = self.client.chat.completions.create(**kwargs)
        raw = response.choices[0].message.content

        if output_format == "json":
            return {"content": json.loads(raw)}
        return {"content": raw}

    def process_images(
        self,
        image_paths: list[str],
        output_format: str = "markdown",
        threads: int = 4,
        language: str | None = None,
        describe_images: bool = False,
    ) -> list[dict]:
        """Process a list of images in parallel and return results in original order."""
        results: list[dict | None] = [None] * len(image_paths)

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {
                executor.submit(
                    self._ocr_single, path, output_format, language, describe_images,
                ): i
                for i, path in enumerate(image_paths)
            }
            for future in as_completed(futures):
                i = futures[future]
                try:
                    results[i] = {"index": i, **future.result()}
                except Exception as exc:
                    logger.error("OCR failed for %s: %s", image_paths[i], exc)
                    results[i] = {"index": i, "content": None, "error": str(exc)}

        return results  # type: ignore[return-value]
