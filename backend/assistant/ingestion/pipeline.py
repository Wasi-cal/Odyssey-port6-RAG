"""6. Per-document pipeline orchestration -- ties extraction, boilerplate
stripping, structure detection, and chunking together, then persists to
Chroma.
"""

import sys
from pathlib import Path

from langchain_core.documents import Document

from ..embeddings import count_tokens
from ..openai_key import require_openai_api_key
from ..paths import DATA_DIR
from .boilerplate import strip_boilerplate
from .chunking.masking import mask_spans
from .chunking.prose import split_prose
from .chunking.tables import build_table_chunks
from .extraction import extract_pages
from .store import get_vector_store
from .structure import build_full_text, determine_section_level, detect_headings, detect_table_spans


def load_and_split(pdf_paths: list[Path]) -> list[Document]:
    """Load each PDF, chunk it, and return chunks carrying metadata
    {"source": <filename>, "page": <page_number>, "section": <heading>,
    "subsection": <nested heading, or "">}.

    This is what lets retrieval produce citations like "Employee Handbook →
    Parental Leave → Bonding Leave, p.12" later, since Chroma stores and
    returns this metadata (and the header baked into page_content) untouched.
    """
    all_chunks = []
    for pdf_path in pdf_paths:
        page_texts, ocr_pages = extract_pages(pdf_path)
        if ocr_pages:
            print(f"[ingest] {pdf_path.name}: OCR fallback used for page(s) {ocr_pages}")

        page_texts = strip_boilerplate(page_texts)
        full_text, page_offsets = build_full_text(page_texts)

        if not full_text.strip():
            # Never silently drop a document: log loudly and move on, rather
            # than pretending ingestion succeeded.
            print(
                f"[ingest] WARNING: {pdf_path.name} yielded no extractable text "
                f"even after OCR -- it was NOT added to the vector store.",
                file=sys.stderr,
            )
            continue

        headings = detect_headings(full_text)
        heading_positions = [h[0] for h in headings]
        section_level = determine_section_level(headings)
        table_spans = detect_table_spans(full_text)

        all_chunks.extend(
            build_table_chunks(
                pdf_path.name, full_text, table_spans, page_offsets, headings, heading_positions, section_level
            )
        )

        masked_text = mask_spans(full_text, table_spans)
        all_chunks.extend(
            split_prose(pdf_path.name, masked_text, page_offsets, headings, heading_positions, section_level)
        )

    return all_chunks


def ingest_files(pdf_paths: list[Path]) -> tuple[int, int]:
    """Embed and persist the given PDFs into Chroma. Returns
    (chunk_count, embed_tokens) -- embed_tokens is an estimate (see
    embeddings.count_tokens) of how many tokens were sent to the embedding
    model, for the admin monitoring dashboard's cost figures.

    Idempotent per filename: clears any existing chunks for each of these
    exact filenames before adding the fresh ones, so calling this twice for
    the same file (e.g. a retry, or recovering a filename whose Postgres row
    or disk copy got out of sync with Chroma some other way) can never leave
    duplicate/stale vectors sitting alongside the new ones -- the admin
    approve endpoint also rejects a duplicate filename outright, but this is
    the pipeline's own defense regardless of what called it (CLI, API, or a
    Temporal activity retry).
    """
    require_openai_api_key()
    if not pdf_paths:
        return 0, 0

    chunks = load_and_split(pdf_paths)
    if not chunks:
        return 0, 0

    embed_tokens = count_tokens([c.page_content for c in chunks])

    store = get_vector_store()
    for pdf_path in pdf_paths:
        store._collection.delete(where={"source": pdf_path.name})
    store.add_documents(chunks)
    return len(chunks), embed_tokens


def ingest_all() -> tuple[int, int]:
    """Rebuild/update the store from every PDF currently in data/pdfs/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))
    return ingest_files(pdf_paths)
