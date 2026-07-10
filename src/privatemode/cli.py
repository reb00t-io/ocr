"""Command-line interface for privatemode.

Usage (from the repo root)::

    python src/privatemode/cli.py document.pdf                 # markdown to stdout
    python src/privatemode/cli.py document.pdf -o out.md       # to a file
    cd src && python -m privatemode document.pdf --pages 0-2   # module form

Progress goes to stderr, the result to stdout (or ``-o``), so piping
just works: ``python src/privatemode/cli.py doc.pdf > doc.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Running as a plain script (python src/privatemode/cli.py …):
    # make the sibling modules (pdf, schema, backends, privatemode) importable.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from privatemode.engine import OCR
from schema import VALID_FORMATS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocr",
        description=(
            "OCR a PDF or image locally: all document handling happens on "
            "this machine, only page images are sent to the LLM."
        ),
    )
    parser.add_argument(
        "input",
        help="Path or http(s) URL of a PDF or image. Use '-' to read from stdin.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file (default: stdout).",
    )
    parser.add_argument(
        "-f", "--format", choices=VALID_FORMATS, default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--pages",
        help="PDF page selection, 0-based: '0-2,5' or '3'. Default: all pages.",
    )
    parser.add_argument(
        "--language",
        help="Document language hint, BCP-47 (e.g. 'de').",
    )
    parser.add_argument(
        "--prompt",
        help="Extra instruction for the model (e.g. 'summarize each page').",
    )
    parser.add_argument(
        "--describe-images", action="store_true",
        help="Append an 'Image Descriptions' section per page.",
    )
    parser.add_argument(
        "--paginate", action="store_true",
        help="Insert '<!-- page N -->' markers between pages in the merged output.",
    )
    parser.add_argument(
        "--base-url", default=None,
        help="OpenAI-compatible endpoint (default: $LLM_BASE_URL).",
    )
    parser.add_argument(
        "--model", default=None,
        help="Model name (default: $LLM_MODEL).",
    )
    parser.add_argument(
        "--dpi", type=int, default=300,
        help="PDF render resolution (default: 300).",
    )
    parser.add_argument(
        "--threads", type=int, default=4,
        help="Pages OCRed concurrently (default: 4).",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress per-page progress on stderr.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # The API key comes from the environment only — a --api-key flag
    # would leak secrets into shell history and process listings.
    engine = OCR(
        base_url=args.base_url,
        api_key=os.environ.get("LLM_API_KEY") or None,
        model=args.model,
        dpi=args.dpi,
        threads=args.threads,
    )

    source: object = args.input
    if args.input == "-":
        source = sys.stdin.buffer.read()

    total = {"done": 0}

    def _progress(page) -> None:
        total["done"] += 1
        if args.quiet:
            return
        status = "ok"
        if page.error:
            status = f"ERROR: {page.error}"
        elif page.warning:
            status = f"warning: {page.warning}"
        print(
            f"page {page.index} done ({page.processing_ms} ms) — {status}",
            file=sys.stderr,
        )

    try:
        doc = engine.process(
            source,
            format=args.format,
            pages=args.pages,
            language=args.language,
            prompt=args.prompt,
            describe_images=args.describe_images,
            on_page=_progress,
        )
    except (ValueError, TypeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        rendered = json.dumps(doc.to_dict(), indent=2, ensure_ascii=False)
    else:
        rendered = doc.merged(paginate=args.paginate)

    if args.output:
        Path(args.output).write_text(rendered + "\n")
        if not args.quiet:
            print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(rendered)

    if not doc.ok:
        failed = ", ".join(str(p.index) for p in doc.errors)
        print(f"error: page(s) {failed} failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
