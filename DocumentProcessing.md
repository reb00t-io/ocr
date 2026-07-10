# Document processing

## Use cases

There are 2 main use cases
1. **OCR (doc -> text)**: user wants text for another use
2. **Analysis (doc -> info)**: user wants a subset of the information or a certain transformation

Concrete customer use cases
Features (layout, tables, extract images, formulas, bounding boxes, extract arrows/boxes/charts)

### UC1 OCR

Caller wants faithful text out for something else to consume, e.g.,:

- **The consumer has no vision.** Text-only LLMs in a chain,
  embedding models, search indexes — none take a page image. RAG
  ingestion and search indexing are the same problem: extract once,
  query later.
- **Reuse.** The document is fixed; the queries are not. Re-running
  over the document on every prompt is wasteful when the text can
  be cached.
- **Performance.** OCR + text-LLM is often faster, cheaper, and
  *higher quality* than a VLM-direct call on the same task.
  Specialised OCR models beat general VLMs at reading dense text;
  text-LLMs beat VLMs at reasoning over text. Two specialists in
  series usually wins.

Sample use cases:

- Ingesting a contract repository into RAG for a compliance bot.
- Building a searchable index over technical manuals or wikis.
- Bulk-extracting invoices / receipts for a downstream accounting
  workflow.
- Pre-processing scanned forms so an agent can read and act on
  them.
- Pulling meeting-recap PDFs into an embedding store.

**Expected frequency: very common.** This is the bread-and-butter
of LLM document pipelines — anything RAG-shaped or search-shaped
starts here.

### UC2 Analysis of the document

Caller wants an answer, an extraction, or a transformation derived
from the document — not the document itself. The mechanism is ours
to pick; the caller cares about quality, latency, and cost, not how
we got there. This may be combined with structured output and
additional inputs and requires a larger LLM or VLM.

From user perspective, this is a generalization of 1, with the
transformation being _'Transcribe the text'_.

We split further on whether the visual / layout content carries
information the text alone would lose.

#### UC2a Text analysis (Text input sufficient) - with or without layout?

The answer lives in the document's text content; layout and visual
elements don't carry the answer.

Sample use cases:

- "Summarise this contract."
- "Translate this menu to German."
- "Pull the invoice number, date, and total."
- "What are the action items in this meeting transcript?"
- "Is this NDA compatible with our standard template?"
- "List every party named in this contract."

**Expected frequency: common.** Typical interactive doc-Q&A — one
document, one question, one answer. High per-user frequency, lower
volume per call than UC1.

#### UC2b Visual analysis (Layout or visual input relevant)

Caller's question is (also) about something the *pixels* carry — chart
shape, slide layout, logo identity, figure comparison. No text-only
shortcut applies; the visual information *is* the answer.

Sample use cases:

- "Is the chart on page 3 misleading?"
- "Describe this slide's layout and design quality."
- "Which company's logo is shown on this brochure?"
- "Compare these two figures — what's different?"
- "Does this deck follow our brand guidelines?"
- "What's depicted in the photograph on the cover?"

**Expected frequency: less common.** A real but niche slice — most
analysis is content-oriented, not visual. Probably the smallest
slice of traffic in the long run, but the only one with no
alternative.

## Solutions

Here we list potential solutions. Each solution may cover an entire use case or
only a subset in certain situations.

### 1a. Text conversion: doc → text \[→ LLM\]

Parse the document directly: XML for DOCX / PPTX / HTML / EML, native
text layer for digital PDFs. Optionally pipe the result into a
text-only LLM.

- Doesn't always work — scanned PDFs and images have nothing to
  parse. Can't handle embedded images.
- Sometimes loses structure (PDF text-layer extraction often arrives without
  reading order; XML preserves more).
- Cheapest and fastest where it applies.
- Covers UC1 and UC2a if the source doc is plain text (i.e., not scanned PDF etc.)

### 1b. OCR: doc → image → text \[→ LLM\]

Render to image, run a OCR model page by page to transcribe, optionally
pipe the result into a text-only LLM.

(What is Mistral doing? What features?)

- Always works.
- Wasteful and lossy when the input was already structured —
  rendering DOCX → image → re-OCRing throws away the text already in
  the XML and pays a font-substitution tax.
- Quality is the OCR's transcription quality; strong on noisy scans
  and unusual layouts.
- Covers UC1 and UC2a

### 2. Analysis: doc → image → VLM

Render to image, send pages plus the caller's prompt to the VLM,
return one answer.

- Cost and image-budget bound — long documents hit the model's
  effective multi-image limit (but applies to text as well).
- Quality bounded by the VLM's reasoning. Loses the precision of a
  dedicated text path for purely content-level questions.
- Covers all cases; for UC1 asking the VLM to transcribe

### 3. Analysis: doc → image + text → VLM

Extract text via 1a / 1b *and* render to image (as 2); send both to the
VLM alongside the caller's prompt.

- Best quality — the model has both representations and can
  cross-check.
- Highest cost — text tokens *plus* image tokens *plus* the
  extraction pass.
- Covers all use cases

(Extraction of text + images)

## Mapping

Ours on the left, existing alternatives on the right.

|                           |  1a | 1b | 2 | 3 | DIY | Unstr | Mistral | Docling |
|---------------------------|:---:|:--:|:-:|:-:|:---:|:-----:|:-------:|:-------:|
| UC1 — doc → text          | (✓) |  ✓ | ✓ | ✓ |  ✓  |   ✓   |    ✓    |    ✓    |
| UC2a — text-only analysis | (✓) |  ✓ | ✓ | ✓ |  ✓  |   ✓   |    ✓    |    ✓    |
| UC2b — visual analysis    |     |    | ✓ | ✓ |     |       |         |         |

External shortcuts:

- **DIY** — caller extracts text in their own process with a library
  (`pdfplumber`, `pypdf`, `python-docx`, BeautifulSoup, …). No
  service, no infrastructure, just a function call. Text-bearing
  inputs only — no fallback for scans or images, and structure
  fidelity is whatever the library gives you. UC2 via a downstream
  LLM as usual. Where it works, this is by far the cheapest path,
  and it's what many users will reach for first.
- **Unstr** — `unstructured-api`. XML / document parsing **with OCR
  fallback**, returns typed elements (`Title`, `Table`, `Header`, …).
  UC2 only via a downstream LLM the caller wires up themselves.
- **Mistral** — Mistral OCR (hosted). Markdown out, plus
  `document_annotation_format` for schema-driven extraction baked
  in. Free-form analysis still needs a downstream LLM.
- **Docling** — self-hosted layout model + classical OCR backend.
  Multi-format input, structured `DoclingDocument` JSON. UC2 via a
  downstream LLM.

**The UC2b row is the differentiator.** None of these
alternatives — DIY, Unstructured, Mistral OCR, Docling — can analyse
visual artefacts. They extract text, at most image *crops*, but
they cannot answer "is this chart misleading?" or "describe this
slide's layout". That is the gap our solutions 2 and 3 fill, and
the reason this service exists alongside the others.

## Potential steps

Remarks:
- UC1 for text input can be covered by users themselves:
  - using text extraction without the need to use a GPU
  - trivial if the input is xml or html
  - still beneficial to offer the full solution but those could be postponed
- If we drop the fallback to text extraction for UC1, then remaining solutions
  1b and 2 use image extraction, which could be a common ground
- Solution 1b accuracy likely better than 2 for UC1 and UC2a; but still worse than
- Solution 2 might be too expensive for UC1

Potential MVP Scope:
- Start with 1b or 2? 2 could be not good enough quality-wise.
- Add option for trivial text extraction.
- Reusing Unstructured or similar?
- Architecture?

Later:
- Solution 2 potential X->img service so each model could process any doc
