from dataclasses import dataclass, field
from typing import Literal

VALID_FORMATS = ("markdown", "text", "json")


def _parse_pages(value) -> list[int]:
    """Coerce a `pages` field into a list of 0-based integer indices.

    Accepts either:
    - a list of integers (or int-coercible values), e.g. `[0, 1, 2]`
    - a comma-separated range string, e.g. `"0-2,4,7-9"`

    Page indices are **0-based** to match the rest of our API and
    Mistral's `pages[]`. The demo viewer shows them 1-based for the
    user, and is responsible for the +1 conversion.
    """
    if isinstance(value, list):
        out: list[int] = []
        for p in value:
            try:
                out.append(int(p))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"'pages' entries must be integers, got: {p!r}") from exc
        return out

    if isinstance(value, str):
        if not value.strip():
            raise ValueError("'pages' string must not be empty")
        out = []
        for raw_part in value.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "-" in part:
                a_str, b_str = part.split("-", 1)
                try:
                    start = int(a_str.strip())
                    end = int(b_str.strip())
                except ValueError as exc:
                    raise ValueError(f"invalid page range: {part!r}") from exc
                if end < start:
                    raise ValueError(
                        f"page range {part!r} is reversed (end < start); "
                        f"pages are 0-based, write the range low-to-high"
                    )
                out.extend(range(start, end + 1))
            else:
                try:
                    out.append(int(part))
                except ValueError as exc:
                    raise ValueError(f"invalid page number: {part!r}") from exc
        return out

    raise ValueError(
        "'pages' must be a list of 0-based integers (e.g. [0,1,2]) "
        "or a comma-separated range string (e.g. \"0-2,4,7-9\")"
    )


@dataclass
class ImageInput:
    type: Literal["url", "base64"]
    value: str

    @classmethod
    def from_dict(cls, d: dict) -> "ImageInput":
        t = d.get("type")
        if t not in ("url", "base64"):
            raise ValueError(f"image type must be 'url' or 'base64', got: {t!r}")
        value = d.get("value")
        if not value:
            raise ValueError("image value must not be empty")
        return cls(type=t, value=value)


@dataclass
class DocumentInput:
    type: Literal["url", "base64"]
    value: str

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentInput":
        t = d.get("type")
        if t not in ("url", "base64"):
            raise ValueError(f"document type must be 'url' or 'base64', got: {t!r}")
        value = d.get("value")
        if not value:
            raise ValueError("document value must not be empty")
        return cls(type=t, value=value)


@dataclass
class OutputOptions:
    format: Literal["markdown", "text", "json"] = "markdown"
    tables: bool = False    # parse tables out of the markdown into structured rows
    elements: bool = False  # emit a typed `elements[]` list per page

    @classmethod
    def from_dict(cls, d: dict | None) -> "OutputOptions":
        if not d:
            return cls()
        fmt = d.get("format", "markdown")
        if fmt not in VALID_FORMATS:
            raise ValueError(f"output format must be one of {VALID_FORMATS}, got: {fmt!r}")
        tables = d.get("tables", False)
        if not isinstance(tables, bool):
            raise ValueError(f"output.tables must be a boolean, got: {type(tables).__name__}")
        elements = d.get("elements", False)
        if not isinstance(elements, bool):
            raise ValueError(f"output.elements must be a boolean, got: {type(elements).__name__}")
        return cls(format=fmt, tables=tables, elements=elements)


@dataclass
class OCRRequest:
    # Exactly one of images or document must be set.
    images: list[ImageInput] | None
    document: DocumentInput | None
    pages: list[int] | None  # only applies to document (PDF page selection)
    output: OutputOptions = field(default_factory=OutputOptions)
    # Optional client-supplied request id; echoed back in the response.
    id: str | None = None
    # Optional language hint, BCP-47 (e.g. "en", "de", "en-US"). Forwarded
    # into the OCR prompt to bias the model on non-English documents.
    language: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "OCRRequest":
        has_images = "images" in d
        has_document = "document" in d

        if has_images and has_document:
            raise ValueError(
                "Request contains both 'images' and 'document' — provide exactly one. "
                "Use 'images' for an array of independent images processed in parallel, "
                "or 'document' for a single PDF or image (with optional 'pages' selection)."
            )
        if not has_images and not has_document:
            raise ValueError(
                "Request must include exactly one of 'images' (an array of image inputs) "
                "or 'document' (a PDF or single image). Neither was provided."
            )

        images: list[ImageInput] | None = None
        document: DocumentInput | None = None
        pages: list[int] | None = None

        if has_images:
            images_raw = d["images"]
            if not isinstance(images_raw, list) or len(images_raw) == 0:
                raise ValueError("'images' must be a non-empty list")
            images = [ImageInput.from_dict(img) for img in images_raw]

        if has_document:
            document = DocumentInput.from_dict(d["document"])
            pages_raw = d.get("pages")
            if pages_raw is not None:
                pages = _parse_pages(pages_raw)

        output = OutputOptions.from_dict(d.get("output"))

        req_id = d.get("id")
        if req_id is not None and not isinstance(req_id, str):
            raise ValueError("'id' must be a string")

        language = d.get("language")
        if language is not None:
            if not isinstance(language, str) or not language.strip():
                raise ValueError("'language' must be a non-empty string")
            language = language.strip()

        return cls(
            images=images,
            document=document,
            pages=pages,
            output=output,
            id=req_id,
            language=language,
        )


@dataclass
class ImageResult:
    index: int
    content: str | dict
    error: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"index": self.index, "content": self.content}
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass
class OCRResponse:
    model: str
    results: list[ImageResult]
    usage: dict

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "results": [r.to_dict() for r in self.results],
            "usage": self.usage,
        }
