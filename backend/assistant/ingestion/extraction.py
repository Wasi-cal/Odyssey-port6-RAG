"""1. PDF extraction (with OCR fallback for scanned pages)."""

import sys
from pathlib import Path

import fitz  # PyMuPDF -- already a dependency of pymupdf4llm; reused for OCR rasterization
import pymupdf4llm

# A page whose extracted text is shorter than this is treated as "no usable
# text" (typical of a scanned/image page) and triggers the OCR fallback.
MIN_PAGE_TEXT_CHARS = 20

# OCR is rasterized at 300 DPI rather than PyMuPDF's ~96 DPI default --
# Tesseract's recognition accuracy drops sharply below ~250-300 DPI on
# scanned documents, which is precisely the case this fallback exists for.
OCR_DPI = 300


def _ocr_page(doc: "fitz.Document", page_index: int) -> str:
    """Rasterize one page and run it through Tesseract OCR.

    Uses PyMuPDF's own pixmap rendering rather than pdf2image, since PyMuPDF
    is already a dependency (via pymupdf4llm) -- this avoids adding a second,
    redundant rasterization path and the poppler system dependency that
    pdf2image would otherwise require.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        print(
            f"[ingest] OCR needed for page {page_index + 1} but pytesseract/Pillow "
            f"are not installed -- this page will have little or no extractable text. "
            f"Install with: uv pip install pytesseract pillow, and install the "
            f"tesseract binary (see README).",
            file=sys.stderr,
        )
        return ""

    page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72))
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(image)


def extract_pages(pdf_path: Path) -> tuple[list[str], list[int]]:
    """Extract Markdown text for every page, OCR'ing pages that come back
    (near-)empty. Returns (page_texts, ocr_page_numbers) -- ocr_page_numbers
    is reported by the caller so scanned documents are never silently
    ingested with missing content.

    NOTE: this assumes pymupdf4llm.to_markdown(..., page_chunks=True) returns
    one dict per page with a "text" key holding that page's markdown -- this
    is the documented shape as of pymupdf4llm's current API; if a future
    version changes that key name, this is the line to update.
    """
    page_dicts = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
    page_texts = [p.get("text", "") for p in page_dicts]

    ocr_pages = []
    needs_ocr = [i for i, text in enumerate(page_texts) if len(text.strip()) < MIN_PAGE_TEXT_CHARS]

    if needs_ocr:
        doc = fitz.open(str(pdf_path))
        for i in needs_ocr:
            ocr_text = _ocr_page(doc, i)
            if ocr_text.strip():
                page_texts[i] = ocr_text
                ocr_pages.append(i + 1)
            # If OCR also comes back empty (or tesseract isn't installed), we
            # deliberately keep the page instead of dropping it -- removing
            # it would shift every later page's number and silently break
            # citations for the rest of the document.
        doc.close()

    return page_texts, ocr_pages
