"""localocr — OCR documents locally, send only page images to any LLM.

All PDF handling (rendering, form-field flattening, page selection,
image sizing) runs on your machine; the LLM only ever sees one page
image at a time. Works with any OpenAI-compatible endpoint out of the
box, and with literally any model via a plain callable.

Quick start::

    from localocr import ocr

    doc = ocr("invoice.pdf")          # uses LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
    print(doc.markdown)

Full control::

    from localocr import LocalOCR

    engine = LocalOCR(base_url="https://api.openai.com/v1",
                      api_key="sk-…", model="gpt-4o")
    doc = engine.process("scan.pdf", pages="0-2,5", language="de")
    doc.save("out.md")

Any LLM at all::

    engine = LocalOCR(llm=lambda prompt, image: my_model.generate(prompt, image))

Streaming::

    for page in engine.iter_pages("big.pdf"):
        print(page.index, page.content[:80])
"""
from localocr.engine import LLMCallable, LocalOCR, ocr
from localocr.result import Document, Page

__all__ = ["LocalOCR", "ocr", "Document", "Page", "LLMCallable"]
