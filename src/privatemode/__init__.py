"""privatemode — OCR documents with the Privatemode pipeline.

Today this runs fully locally: all PDF handling (rendering, form-field
flattening, page selection, image sizing) happens on your machine and
the LLM only ever sees one page image at a time. The same interface
will later also drive the hosted Privatemode OCR API.

Works with any OpenAI-compatible endpoint out of the box, and with
literally any model via a plain callable.

Quick start::

    from privatemode import ocr

    doc = ocr("invoice.pdf")          # uses LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
    print(doc.markdown)

Full control::

    from privatemode import OCR

    engine = OCR(base_url="https://api.openai.com/v1",
                 api_key="sk-…", model="gpt-4o")
    doc = engine.process("scan.pdf", pages="0-2,5", language="de")
    doc.save("out.md")

Any LLM at all::

    engine = OCR(llm=lambda prompt, image: my_model.generate(prompt, image))

Streaming::

    for page in engine.iter_pages("big.pdf"):
        print(page.index, page.content[:80])
"""
from privatemode.engine import LLMCallable, OCR, ocr
from privatemode.result import Document, Page

__all__ = ["OCR", "ocr", "Document", "Page", "LLMCallable"]
