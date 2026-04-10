# OCR API Comparison

A side-by-side look at five document-OCR offerings:

| | API | Style |
|---|---|---|
| 1 | **This service** (`POST /v1/ocr`) | LLM-driven, markdown-first |
| 2 | **Mistral OCR** (`POST /v1/ocr` on `api.mistral.ai`) | LLM-driven, markdown-first |
| 3 | **Google Cloud Document AI — Enterprise Document OCR** (`processors/{id}:process`) | classical CV + layout, geometry-first |
| 4 | **Unstructured** (`POST /general/v0/general`) | element-typed output |
| 5 | **Docling** (Python library + `docling-serve` REST) | classical layout + OCR, markdown-first |

The first three are *managed* APIs (you POST to someone else's
infrastructure, or to ours); the last two are open-source projects you
run yourself. We sit on the boundary — we are self-hosted but expose a
REST API of the same shape as the hosted services.

The goal of this doc is to find places where our API surface drifts from
the de-facto shape users expect, and where we are missing features that
are table stakes for a production OCR API.

> Sources: [Mistral OCR docs](https://docs.mistral.ai/capabilities/OCR/basic_ocr/),
> [Mistral OCR endpoint reference](https://docs.mistral.ai/api/endpoint/ocr),
> [Document AI overview](https://docs.cloud.google.com/document-ai/docs/overview),
> [Enterprise Document OCR](https://docs.cloud.google.com/document-ai/docs/enterprise-document-ocr),
> [`processors:process`](https://docs.cloud.google.com/document-ai/docs/process-documents-ocr),
> [Document AI limits](https://docs.cloud.google.com/document-ai/limits),
> [Unstructured API overview](https://docs.unstructured.io/api-reference/api-services/overview),
> [Unstructured Partition API](https://docs.unstructured.io/api-reference/partition/overview),
> [Docling on GitHub](https://github.com/docling-project/docling),
> [Docling quickstart](https://docling-project.github.io/docling/getting_started/quickstart/),
> [docling-serve](https://github.com/docling-project/docling-serve).
> Schema notes captured 2026-04-10.

---

## 1. At-a-glance

### 1.1 Managed APIs

| Capability                       | **Ours**                          | **Mistral OCR**                                  | **Google Document AI (Enterprise Document OCR)**                          |
|----------------------------------|-----------------------------------|--------------------------------------------------|---------------------------------------------------------------------------|
| Endpoint                         | `POST /v1/ocr`                    | `POST /v1/ocr`                                   | `POST .../processors/{id}:process` (sync) / `:batchProcess` (async)       |
| Auth                             | none (self-hosted)                | `Authorization: Bearer …`                        | OAuth / service account                                                   |
| Input — image base64             | ✅                                | ✅ (`image_url` data URL)                         | ✅ (`rawDocument.content` + `mimeType`)                                    |
| Input — image URL                | ✅                                | ✅ (`image_url`)                                  | ❌ (only inline `rawDocument` or `gcsDocument` for sync)                   |
| Input — PDF                      | ✅ (base64 or URL)                | ✅ (`document_url`, also DOCX/PPTX)               | ✅ inline base64 (`rawDocument`) or `gcsDocument`                          |
| Multi-input batch in one call    | ✅ (`images[]`)                   | ❌ (one document per call; batch API separate)    | ❌ on `:process`; ✅ on `:batchProcess` (up to 5 000 files, all in GCS)     |
| Page selection                   | ✅ (`pages[]`, 0-based)           | ✅ (`pages[]`)                                    | ✅ (`processOptions.individualPageSelector` / `fromStart` / `fromEnd`)     |
| Page limit per sync request      | none enforced                     | not documented                                    | **15 pages** (or **30** in imageless mode); 40 MB                          |
| Sync result                      | ✅                                | ✅                                                | ✅ for ≤ 15-page docs (PDFs included)                                      |
| Async / job-based                | ❌                                | ✅ (Batch Inference)                              | ✅ via `:batchProcess` (LRO, GCS in/out)                                   |
| Output formats                   | `markdown` / `text` / `json`      | always markdown per page (+ optional structured doc/bbox annotations) | hierarchical JSON `Document` (text + pages → blocks → paragraphs → lines → tokens) |
| Tables                           | LLM-rendered into markdown        | dedicated `tables[]`, `markdown` or `html`        | not in Enterprise Document OCR — use **Form Parser** processor             |
| Bounding boxes                   | ❌                                | ✅ for images; configurable bbox annotation       | ✅ on every layout element (`boundingPoly` with normalised vertices)       |
| Per-element confidence           | ❌                                | ✅ (`confidence_scores_granularity`: word / page) | ✅ on every layout element + per-language confidence                       |
| Headers / footers                | ❌                                | ✅ (`extract_header` / `extract_footer`)          | ❌ (block type, no semantic header/footer flag)                             |
| Hyperlink preservation           | ❌                                | ✅ (`hyperlinks[]`)                               | ❌                                                                          |
| Image asset extraction           | ❌                                | ✅ (`images[]` with crops + bbox)                 | ❌ (page images returned, no figure crops)                                  |
| Document-level annotation        | ❌                                | ✅ (`document_annotation_format` + prompt → JSON) | ❌ in OCR processor — use **Custom Extractor** / pretrained processors      |
| Per-image structured output      | ✅ (`output.format=json`)         | ❌ (only doc-level)                               | ❌                                                                          |
| Native digital-PDF text          | ❌ (always re-renders + OCRs)     | not documented                                    | ✅ (`processOptions.ocrConfig.enableNativePdfParsing`)                     |
| Image quality scoring            | ❌                                | ❌                                                | ✅ (`enableImageQualityScores` — 8 dimensions)                              |
| Math / checkbox / font extraction| ❌                                | ❌                                                | ✅ premium (`enableMathOcr`, `enableSelectionMarkDetection`, `computeStyleInfo`) |
| Language hints                   | ✅ (`language`, BCP-47)           | ❌                                                | ✅ (`hints.languageHints`, BCP-47)                                          |
| Usage / cost reporting           | `usage_info.pages_processed`, `doc_size_bytes`, `processing_ms` | `usage_info.pages_processed`, `doc_size_bytes` | none in payload (billing-side, per-page tier) |
| Streaming                        | ❌                                | ❌                                                | ❌                                                                          |
| Per-page timings                 | ✅ (`pages[].processing_ms`)      | ❌                                                | ❌                                                                          |
| Idempotency / `id` field         | ✅ (`id`, echoed in response)     | ✅ (`id`)                                         | ❌                                                                          |

### 1.2 Open-source / self-hosted

| Capability                       | **Ours**                          | **Unstructured**                                                       | **Docling** (lib + `docling-serve`)                              |
|----------------------------------|-----------------------------------|------------------------------------------------------------------------|------------------------------------------------------------------|
| Primary surface                  | REST                              | REST (`POST /general/v0/general`, multipart)                           | Python lib (`DocumentConverter`); REST via `docling-serve`       |
| License / hosting                | self-host, MIT-style              | hosted SaaS or `unstructured-io/unstructured-api` (Apache-2.0)         | self-host, MIT (LF AI & Data Foundation)                         |
| Auth                             | none                              | `unstructured-api-key` header on the SaaS; none on self-host           | none                                                              |
| Input — image base64             | ✅                                | ❌ (multipart only)                                                     | ❌ via lib; ✅ via `docling-serve` `kind: file` upload            |
| Input — image URL                | ✅                                | ❌                                                                      | ✅ (`{kind: http, url: …}` in `docling-serve`; URL in lib)        |
| Input — PDF                      | ✅                                | ✅ (multipart `files`)                                                  | ✅ (file path / URL / bytes)                                      |
| Other input formats              | none                              | DOCX, PPTX, XLSX, HTML, EML, MSG, EPUB, RTF, MD, …                     | DOCX, PPTX, XLSX, HTML, LaTeX, USPTO XML, JATS, audio (WAV/MP3)  |
| Multi-input batch in one call    | ✅ (`images[]`)                   | ❌ (one file / call; SDK loops)                                        | ✅ (`sources[]` in `docling-serve`)                               |
| Page selection                   | ✅                                | partial (`starting_page_number`)                                       | ✅ (`PdfPipelineOptions.page_range`)                              |
| Sync result                      | ✅                                | ✅                                                                      | ✅                                                                |
| Async / job-based                | ❌                                | ✅ (Workflows API on the hosted plan)                                  | ❌ in lib; ❌ in current `docling-serve`                          |
| Output formats                   | `markdown` / `text` / `json`      | element list as JSON or `text/csv`; markdown via post-processing      | markdown / HTML / JSON / DocTags                                 |
| Element / block typing           | ❌ (free markdown)                | ✅ (`Title`, `NarrativeText`, `ListItem`, `Table`, `Header`, `Footer`, `Image`, `FigureCaption`, …) | ✅ (page-block tree in JSON / DocTags)                  |
| Tables                           | in markdown                       | ✅ `Table` element (HTML in `metadata.text_as_html`)                    | ✅ structured table model + HTML/markdown export                  |
| Bounding boxes                   | ❌                                | ✅ (`metadata.coordinates`, optional)                                   | ✅ in JSON / DocTags export                                       |
| Per-element confidence           | ❌                                | ❌                                                                      | depends on OCR backend (Tesseract/EasyOCR/RapidOCR)              |
| Headers / footers                | ❌                                | ✅ (element types)                                                     | ✅ (page header/footer detection)                                |
| Hyperlink preservation           | ❌                                | partial (`metadata.links`)                                             | ✅                                                                |
| Image asset extraction           | ❌                                | ✅ (`extract_image_block_types`)                                       | ✅ (image classification + crops)                                |
| Document-level structured extraction | ❌                            | ❌ (chunking yes, schema-driven extraction no)                         | ❌                                                                |
| Per-image structured output      | ✅ (`output.format=json`)         | ❌                                                                      | ❌                                                                |
| Native digital-PDF text          | ❌                                | ✅ (`strategy=fast`)                                                   | ✅ (skips OCR for digital PDFs unless forced)                     |
| Math / formulas                  | ❌                                | ❌                                                                      | ✅ (formula recognition)                                          |
| Code blocks                      | LLM-rendered                      | partial                                                                | ✅ (code block detection)                                         |
| Language hints                   | ✅ (`language`)                   | ✅ (`languages[]`)                                                     | ✅ (`PdfPipelineOptions.ocr_options.lang`)                        |
| Usage / cost reporting           | `usage_info.{pages, bytes, ms}`   | none in payload (billed per page)                                     | n/a (you pay for your own GPU)                                   |
| Streaming                        | ❌                                | ❌                                                                      | ❌                                                                |
| Per-page timings                 | ✅                                | ❌                                                                      | ❌ (some lib timings via logging)                                |
| Idempotency / `id` field         | ✅                                | ❌                                                                      | ❌                                                                |
| Chunking strategies              | ❌                                | ✅ (`by_title`, `by_page`, `basic`, `max_characters`, `overlap`)       | ❌ in core; HybridChunker available as add-on                     |

---

## 2. Wire-format comparison

### 2.1 Ours

```json
POST /v1/ocr
{
  "id":       "req-2026-04-10-002",
  "document": { "type": "base64", "value": "JVBERi0xLjQK..." },
  "pages":    [0, 1, 2],
  "output":   { "format": "markdown" },
  "language": "de"
}
```

```json
200 OK
{
  "id":    "req-2026-04-10-002",
  "model": "gemma-3-27b",
  "pages": [
    { "index": 0, "content": "# Invoice\n...", "processing_ms": 612 },
    { "index": 1, "content": "# Invoice\n...", "processing_ms": 754 },
    { "index": 2, "content": "# Invoice\n...", "processing_ms": 474 }
  ],
  "usage_info": {
    "pages_processed": 3,
    "doc_size_bytes":  184232,
    "processing_ms":   1840
  }
}
```

- One endpoint, two input shapes (`images[]` or `document`), exactly one
  required.
- Each `pages[]` entry is per-image; for PDFs, "image" == "page".
- `content` is a string for `markdown`/`text`, an object for `json`.
- `id` is optional on the request and only echoed back when supplied.
- `language` is an optional BCP-47 hint folded into the OCR prompt.
- Field names (`pages`, `usage_info`, `pages_processed`, `doc_size_bytes`)
  intentionally match Mistral; `processing_ms` (both per-page and overall)
  is our addition.

### 2.2 Mistral OCR

```json
POST /v1/ocr
Authorization: Bearer …
{
  "model": "mistral-ocr-latest",
  "document": {
    "type": "document_url",
    "document_url": "https://example.com/invoice.pdf"
  },
  "pages": [0, 1, 2],
  "table_format": "markdown",
  "extract_header": true,
  "extract_footer": true,
  "include_image_base64": false,
  "confidence_scores_granularity": "page",
  "image_limit": 16,
  "image_min_size": 64,
  "document_annotation_format": { "type": "json_schema", "json_schema": { /* … */ } },
  "document_annotation_prompt": "Return invoice header fields"
}
```

```json
200 OK
{
  "model": "mistral-ocr-latest",
  "pages": [
    {
      "index": 0,
      "markdown": "# Invoice\n...",
      "images": [ { "id": "img_0", "top_left": [..], "bottom_right": [..], "image_base64": null } ],
      "tables": [ /* … */ ],
      "hyperlinks": [],
      "header": "ACME Corp.",
      "footer": "Page 1 / 3",
      "dimensions": { "dpi": 200, "width": 1700, "height": 2200 },
      "confidence_scores": { "page": 0.97 }
    }
  ],
  "document_annotation": { /* structured output for the whole doc */ },
  "usage_info": { "pages_processed": 3, "doc_size_bytes": 184232 }
}
```

- Markdown is the **only** text format — the structure-vs-plaintext
  decision is removed and the client is expected to strip markdown if it
  wants plain text.
- `document_annotation_format` lets you ask for structured output
  *across* the document (an invoice header, a contract metadata block)
  rather than per-page.
- `image_limit` / `image_min_size` give the client cost control over
  image extraction.

### 2.3 Google Document AI — Enterprise Document OCR

The **synchronous** call. Note that the processor must be created in
your project ahead of time; the URL bakes in project, location, and
processor ID.

```json
POST https://us-documentai.googleapis.com/v1/projects/{PROJECT}/locations/us/processors/{PROCESSOR_ID}:process
Authorization: Bearer ya29.…
{
  "rawDocument": {
    "content": "JVBERi0xLjQK...",
    "mimeType": "application/pdf"
  },
  "processOptions": {
    "ocrConfig": {
      "enableNativePdfParsing": true,
      "enableImageQualityScores": true,
      "enableSymbol": false,
      "hints": { "languageHints": ["en", "de"] },
      "premiumFeatures": {
        "enableMathOcr": true,
        "enableSelectionMarkDetection": true,
        "computeStyleInfo": false
      }
    },
    "individualPageSelector": { "pages": [1, 2, 3] }
  }
}
```

```json
200 OK
{
  "document": {
    "mimeType": "application/pdf",
    "text": "Invoice\nACME Corp.\nTotal: 1234.00\n...",
    "pages": [
      {
        "pageNumber": 1,
        "dimension": { "width": 1700, "height": 2200, "unit": "pixels" },
        "image": { "content": "iVBORw0KGgo...", "mimeType": "image/png", "width": 1700, "height": 2200 },
        "layout": { "textAnchor": { "textSegments": [{ "startIndex": "0", "endIndex": "120" }] }, "confidence": 0.97 },
        "detectedLanguages": [{ "languageCode": "en", "confidence": 0.99 }],
        "imageQualityScores": {
          "qualityScore": 0.94,
          "detectedDefects": [{ "type": "quality/defect_blurry", "confidence": 0.02 }]
        },
        "blocks": [
          {
            "layout": {
              "textAnchor": { "textSegments": [{ "startIndex": "0", "endIndex": "8" }] },
              "boundingPoly": {
                "vertices":           [{ "x": 100, "y": 80 }, { "x": 600, "y": 80 }, { "x": 600, "y": 140 }, { "x": 100, "y": 140 }],
                "normalizedVertices": [{ "x": 0.058, "y": 0.036 }, { "x": 0.353, "y": 0.036 }, { "x": 0.353, "y": 0.063 }, { "x": 0.058, "y": 0.063 }]
              },
              "confidence": 0.99
            }
          }
        ],
        "paragraphs": [ /* same shape as blocks */ ],
        "lines":      [ /* same shape */ ],
        "tokens":     [ /* same shape, with detectedBreak */ ],
        "visualElements": [ /* math formulas, checkboxes when enabled */ ]
      }
    ]
  },
  "humanReviewStatus": { "state": "SKIPPED" }
}
```

For documents over 15 pages (or 30 in imageless mode) you switch to
`:batchProcess`. Inputs must live in GCS, the call returns a
long-running operation name, and the result lands as `Document` JSON
back in GCS.

```json
POST .../processors/{PROCESSOR_ID}:batchProcess
{
  "inputDocuments": {
    "gcsDocuments": {
      "documents": [
        { "gcsUri": "gs://bucket/in/contract.pdf", "mimeType": "application/pdf" }
      ]
    }
  },
  "documentOutputConfig": {
    "gcsOutputConfig": { "gcsUri": "gs://bucket/out/", "fieldMask": "text,pages.layout,pages.blocks" }
  }
}
```

- The response is a single `Document` object whose `text` is the entire
  doc as one flat string; `pages[].layout.textAnchor.textSegments`
  point back into that string. Reconstructing "the markdown for page 3
  in reading order" is the client's job.
- Geometry runs page → block → paragraph → line → token (and
  optionally symbol). Every layer has both pixel and normalised
  vertices and a confidence score.
- For tables you stack a **Form Parser** processor; for typed entity
  extraction (invoice totals, contract parties) a **Custom Extractor**;
  for chunking long documents the **Layout Parser**. Document AI is a
  composition of processors, not one fat call.
- Enterprise Document OCR's "premium" features (math LaTeX, checkboxes,
  font/style) are off by default and billed separately.

### 2.4 Unstructured

A `multipart/form-data` POST. The body is a file plus a flat set of
form fields; there is no JSON request envelope.

```http
POST https://api.unstructuredapp.io/general/v0/general
unstructured-api-key: …
Content-Type: multipart/form-data; boundary=…

--…
Content-Disposition: form-data; name="files"; filename="invoice.pdf"
Content-Type: application/pdf

%PDF-1.4
…
--…
Content-Disposition: form-data; name="strategy"
hi_res
--…
Content-Disposition: form-data; name="languages"
eng
--…
Content-Disposition: form-data; name="pdf_infer_table_structure"
true
--…
Content-Disposition: form-data; name="coordinates"
true
--…
Content-Disposition: form-data; name="extract_image_block_types"
["Image","Table"]
--…
Content-Disposition: form-data; name="chunking_strategy"
by_title
--…--
```

```json
200 OK
[
  {
    "type": "Title",
    "element_id": "5b1f7ed3…",
    "text": "Invoice",
    "metadata": {
      "filename": "invoice.pdf",
      "filetype": "application/pdf",
      "page_number": 1,
      "languages": ["eng"],
      "coordinates": {
        "points": [[100,80],[600,80],[600,140],[100,140]],
        "system": "PixelSpace",
        "layout_width":  1700,
        "layout_height": 2200
      }
    }
  },
  {
    "type": "NarrativeText",
    "text": "ACME Corp. issues this invoice on 2026-04-10…",
    "metadata": { "page_number": 1, "parent_id": "5b1f7ed3…" }
  },
  {
    "type": "Table",
    "text": "Item\tQty\tPrice\nWidget\t3\t12.00\n…",
    "metadata": {
      "page_number": 1,
      "text_as_html": "<table><tr><th>Item</th>…</tr>…</table>"
    }
  },
  { "type": "ListItem",     "text": "Net 30 terms",      "metadata": { "page_number": 2 } },
  { "type": "Header",       "text": "ACME Corp.",         "metadata": { "page_number": 2 } },
  { "type": "Footer",       "text": "Page 2 / 3",         "metadata": { "page_number": 2 } },
  { "type": "Image",        "text": "",                   "metadata": { "page_number": 2, "image_base64": "iVBOR…" } },
  { "type": "FigureCaption","text": "Fig. 1 — workflow",  "metadata": { "page_number": 2 } }
]
```

- The response is a **flat array of element objects**, not a tree. The
  reading order is the array order; structure is inferred from the
  `type` field and `metadata.parent_id`.
- Strategies: `auto`, `fast` (digital PDF text only), `hi_res`
  (layout + OCR), `ocr_only`, and the newer `vlm` (route through a
  vision model — `vlm_model_provider` / `vlm_model`).
- There is **no markdown output**: clients reconstruct it themselves
  from the typed elements (or use a helper like
  `unstructured.staging.html.elements_to_html()`).
- Coordinates are returned only when `coordinates=true`.
- Tables show up as a `Table` element whose plain `text` is the
  flattened cells *and* whose `metadata.text_as_html` carries the
  proper grid.
- Chunking is built in (`by_title`, `by_page`, `basic`,
  `max_characters`, `overlap`) — Unstructured's main differentiator
  for RAG pipelines.

### 2.5 Docling

Docling is primarily a **Python library**, with `docling-serve` as an
optional FastAPI wrapper. Both go through the same core pipeline.

**Library:**

```python
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat

opts = PdfPipelineOptions()
opts.do_ocr            = True            # OCR scanned pages
opts.do_table_structure = True           # extract table grid
opts.ocr_options.lang  = ["en", "de"]    # language hint
opts.page_range         = (1, 3)         # 1-indexed inclusive

converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
)
result = converter.convert("invoice.pdf")    # path | URL | bytes-like
doc    = result.document

print(doc.export_to_markdown())   # markdown
doc.export_to_html()              # HTML
doc.export_to_dict()              # lossless JSON
doc.export_to_doctags()           # XML-ish "DocTags" format
```

**REST (`docling-serve`):**

```http
POST http://localhost:5001/v1/convert/source
Content-Type: application/json

{
  "sources": [
    { "kind": "http", "url": "https://arxiv.org/pdf/2408.09869" }
  ],
  "options": {
    "to_formats": ["md", "json"],
    "do_ocr":     true,
    "do_table_structure": true,
    "ocr_lang":   ["en"]
  }
}
```

```json
200 OK
{
  "document": {
    "filename": "2408.09869.pdf",
    "md_content":  "# Docling …",
    "json_content": {
      "schema_name": "DoclingDocument",
      "version":     "1.0.0",
      "name":        "2408.09869",
      "pages": {
        "1": {
          "size": { "width": 612, "height": 792 },
          "image": null
        }
      },
      "texts": [
        {
          "self_ref": "#/texts/0",
          "label":    "title",
          "text":     "Docling Technical Report",
          "prov": [{ "page_no": 1, "bbox": { "l": 134, "t": 86, "r": 478, "b": 110 } }]
        },
        { "self_ref": "#/texts/1", "label": "section_header", "text": "Abstract", "prov": [/* … */] },
        { "self_ref": "#/texts/2", "label": "text",           "text": "Converting PDF documents …", "prov": [/* … */] }
      ],
      "tables": [
        {
          "self_ref": "#/tables/0",
          "data": {
            "table_cells": [
              { "row": 0, "col": 0, "text": "Item",  "row_header": true },
              { "row": 0, "col": 1, "text": "Price", "row_header": true },
              { "row": 1, "col": 0, "text": "Widget" },
              { "row": 1, "col": 1, "text": "12.00" }
            ],
            "num_rows": 2, "num_cols": 2
          },
          "prov": [{ "page_no": 1, "bbox": { /* … */ } }]
        }
      ],
      "pictures": [ /* image crops with bbox + classification */ ]
    }
  },
  "status": "success",
  "errors": [],
  "processing_time": 4.21
}
```

- One pipeline, multiple export formats. Markdown and JSON are not
  separate calls — you pick which `to_formats` you want.
- The `DoclingDocument` JSON is a typed graph (`texts[]`, `tables[]`,
  `pictures[]`, `groups[]`) with cross-references via `self_ref` /
  `parent`. Bounding boxes (`prov[].bbox`) are in PDF point space.
- Element labels: `title`, `section_header`, `text`, `list_item`,
  `caption`, `footnote`, `formula`, `code`, `page_header`,
  `page_footer`. Tables are first-class with cell-level structure.
- OCR backend is pluggable: Tesseract, EasyOCR, RapidOCR, OnnxTR.
- `docling-serve` is FastAPI; auto-docs at `/docs`, demo UI at `/ui`.
  Sync only at the moment.

---

## 3. Per-API summary

### 3.1 Ours — `POST /v1/ocr`

**What it does well**

- One endpoint, two intuitive input shapes, base64 *or* URL on either.
- Synchronous PDF support with no object-store roundtrip.
- The `output.format` switch (`markdown`/`text`/`json`) is unique among
  the three: clients pick the level of structure they want without
  post-processing.
- Multi-image batching in one call (Mistral can't do this).
- Wire shape (`pages[]`, `usage_info.pages_processed`,
  `usage_info.doc_size_bytes`) is deliberately compatible with
  Mistral's, so swapping backends is mostly an `import` change.
- Optional `id` echoed back for client-side correlation; optional
  `language` (BCP-47) hint folded into the OCR prompt.
- Per-page `processing_ms` plus an overall `usage_info.processing_ms`
  — neither Mistral nor Document AI surface this at all.
- Self-hosted, no auth, no per-page billing.

**What it lacks**

- No bounding boxes, no per-element confidence, no geometry at all.
- No table-as-data extraction (tables are baked into the markdown
  string, undifferentiated).
- No headers/footers, no hyperlink list, no image extraction.
- No async / job model — long PDFs block the HTTP connection.
- No streaming or progressive delivery.
- `usage_info` is byte/page/wallclock only — no token counts for cost
  attribution against the underlying LLM.

### 3.2 Mistral OCR

**What it does well**

- Strong structured-document story: `document_annotation_format` +
  `document_annotation_prompt` give you arbitrary JSON over the whole
  document in one round-trip. That's the headline feature.
- Tables, headers, footers, hyperlinks, images, and per-element bboxes
  are all first-class.
- `image_limit` / `image_min_size` are nice cost knobs.
- `confidence_scores_granularity` lets you trade detail for payload
  size.

**What it lacks**

- One document per request; multi-image batches need the separate Batch
  Inference API.
- Markdown is the only text shape — no plain-text mode.
- Per-image / per-page structured output is awkward (you have to do it
  yourself by re-uploading single pages).

### 3.3 Google Document AI — Enterprise Document OCR

> **Why Document AI and not Cloud Vision?** Google's own docs point
> users there: *"If you are detecting text in scanned documents, try
> Document AI for optical character recognition, structured form
> parsing, and entity extraction."* Cloud Vision
> (`images:annotate` / `files:asyncBatchAnnotate`) still works, but it
> has two architectural problems for scanned PDFs: the PDF path is
> **async-only** and requires staging files in **Google Cloud Storage**
> for both input and output. Document AI's Enterprise Document OCR
> processor accepts a base64-inline PDF on a synchronous request (up
> to 15 pages, 30 in imageless mode, 40 MB), and a single
> `batchProcess` call for larger jobs (up to 500 pages, 1 GB).
>
> **There is no single comprehensive Google API.** Document AI is a
> collection of *processors* you instantiate per project: Enterprise
> Document OCR ("digitize" — text + layout), Form Parser (key/value),
> Layout Parser (Gemini-based document chunking), Custom Extractor
> (schema-driven entity extraction), plus pretrained processors for
> invoices/receipts/W-2/etc. For "scanned PDF in, structured text out"
> the right entry point is **Enterprise Document OCR**, optionally
> followed by Form Parser or Custom Extractor for richer fields.

**What it does well**

- A real "POST a PDF, get a result" path: `:process` accepts inline
  base64 PDFs (`rawDocument`) up to 15 pages / 40 MB synchronously, no
  GCS bucket required. This is the thing Cloud Vision *cannot* do.
- The richest geometry of any OCR API: page → block → paragraph → line
  → token (→ symbol), every layer with both pixel and normalised
  bounding polygons and a confidence score, plus per-token
  `detectedBreak` so you can reconstruct line wrapping.
- Document-aware extras that the LLM-driven services do not have:
  `enableNativePdfParsing` (digital PDFs skip OCR entirely),
  `enableImageQualityScores` (8-dimension defect detection — blurry,
  glare, dark, faint, etc.), language hints, automatic deskew/rotation.
- Premium add-ons for math (`enableMathOcr` → LaTeX), checkboxes
  (`enableSelectionMarkDetection`), and font/style info — features
  neither Mistral nor we expose.
- Page selection in sync mode (`individualPageSelector`, `fromStart`,
  `fromEnd`).
- Batch path scales to 500 pages × 5 000 files in one operation.

**What it lacks**

- Not a single API: you compose Enterprise Document OCR with **Form
  Parser** (tables / key-value), **Layout Parser** (chunking),
  **Custom Extractor** (schema-driven entities), and the pretrained
  invoice/receipt processors. Each is a separately provisioned
  *processor* in your project. There is no single endpoint that gives
  you "OCR + tables + structured fields" the way Mistral's
  `document_annotation_format` does.
- No markdown output. The response is a flat `text` string plus
  `textSegments` index pointers; turning that into reading-order
  markdown for a page is the client's problem (or the **Document AI
  Toolbox** library's).
- No headers/footers, no hyperlink list, no figure crops.
- The 15-page sync limit means even moderate scanned docs spill over
  into the async/GCS path.
- Setup overhead: you create the GCP project, enable the API, create a
  processor instance, then bake project + location + processor ID into
  the URL. Compared to "send a JSON body to `/v1/ocr`" it's a lot.
- Premium features are billed separately on top of the per-page rate.

**The "right" Google approach for scanned PDFs**

For "scanned PDF in, structured text out" the answer is:

1. **`:process` on Enterprise Document OCR** for ≤ 15-page docs — best
   layout fidelity and the only sync PDF path Google offers.
2. **`:batchProcess`** for everything bigger, with input/output staged
   through GCS.
3. Stack **Form Parser** if you need cell-level table data.
4. Stack a **Custom Extractor** (or a pretrained processor like Invoice
   Parser) if you need typed entity fields rather than free text.

Cloud Vision's `images:annotate` is fine for individual JPEGs/PNGs but
should be considered legacy for documents — Google's own docs redirect
scanned-document users to Document AI.

### 3.4 Unstructured

**What it does well**

- The widest input matrix of anyone in this comparison: PDF, DOCX,
  PPTX, XLSX, HTML, EML/MSG (email!), EPUB, RTF, MD, plain text,
  images. If your pipeline ingests "any document a user might have",
  Unstructured is the path of least resistance.
- **Element-typed output** is its headline feature: every chunk comes
  back tagged as `Title`, `NarrativeText`, `ListItem`, `Table`,
  `Header`, `Footer`, `Image`, `FigureCaption`, etc. RAG indexers and
  reading-order pipelines can act on type without parsing markdown
  back into structure.
- First-class **chunking strategies** (`by_title`, `by_page`, `basic`,
  `max_characters`, `overlap`) — Unstructured is built around the RAG
  use case and that shows.
- Strategy switch (`fast` / `hi_res` / `ocr_only` / `vlm`) lets you
  trade cost vs. quality without changing the response shape.
- Open-source server (`unstructured-io/unstructured-api`) is a
  drop-in Docker image, so you can self-host the same wire format the
  hosted SaaS offers.

**What it lacks**

- **No native markdown output.** The response is a JSON array of
  elements; producing readable markdown is the client's job.
- One file per request on the legacy `/general/v0/general` endpoint;
  batches require either the SDK loop or the Workflows API.
- Tables come back as a `Table` element with `text_as_html` in
  metadata — usable, but two parses away from a real grid.
- No request `id`, no per-element confidence, no per-page timings.
- The hosted SaaS bills per page; pricing is opaque on the
  marketing page.

**The "we currently offer this" angle**

What we and Unstructured both offer is "POST a doc, get
reading-order text back without an upfront schema". The difference
is that we hand the client one markdown string per page and let
them parse it however they like, while Unstructured hands them a
typed list of elements and lets them assemble markdown themselves.
For RAG / chunking pipelines, Unstructured's element list is easier
to work with; for "show me the page on a screen" the markdown
shape is more direct.

### 3.5 Docling

**What it does well**

- **MIT, runs locally, no SaaS**, hosted by the LF AI & Data
  Foundation. Same self-host story as us, with broader scope: PDF,
  DOCX, PPTX, XLSX, HTML, LaTeX, USPTO patent XML, JATS articles, and
  even audio (WAV/MP3 transcription). The library and `docling-serve`
  REST wrapper share one pipeline.
- **Markdown is first-class** (`export_to_markdown()`), and the
  `DoclingDocument` JSON is a typed graph with `texts[]`, `tables[]`,
  `pictures[]`, `groups[]`, page/bbox provenance via `prov[].bbox`,
  and explicit element labels (`title`, `section_header`,
  `list_item`, `caption`, `footnote`, `formula`, `code`,
  `page_header`, `page_footer`).
- **Tables are real grids** with `table_cells[].{row, col, text,
  row_header}` — closest to a usable spreadsheet of any open-source
  option.
- Modern document features the LLM-driven services tend to skip:
  formula recognition, code-block detection, image classification,
  reading-order reconstruction, page header/footer separation.
- **Pluggable OCR backends** (Tesseract, EasyOCR, RapidOCR, OnnxTR)
  and pluggable layout / table models. You can swap quality vs.
  latency without forking the project.
- DOCX / PPTX / HTML go through the *same* pipeline and produce the
  *same* JSON shape as PDFs.

**What it lacks**

- `docling-serve` is younger than the library. The REST surface is
  intentionally thin (one `POST /v1/convert/source`); there is no
  async / job model, no per-page selection in the simplest call, no
  request id echo. For batch jobs you wrap the library yourself.
- No language model in the box. Quality on noisy scans depends on
  which OCR backend you pick and how you tune it. There is no "let
  the model figure it out" fallback.
- No structured-output / "fill this JSON schema" mode — the closest
  you get is the typed `DoclingDocument` graph.
- `do_ocr=true` on a long scanned PDF is CPU-bound and will hold the
  HTTP connection open for minutes. There is no progress stream.
- No usage / billing payload; you pay for the GPU you run it on.

**How it compares to us**

Docling and us occupy the same niche from different directions.
Docling is the *classical* implementation: layout models + an OCR
backend + a typed document graph, deterministic and reproducible.
We are the *LLM-driven* implementation: one VLM call per page,
markdown out, no layout model in the loop. Docling is sharper on
tables, formulas, code blocks, and reading order on complex
academic-paper-style PDFs; we're sharper on noisy or unusual
layouts where the LLM's flexibility wins, and we already speak
HTTP/JSON the way the hosted services do. **A future "best of both
worlds" version of this service could ship Docling as an alternate
backend** behind the same `POST /v1/ocr` shape — see §5.3.

---

## 4. Rating

Scores are 1–5 (5 = best), comparing what each API offers a typical
"upload doc, get structured text back" workflow. Google is rated as
**Document AI Enterprise Document OCR** (not Cloud Vision).

| Criterion                              | **Ours** | **Mistral** | **Google** | **Unstructured** | **Docling** |
|----------------------------------------|:--------:|:-----------:|:----------:|:----------------:|:-----------:|
| Ease of integration (auth, transport)  |   5      |     4       |     2      |        4         |      4      |
| Sync PDF support                       |   5      |     5       |     4      |        5         |      5      |
| Multi-input batching                   |   4      |     2       |     3      |        2         |      4      |
| Input format breadth (PDF + DOCX + …)  |   1      |     3       |     2      |        5         |      5      |
| Output structure (markdown/tables)     |   5      |     5       |     2      |        3         |      5      |
| Element / block typing                 |   4      |     4       |     5      |        5         |      5      |
| Geometry (bboxes / hierarchy)          |   1      |     4       |     5      |        4         |      4      |
| Confidence reporting                   |   1      |     4       |     5      |        1         |      2      |
| Document-level structured extraction   |   2      |     5       |     4      |        2         |      2      |
| RAG / chunking ergonomics              |   4      |     2       |     2      |        5         |      3      |
| Cost / usage transparency              |   3      |     3       |     1      |        1         |      5      |
| Operational features (id, async, jobs) |   3      |     4       |     5      |        3         |      2      |
| Self-host / data locality              |   5      |     1       |     1      |        4         |      5      |
| **Total (out of 65)**                  | **43**   |  **46**     |  **41**    |     **44**       |   **51**    |

Some context for the totals:

- **Docling** still comes out on top once you weigh self-host, format
  breadth, and structured output equally. Its weak spots are
  operational maturity (no jobs, no async, thin REST surface) and the
  lack of an LLM fallback for noisy scans — both fixable.
- **Mistral** keeps the highest score among the *managed* APIs because
  its single POST gives you markdown, tables, bboxes, headers,
  hyperlinks and a `document_annotation` schema in one round trip.
  The price is opaque billing and zero data locality.
- **Unstructured** wins on input format breadth and on RAG ergonomics.
  It loses points for not producing markdown directly and for the
  one-file-per-request legacy endpoint.
- **Document AI** is genuinely competitive for documents (not the 29
  it would score if we'd left Cloud Vision in this row). The geometry
  is best-in-class and sync PDFs work, but the multi-processor sprawl,
  the GCP project setup, and the 15-page sync ceiling are visible in
  the totals.
- **Ours** jumped from 35 → 43 in this pass after shipping
  `output.tables`, `output.elements`, the page-range string DSL, and
  the louder schema errors. We now sit one point behind Mistral in
  the managed-API peer group, ahead of Document AI, and just below
  Unstructured. The remaining gap to Docling is roughly two
  buckets: input format breadth (DOCX/PPTX/HTML — see §5.2 #8) and
  the visual / geometry items in §5.3, which are blocked on either a
  layout-aware model or the hybrid Docling backend (§5.3 #13). That
  hybrid-backend item is still the single most impactful next
  step — it would close most of the remaining gap in one move.

## 4.1 Timing and quality spot checks

Quality is recorded on a 0–100 scale from manual inspection of the
output for the sample document.

<table>
  <thead>
    <tr>
      <th rowspan="2">Service</th>
      <th colspan="2" style="text-align: right;">Receipt with tables</th>
      <th colspan="2" style="text-align: right;">two_col.pdf</th>
    </tr>
    <tr>
      <th style="text-align: right;">Quality</th>
      <th style="text-align: right;">Time</th>
      <th style="text-align: right;">Quality</th>
      <th style="text-align: right;">Time</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Ours</td>
      <td style="text-align: right;">100</td>
      <td style="text-align: right;">11s</td>
      <td style="text-align: right;">95</td>
      <td style="text-align: right;">22s</td>
    </tr>
    <tr>
      <td>Mistral</td>
      <td style="text-align: right;">100</td>
      <td style="text-align: right;">1.9s</td>
      <td style="text-align: right;">90</td>
      <td style="text-align: right;">2.3s</td>
    </tr>
    <tr>
      <td>Unstructured</td>
      <td style="text-align: right;">30</td>
      <td style="text-align: right;">0.3s</td>
      <td style="text-align: right;">30</td>
      <td style="text-align: right;">0.5s</td>
    </tr>
  </tbody>
</table>

---

## 5. Suggestions for changes to our API

Ordered roughly by **impact ÷ effort**, smallest changes first. The
§5.1 "cheap wins" list that used to live here has all shipped (`id`
echo, `language` hint, per-page `processing_ms`,
`usage_info.{pages_processed,doc_size_bytes}`, `OCR_THREADS`
documented, plus the `results[] → pages[]` and `usage → usage_info`
renames to match Mistral) — see git history if you want the diff.

### 5.1 Worth doing soon — protocol-level wins

These are pure-protocol changes that don't depend on the model's
visual capabilities; they pay off even on the current backend.

1. **`document_annotation` mode.** Borrow Mistral's pattern: accept
   a JSON schema + prompt and return one structured object for the
   whole document, not per page. Materially different from our
   current per-page `output.format=json` and the right shape for
   "extract these 8 fields from this contract".

### 5.2 Bigger bets — operational and API surface

> Authentication is intentionally **not** in this list. The service
> assumes a reverse proxy / API gateway in front of it that owns
> auth, and we expect every comparable solution to be deployed the
> same way.

6. **Async / job mode.** `POST /v1/ocr/jobs` → `{ id, status_url }`,
   plus `GET /v1/ocr/jobs/{id}`. Needed once anyone uploads a 200-page
   PDF — we currently hold the HTTP connection open for the duration
   of the OCR pass. Pair with a webhook callback URL.
7. **Streaming responses.** With per-page timings already on hand,
   stream pages as `text/event-stream` so the demo (and any client)
   can render results incrementally. Highest-perceived UX win for
   slow models.
8. **Broader input format support.** PDF / image is fine for now,
   but DOCX / PPTX / HTML round-tripping is what makes Unstructured
   and Docling sticky. The cheapest path is to detect-and-rasterise:
   convert non-PDF formats to PDF on the way in (LibreOffice
   headless / `pdfkit`) and run the existing pipeline. Heavier
   path: integrate Docling as a non-LLM backend (see §5.3 #14).

### 5.3 Bigger bets — visual / model-dependent

The current backend is a markdown-emitting VLM with no notion of
pixel coordinates or self-reported confidence. Everything in this
group either needs prompt-engineering work the model may not honour,
a different model, or a separate analysis pipeline. Treat them as
research items rather than ticket-ready tasks.

9. **`include_bbox` flag (per-page or per-element).** Even rough
   "this paragraph lives in this region of the page" coordinates
   would close our biggest gap vs. Mistral, Document AI and
   Docling. The model sees the image, but our current model
   (`gemma-3-27b`) is not reliable at emitting normalised pixel
   coordinates. A real solution either needs a layout-aware model
   or a parallel layout pass (e.g. `surya-layout`, `LayoutLMv3`)
   whose output we merge into the response.
10. **`include_confidence` (page-level).** Ask the model for a 0–1
    self-assessment per page. In theory cheap (one extra token);
    in practice today's VLMs return uncalibrated guesses. Worth
    revisiting once we move to a model with better introspection,
    or once we have ground truth to calibrate against.
11. **Per-page image asset extraction.** Mirror Mistral's
    `images[]`: when the document contains figures/photos, return
    the cropped sub-image with its bbox. Needs the same layout
    pipeline as #9 — without coordinates we have nothing to crop.
12. **Per-element confidence / quality scoring.** Document AI's
    `imageQualityScores` (blurry / glare / dark / faint /
    rotated…) is a separate model entirely. Ours would need
    either a small dedicated quality classifier or a fallback to
    a classical OCR backend that already exposes per-token
    confidence.
13. **Pluggable backends — Docling alongside the LLM.** The
    cleanest way to get bboxes, formulas, structured tables and
    code blocks **today** is not to teach our VLM new tricks, it
    is to add a `backend` field to the request (`"vlm"` /
    `"docling"`) and route to either implementation behind the
    same `POST /v1/ocr` shape. We get Docling's classical
    strengths without rewriting our wire format, and clients can
    A/B the two on their own data. This is the single most
    impactful item in §5 for catching up to the open-source
    leader.

### 5.4 Things we should *not* copy

- **GCS / object-store-only inputs (Google).** Our self-hosted model
  is the value prop; making the user stage files into a bucket would
  destroy it.
- **Async-only PDF handling (Google).** Sync PDFs are a feature, not
  a bug — keep them as the default and add async on top.
- **Hierarchical symbol-level geometry (Google).** Five levels of
  nesting is overkill for an LLM-driven OCR; paragraph-level bboxes
  buy 90% of the value at 10% of the payload.
- **One document per request (Mistral).** Our `images[]` batching
  is a real win, especially for parallel test pipelines.
- **Element-only (no markdown) output (Unstructured).** Markdown is
  the single most useful default for our users; element typing can
  ride alongside it (§5.1 #5), not replace it.
