"""1. PDF extraction (with a plain-text fallback for pages pymupdf4llm's
markdown/table parser mis-parses, and an OCR fallback for genuinely scanned
pages).
"""

import sys
from pathlib import Path

import fitz  # PyMuPDF -- already a dependency of pymupdf4llm; reused for OCR rasterization
import pymupdf4llm

# A page whose extracted text is shorter than this is treated as "no usable
# text" (typical of a scanned/image page) and triggers the OCR fallback.
MIN_PAGE_TEXT_CHARS = 20

# A page whose text falls between MIN_PAGE_TEXT_CHARS and this is short
# enough to be WORTH double-checking against plain fitz text extraction
# (see _recover_short_page below), but not so short it's presumed empty --
# most pages this size are legitimately short (a Disclaimer/Changes-to-
# Policy closing section, verified empirically: several real ~200-char
# closing pages recover essentially nothing extra from plain text, ratio
# ~1.0). Kept generous on purpose since the actual decision to use the
# plain-text result is driven by PLAIN_TEXT_RECOVERY_RATIO below, not by
# this threshold alone -- this just bounds which pages bother checking.
SHORT_PAGE_TEXT_CHARS = 500

# Diagnosed case: POSH Policy_2025 Ver2.0.pdf page 14's 7-row timeline table
# is drawn with vector graphics (72 draw ops, zero embedded images -- this
# is NOT a scanned/image page) whose text pymupdf4llm's markdown/table
# parser fails to associate with the page at all (190 chars recovered, just
# the caption) even though the text itself is completely intact in the PDF's
# text layer -- plain fitz Page.get_text() recovers it in full (1351 chars,
# a 7.1x ratio), instantly and exactly, no OCR/Tesseract involved. Checked
# against every other short page in the corpus before picking this ratio:
# legitimately-short pages (closing Disclaimer sections etc.) recover a
# ~1.0x ratio from plain text -- essentially nothing extra -- so 2.0x with
# an absolute floor cleanly separates "real content pymupdf4llm dropped"
# from "this page is just naturally short" with no observed false positives.
PLAIN_TEXT_RECOVERY_RATIO = 2.0
PLAIN_TEXT_RECOVERY_MIN_CHARS = 100

# OCR is rasterized at 300 DPI rather than PyMuPDF's ~96 DPI default --
# Tesseract's recognition accuracy drops sharply below ~250-300 DPI on
# scanned documents, which is precisely the case this fallback exists for.
OCR_DPI = 300


def _recover_short_page(doc: "fitz.Document", page_index: int, current_text: str) -> str | None:
    """For a page whose pymupdf4llm text is short but not empty: check
    whether plain fitz text extraction (Page.get_text(), no markdown/table
    structuring) recovers meaningfully more of the page's actual text layer.
    Returns the plain-text result if it clearly recovers more content, else
    None (the caller keeps pymupdf4llm's original text unchanged).

    This is deliberately NOT an OCR path -- OCR is for pages with no real
    text layer at all (see _ocr_page/needs_ocr below). Running OCR on a page
    that already has a perfectly good, exact text layer would be slower and
    strictly worse (real risk of misread characters) than just reading that
    text layer directly, which is what this does.
    """
    plain_text = doc[page_index].get_text().strip()
    current_len = len(current_text.strip())
    if (
        len(plain_text) >= PLAIN_TEXT_RECOVERY_MIN_CHARS
        and current_len > 0
        and len(plain_text) >= current_len * PLAIN_TEXT_RECOVERY_RATIO
    ):
        return plain_text
    return None


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
    # Short but not empty -- worth a cheap plain-text double-check (see
    # _recover_short_page) before ever reaching for OCR. Pages already in
    # needs_ocr are excluded: those get the real OCR path below regardless.
    needs_recovery_check = [
        i
        for i, text in enumerate(page_texts)
        if MIN_PAGE_TEXT_CHARS <= len(text.strip()) < SHORT_PAGE_TEXT_CHARS
    ]

    if needs_ocr or needs_recovery_check:
        doc = fitz.open(str(pdf_path))

        for i in needs_recovery_check:
            recovered = _recover_short_page(doc, i, page_texts[i])
            if recovered is not None:
                page_texts[i] = recovered

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
