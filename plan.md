# OCR Service — Implementation Plan

## What We're Building

A self-hosted OCR REST API wrapping a **Privatemode OCR** model. Clients submit
images or PDFs and get back structured markdown, plain text, or extracted JSON.
The API design is informed by the Mistral OCR API surface (used as a reference,
not as a backend).

---

## Architecture

```
client
  │
  ▼
POST /v1/ocr          ← synchronous endpoint
  │
  ├── images[]        ← one or more images (base64 or URL)
  └── document        ← single PDF or image with optional page selection
  │
  ▼
pdf.py (if PDF)       ← convert pages → PIL images
  │
  ▼
Privatemode OCR backend  (OpenAI-compatible API at localhost:8080/v1)
```

---

## API Contract

### `POST /v1/ocr`

Exactly one of `images` or `document` must be provided.

**Image array request:**
```json
{
  "images": [
    { "type": "url" | "base64", "value": "..." }
  ],
  "output": { "format": "markdown" | "text" | "json" },
  "threads": 4
}
```

**PDF / single-document request:**
```json
{
  "document": { "type": "url" | "base64", "value": "..." },
  "pages": [0, 1],
  "output": { "format": "markdown" | "text" | "json" },
  "threads": 4
}
```

**Response:**
```json
{
  "model": "gemma-3-27b",
  "results": [
    { "index": 0, "content": "# Invoice\n..." }
  ],
  "usage": { "images": 2, "processing_ms": 820 }
}
```

`content` is a string for `markdown`/`text`, a JSON object for `json` format.

---

## File Structure

```
src/
  main.py             # Flask app: blueprint registration, logging, size limit
  routes/
    ocr.py            # POST /v1/ocr
  backends/
    image.py          # encode_jpeg_image / encode_jpeg_bytes
    privatemode.py    # PrivatemodeBackend (ThreadPoolExecutor)
  pdf.py              # pdf_to_images() — pdf2image wrapper
  schema.py           # OCRRequest, ImageInput, DocumentInput, OutputOptions
  logging_config.py   # JSON structured logging setup
config/
  nginx/              # nginx site config
test/
  conftest.py         # adds src/ to sys.path
  unit/
    test_image.py
    test_schema.py
    test_backend.py
    test_pdf.py
  integration/
    test_ocr_image.py # real LLM call, skipped if server unreachable
  e2e.sh              # smoke test against running server
```

---

## Dependencies

```toml
"flask==3.1.2"
"uvicorn==0.40.0"
"asgiref==3.11.1"
"openai>=1.0.0"
"pillow>=11.0.0"
"pdf2image>=1.17.0"    # requires poppler-utils system package
```

Poppler installed via `apt-get install poppler-utils` in Dockerfile,
`brew install poppler` on macOS.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | set in `.envrc` | Server port |
| `LLM_BASE_URL` | `http://localhost:8080/v1` | OpenAI-compatible inference endpoint |
| `LLM_API_KEY` | `dummy` | API key (use `dummy` for local models) |
| `LLM_MODEL` | `gemma-3-27b` | Model name |
| `OCR_MAX_UPLOAD_MB` | `50` | Request body size limit |

---

## Implementation Phases

### Phase 1 — API skeleton ✅
- [x] Define `schema.py` (request/response dataclasses)
- [x] Wire up route in `routes/ocr.py`
- [x] `/health` endpoint

### Phase 2 — Privatemode OCR backend ✅
- [x] `backends/image.py` (`encode_jpeg_image`, `encode_jpeg_bytes`)
- [x] `backends/privatemode.py` (ThreadPoolExecutor, markdown/text/json modes)
- [x] Integration test with real image (`test/integration/test_ocr_image.py`)

### Phase 3 — PDF support ✅
- [x] `pdf.py` — `pdf_to_images(bytes, pages, dpi)` using pdf2image at 300 DPI
- [x] `document` + `pages` fields in `OCRRequest`
- [x] Route handles PDF: detect → convert pages → OCR
- [x] poppler added to Dockerfile

### Phase 4 — Hardening ✅
- [x] Request size limit (`OCR_MAX_UPLOAD_MB` → `MAX_CONTENT_LENGTH`)
- [x] Structured JSON logging (`logging_config.py`)
- [x] `AGENTS.md` updated with real commands

---

## Open Questions

- **Auth**: `X-API-Key` header middleware if exposing externally
- **Rate limiting**: out of scope for now
- **PDF DPI**: 300 DPI is the default; expose as a request parameter if needed
