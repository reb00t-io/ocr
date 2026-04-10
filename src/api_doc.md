# OCR Service — API

A self-hosted OCR REST API. Submit images or PDFs and receive structured
markdown, plain text, or JSON extracted from the document.

The API is intentionally small. There is one OCR endpoint plus a health
check; everything else (the viewer at `/demo`, this doc page) is
auxiliary.

---

## `POST /v1/ocr`

Run OCR on one or more images, or on a PDF document.

**Request body** — JSON. Exactly one of `images` or `document` must be
provided.

### Image array request

```json
{
  "id": "req-2026-04-10-001",
  "images": [
    { "type": "url",    "value": "https://example.com/page1.png" },
    { "type": "base64", "value": "iVBORw0KGgo..." }
  ],
  "output":   { "format": "markdown" },
  "language": "en"
}
```

### PDF / single-document request

```json
{
  "id": "req-2026-04-10-002",
  "document": { "type": "base64", "value": "JVBERi0xLjQK..." },
  "pages":    [0, 1, 2],
  "output":   { "format": "markdown", "tables": true },
  "language": "de"
}
```

### Fields

| Field            | Type                                 | Default      | Notes                                                                       |
|------------------|--------------------------------------|--------------|-----------------------------------------------------------------------------|
| `images`         | array of `{type, value}`             | —            | Required if `document` is absent. Each entry is processed in order.         |
| `document`       | `{type, value}`                      | —            | Required if `images` is absent. May be a PDF or a single image.             |
| `pages`          | array of int **or** range string     | all pages    | **0-based** PDF page indices. Either a list (`[0, 1, 2]`) or a comma-separated range string (`"0-2,4,7-9"`). Ignored for non-PDF documents. The bundled viewer at `/demo` displays page numbers 1-based for humans, but the API itself is 0-based to match Mistral. |
| `output.format`  | `"markdown"` \| `"text"` \| `"json"` | `"markdown"` | Output style.                                                               |
| `output.tables`  | boolean                              | `false`      | If `true`, parse markdown tables out of each page and surface them as structured data under `pages[].tables[]`. The original markdown is still returned. |
| `output.elements`| boolean                              | `false`      | If `true`, emit a typed `pages[].elements[]` list (`title`, `section_header`, `paragraph`, `list_item`, `code`, `table`, `blockquote`, `horizontal_rule`) parsed from the markdown. |
| `output.describe_images` | boolean                      | `false`      | If `true`, the OCR prompt instructs the model to append a final `## Image Descriptions` section listing every figure / photo / chart / diagram in the page with a one-sentence description. Has no effect for `format=json` (the strict JSON schema doesn't allow extra prose). |
| `id`             | string                               | —            | Optional client-supplied request id; echoed back in the response.           |
| `language`       | string (BCP-47)                      | —            | Optional language hint (e.g. `"en"`, `"de"`, `"fr"`). Forwarded to the OCR prompt. |
| `prompt`         | string                               | —            | Optional free-form instruction merged into the OCR prompt as the **primary directive** (e.g. `"summarize each page"`, `"translate to English"`, `"only list the invoice totals"`). Overrides the default "preserve all structure" behaviour where they conflict. Ignored when `output.format=json` (the strict JSON schema doesn't leave room for free-form changes). |

> Parallelism is configured server-side via the `OCR_THREADS` constant in
> `src/routes/ocr.py` (default `4`) and is **not exposed through the API**.
> Tune it to match the concurrency budget of your inference backend.

For both `images[]` entries and `document`, `type` must be either:

- `"url"` — `value` is an HTTP(S) URL the server will fetch.
- `"base64"` — `value` is the raw image or PDF bytes, base64-encoded.

### Response

```json
{
  "id":    "req-2026-04-10-002",
  "model": "gemma-3-27b",
  "pages": [
    {
      "index": 0,
      "content": "# Invoice\n\n| Item | Qty | Price |\n|------|-----|-------|\n| Widget | 3 | 12.00 |\n",
      "processing_ms": 612,
      "tables": [
        {
          "header": ["Item", "Qty", "Price"],
          "rows":   [["Widget", "3", "12.00"]]
        }
      ]
    },
    { "index": 1, "content": "# Invoice page 2\n...", "processing_ms": 754, "tables": [] }
  ],
  "usage_info": {
    "pages_processed": 2,
    "doc_size_bytes":  184232,
    "processing_ms":   1840
  }
}
```

- `pages[].content` is a string for `markdown` and `text`, and a JSON
  object for `json` (with `title`, `content`, `sections[]`).
- `pages[].processing_ms` is the wall-clock time the backend spent on
  that single page; useful for finding the slowest page in a batch.
- `pages[].tables` is present only when the request set
  `output.tables: true`. It is an array of `{header, rows}` objects
  parsed out of the markdown content; the original markdown is still
  in `content`. Pages without tables get an empty array.
- `pages[].elements` is present only when the request set
  `output.elements: true`. Each element is `{type, text}` (plus
  `level` on headings and `language` on code blocks). Element types:
  `title`, `section_header`, `paragraph`, `list_item`, `code`,
  `table`, `blockquote`, `horizontal_rule`. The order matches the
  reading order of the markdown.
- `pages[].error` is set on individual pages that failed; the rest of
  the response still succeeds.
- `usage_info.pages_processed` is the number of images / pages actually
  sent to the model (PDF pages count individually).
- `usage_info.doc_size_bytes` is the total input size after URL fetch /
  base64 decode.
- `usage_info.processing_ms` is the wall-clock time across the entire
  parallel OCR pass.
- `id` is included only when the request supplied one.

### Status codes

| Code | Meaning                                                       |
|------|---------------------------------------------------------------|
| 200  | Success.                                                      |
| 400  | Body was not valid JSON.                                      |
| 422  | Schema error, bad page indices, or unparseable document.      |
| 500  | Unexpected server / backend error.                            |

### Examples

#### cURL — single image, base64

```bash
b64=$(base64 -i page.png)
curl -sS http://localhost:8088/v1/ocr \
  -H 'content-type: application/json' \
  -d "{\"images\":[{\"type\":\"base64\",\"value\":\"$b64\"}]}"
```

#### cURL — PDF, pages 0 and 2 only, plain text

```bash
b64=$(base64 -i invoice.pdf)
curl -sS http://localhost:8088/v1/ocr \
  -H 'content-type: application/json' \
  -d "{
        \"document\": {\"type\": \"base64\", \"value\": \"$b64\"},
        \"pages\":    [0, 2],
        \"output\":   {\"format\": \"text\"}
      }"
```

#### Python

```python
import base64, requests

with open("invoice.pdf", "rb") as f:
    payload = {
        "id":       "invoice-2026-04-10",
        "document": {"type": "base64", "value": base64.b64encode(f.read()).decode()},
        "output":   {"format": "markdown"},
        "language": "en",
    }

r = requests.post("http://localhost:8088/v1/ocr", json=payload, timeout=120)
r.raise_for_status()
body = r.json()
print(f"id={body['id']} pages={body['usage_info']['pages_processed']} "
      f"bytes={body['usage_info']['doc_size_bytes']} "
      f"total={body['usage_info']['processing_ms']}ms")
for page in body["pages"]:
    print(f"--- page {page['index']} ({page['processing_ms']}ms) ---")
    print(page["content"])
```

---

## `GET /health`

Lightweight liveness probe.

```json
{ "status": "ok", "version": "0.1.0" }
```

Returns `200` whenever the process is up. Does **not** check that the
LLM backend is reachable.

---

## Auxiliary endpoints

These exist for the bundled web UI and live documentation. They are not
part of the public API contract:

| Method & path        | Purpose                                                            |
|----------------------|--------------------------------------------------------------------|
| `GET /demo`          | Side-by-side PDF viewer (image left, extracted markdown right).    |
| `POST /demo/process` | Multipart upload backing the viewer. Returns per-page timings.    |
| `GET /doc`           | This documentation as raw markdown (`text/markdown`).              |
| `GET /docs`          | This documentation rendered as a styled HTML page.                 |

---

## Configuration

The server is configured via environment variables:

| Variable             | Default                       | Description                              |
|----------------------|-------------------------------|------------------------------------------|
| `PORT`               | (required)                    | TCP port to bind.                        |
| `LLM_BASE_URL`       | `http://localhost:8080/v1`    | OpenAI-compatible inference endpoint.    |
| `LLM_API_KEY`        | `dummy`                       | API key (use `dummy` for local models).  |
| `LLM_MODEL`          | `gemma-3-27b`                 | Model name passed to the backend.        |
| `OCR_MAX_UPLOAD_MB`  | `50`                          | Maximum request body size, in megabytes. |
