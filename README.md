# OCR Service

A self-hosted OCR REST API built on **Privatemode OCR**. Submit a PDF or image,
get back structured markdown, plain text, or extracted JSON.

## Requirements

- Python 3.13
- `poppler-utils` system package (for local PDF support)
- Privatemode OCR credentials / model access (see configuration)

## Quick Start

```bash
# 1. Load environment (creates venv, installs deps, sets PORT)
direnv allow

# 2. Run locally
python src/main.py
# → http://localhost:$PORT

# 3. Or run with Docker
./scripts/build.sh
docker compose up
```

## API

### `POST /v1/ocr`

Synchronous. Suitable for single images or short PDFs (≤ 10 pages).

**Request**
```json
{
  "model": "privatemode-ocr",
  "document": {
    "type": "url",
    "value": "https://example.com/invoice.pdf"
  },
  "pages": [0, 1],
  "output": {
    "format": "markdown"
  }
}
```

`document.type` accepts `"url"` or `"base64"`.
`pages` is optional — omit to process all pages.
`output.format` is `"markdown"` (default), `"text"`, or `"json"`.

**Response**
```json
{
  "id": "ocr_abc123",
  "model": "privatemode-ocr",
  "pages": [
    {
      "index": 0,
      "markdown": "# Invoice\n\n| Item | Price |\n|------|-------|\n...",
      "images": [],
      "dimensions": { "width": 1240, "height": 1754, "dpi": 300 }
    }
  ],
  "usage": { "pages": 1, "processing_ms": 1200 }
}
```

### `GET /health`

```json
{ "status": "ok", "version": "0.1.0" }
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PORT` | set in `.envrc` | Server port |
| `OCR_FILE_TTL_SECONDS` | `3600` | How long uploaded files are kept |
| `OCR_MAX_UPLOAD_MB` | `50` | Request size limit |

## Project Structure

```
src/
  main.py             # Flask app entry point
  routes/
    ocr.py            # /v1/ocr
  backends/
    base.py           # Abstract OCRBackend
    privatemode.py    # Privatemode OCR backend
  pdf.py              # PDF → image conversion (pdf2image)
  schema.py           # Request / response dataclasses
scripts/
  build.sh            # Docker build
  deploy.sh           # Build, upload, and deploy to remote host
  get_logs.sh         # Fetch container logs from remote
test/
  e2e.sh              # End-to-end smoke tests
.github/workflows/
  ci.yml              # CI pipeline: build → e2e → deploy
Dockerfile
docker-compose.yml
plan.md               # Implementation plan and architecture notes
```

## Docker

The container image installs `poppler-utils`, so PDF preview and OCR work without any extra host packages.
Runtime settings such as `MISTRAL_API_KEY` are passed through from the shell that runs `docker compose up`.

```bash
./scripts/build.sh
docker compose up
```
