"""
ingest.py — PDF -> chunk -> embed -> persist to Chroma.

Run standalone (`python ingest.py` or `uv run ingest.py`) to (re)build the vector
store from every PDF in data/pdfs/. app.py also calls `ingest_files()` directly
whenever a user uploads a new PDF through the Streamlit UI, so a brand-new
document works with zero code changes (M6S6).

This module OWNS writes to ./chroma_db. rag.py and app.py only ever read from it.

Pipeline (per PDF):
  1. Extract per-page Markdown text via pymupdf4llm, with an OCR fallback for
     pages that yield little/no text (scanned documents).
  2. Strip boilerplate lines (repeated headers/footers, "Page X of Y", etc.)
     that show up on most pages of the document.
  3. Concatenate ALL pages into one text stream and record each page's start
     offset, so chunking (and its overlap) can span page boundaries instead
     of being trapped inside a single page.
  4. Detect section headings (markdown #, ALL-CAPS lines, numbered clauses)
     and markdown table blocks across that whole-document stream.
  5. Emit each table as its own dedicated chunk (never split mid-table), and
     split the remaining prose with a token-aware RecursiveCharacterTextSplitter.
  6. Map every chunk back to the page it STARTS on and the nearest preceding
     heading, and prepend "{filename} — {section}" to its text before it is
     embedded, so citations and retrieval both benefit from that context.
"""

import bisect
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from chromadb.config import Settings as ChromaSettings
import pymupdf4llm
import fitz  # PyMuPDF -- already a dependency of pymupdf4llm; reused for OCR rasterization
import tiktoken

from embeddings import get_embeddings, EMBED_MODEL_NAME, EMBED_MAX_TOKENS

load_dotenv()

# --------------------------------------------------------------------------
# Constants — intentionally placed at the top of the file so they're easy to
# find and tune without digging through the ingestion logic below.
# --------------------------------------------------------------------------

# CHUNK_SIZE=200 / CHUNK_OVERLAP=64 TOKENS (~32%), measured with tiktoken's
# cl100k_base encoding (what gpt-4o-mini / text-embedding-3-small use).
#
# Sizing in tokens rather than characters keeps chunks consistent for the
# embedding model regardless of how dense the source text is -- 800 characters
# of table-heavy or heavily-punctuated text can be a very different number of
# tokens than 800 characters of plain prose, but the embedding model only
# ever "sees" tokens. 200 tokens is still roughly one coherent paragraph or
# policy clause. Overlap protects rules/definitions that straddle a chunk
# boundary -- and because chunking now runs over the WHOLE document instead
# of per-page (see _build_full_text below), that overlap also spans PAGE
# boundaries, which it never did before.
#
# CHUNK_OVERLAP was raised from 30 -> 64 after eval/golden_questions.yaml's
# q5 (Harborlight parental leave) surfaced a real chunk-boundary orphan: the
# sentence "Employees who have completed 12 months of service are eligible
# for up to 12 weeks of parental leave..." (~50 tokens as one atomic
# "\n\n"-delimited paragraph) sat at the tail of an unrelated "Code of
# Conduct" chunk, right before a chunk boundary. LangChain's splitter only
# ever carries back WHOLE atomic pieces into the overlap of the next chunk
# (see _merge_splits in langchain_text_splitters/base.py -- it pops pieces
# off the front of the finished chunk while their cumulative size exceeds
# chunk_overlap, but never slices INSIDE a piece), so with a 30-token budget
# that ~50-token paragraph was too big to carry across at all and simply
# vanished from both chunks. 64 tokens comfortably covers a single
# paragraph-sized piece like that one with room to spare, so it now gets
# carried forward into the next ("...four weeks of company-paid...") chunk
# instead of being orphaned. The cost is more duplicate text stored (~32%
# overlap vs. the original ~15%), which is a fine trade for not silently
# losing boundary-straddling facts.
#
# Because the merge algorithm only ever moves whole atomic pieces, and our
# separators list (see _split_prose below) bottoms out at ". " (sentence
# level) before falling back to word/character splitting, overlap is already
# sentence/paragraph-boundary-safe by construction for normal prose -- there
# was no need to write a custom sentence-aware overlap step; the existing
# RecursiveCharacterTextSplitter mechanism already guarantees it as long as
# no single atomic piece is degenerate enough to require splitting below
# ". " (which would require an implausibly long, period-free run of text).
#
# Note: the "{filename} — {section}\n\n" header prepended to each chunk (see
# _split_prose / _build_table_chunks) is added AFTER splitting, so it's not
# counted against this budget -- a chunk's real embedded size is ~200 tokens
# plus a short header. That's an intentional tradeoff: the header materially
# improves retrieval and citation quality, and text-embedding-3-small's
# 8191-token limit leaves enormous headroom above ~200-230 tokens.
#
# IMPORTANT: changing either constant changes chunk boundaries, so the index
# must be rebuilt after editing them: rm -rf ./chroma_db && re-ingest (e.g.
# `uv run ingest.py`). Old chunks in a stale ./chroma_db reflect the OLD
# boundaries and will not pick this up.
CHUNK_SIZE = 200
CHUNK_OVERLAP = 64

# A page whose extracted text is shorter than this is treated as "no usable
# text" (typical of a scanned/image page) and triggers the OCR fallback.
MIN_PAGE_TEXT_CHARS = 20

# Boilerplate detection: a (normalized) line that repeats across at least
# this fraction of a document's pages is treated as a running header/footer
# and stripped before chunking. Skipped entirely for very short documents,
# where "repeats across most pages" isn't a meaningful signal.
BOILERPLATE_MIN_PAGES = 3
BOILERPLATE_FREQUENCY_THRESHOLD = 0.6

# Placeholder character used to "mask" table regions (see _mask_spans) so the
# prose splitter never cuts into the middle of a table. Chosen because it's a
# single character (preserves 1:1 offset alignment with the original text)
# and effectively never appears in real documents.
_FILLER_CHAR = "￼"

# EMBED_MAX_TOKENS (the embedding model's hard input limit) lives in
# embeddings.py now -- that module is the single source of truth for
# everything about the embedding model, since ingest.py (documents) and
# rag.py (queries) both need to agree on it exactly. A table chunk built
# without any cap would silently get truncated by the embeddings API past
# that limit, so TABLE_TOKEN_CAP reserves a 10% margin under it for the
# "{filename} — {section}\n\n" header every chunk gets prepended with (see
# _chunk_header) -- callers only need to size the table's own content
# against TABLE_TOKEN_CAP, not the header too.
TABLE_TOKEN_CAP = int(EMBED_MAX_TOKENS * 0.9)

# OCR is rasterized at 300 DPI rather than PyMuPDF's ~96 DPI default --
# Tesseract's recognition accuracy drops sharply below ~250-300 DPI on
# scanned documents, which is precisely the case this fallback exists for.
OCR_DPI = 300

PAGE_SEPARATOR = "\n\n"

DATA_DIR = Path(__file__).parent / "data" / "pdfs"
PERSIST_DIR = str(Path(__file__).parent / "chroma_db")
COLLECTION_NAME = "internal_docs"

# Re-exported (not redefined) so rag.py's current `from ingest import
# EMBEDDING_MODEL` keeps working without touching rag.py in this task.
# embeddings.py is the single source of truth for the model name; this alias
# should go away once rag.py is updated to import EMBED_MODEL_NAME from
# embeddings.py directly instead.
EMBEDDING_MODEL = EMBED_MODEL_NAME

_ENCODER = tiktoken.get_encoding("cl100k_base")


def _token_len(text: str) -> int:
    return len(_ENCODER.encode(text))


def _require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )


# --------------------------------------------------------------------------
# 1. PDF extraction (with OCR fallback for scanned pages)
# --------------------------------------------------------------------------


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


def _extract_pages(pdf_path: Path) -> tuple[list[str], list[int]]:
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


# --------------------------------------------------------------------------
# 6. Boilerplate stripping (repeated headers/footers, "Page X of Y", etc.)
# --------------------------------------------------------------------------

_DIGIT_RE = re.compile(r"\d+")


def _normalize_line(line: str) -> str:
    # Collapse digit runs so "Page 3 of 42" and "Page 4 of 42" normalize to
    # the same signature ("page # of #") and count as the same repeated line.
    return _DIGIT_RE.sub("#", line.strip().lower())


def _strip_boilerplate(page_texts: list[str]) -> list[str]:
    if len(page_texts) < BOILERPLATE_MIN_PAGES:
        return page_texts

    per_page_lines = [text.split("\n") for text in page_texts]
    line_page_counts: dict[str, int] = {}
    for lines in per_page_lines:
        seen_this_page = set()
        for line in lines:
            norm = _normalize_line(line)
            if not norm or norm in seen_this_page:
                continue
            seen_this_page.add(norm)
            line_page_counts[norm] = line_page_counts.get(norm, 0) + 1

    threshold = len(page_texts) * BOILERPLATE_FREQUENCY_THRESHOLD
    boilerplate = {norm for norm, count in line_page_counts.items() if count >= threshold}

    return [
        "\n".join(line for line in lines if _normalize_line(line) not in boilerplate)
        for lines in per_page_lines
    ]


# --------------------------------------------------------------------------
# Whole-document text stream + page offset lookup (fixes cross-page overlap)
# --------------------------------------------------------------------------


def _build_full_text(page_texts: list[str]) -> tuple[str, list[int]]:
    """Concatenate all pages into one stream and record each page's start
    offset within it, so a chunk's character offset can be mapped back to
    the page it starts on (via bisect) after chunking the WHOLE document."""
    parts = []
    offsets = []
    offset = 0
    for text in page_texts:
        offsets.append(offset)
        parts.append(text)
        offset += len(text)
        parts.append(PAGE_SEPARATOR)
        offset += len(PAGE_SEPARATOR)
    return "".join(parts), offsets


def _offset_to_page(offset: int, page_offsets: list[int]) -> int:
    idx = bisect.bisect_right(page_offsets, offset) - 1
    return max(0, idx) + 1  # 1-indexed


# --------------------------------------------------------------------------
# 3. Section-heading detection
# --------------------------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
_NUMBERED_CLAUSE_RE = re.compile(r"^(?:Section\s+)?\d+(?:\.\d+)*\.?\s+[A-Z].{0,80}$")


def _is_all_caps_heading(line: str) -> bool:
    s = line.strip()
    if not (3 <= len(s) <= 80):
        return False
    if not any(c.isalpha() for c in s):
        return False
    return s == s.upper() and s != s.lower()


def _detect_headings(text: str) -> list[tuple[int, str]]:
    """Scan the whole-document text for heading-like lines. Returns a list of
    (char_offset, heading_text) sorted by offset (built in reading order)."""
    headings = []
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        md_match = _MD_HEADING_RE.match(stripped)
        if md_match:
            headings.append((offset, md_match.group(1).strip()))
        elif _NUMBERED_CLAUSE_RE.match(stripped):
            headings.append((offset, stripped))
        elif _is_all_caps_heading(stripped):
            headings.append((offset, stripped.title()))
        offset += len(line) + 1  # +1 for the "\n" split() consumed
    return headings


def _offset_to_section(offset: int, heading_positions: list[int], headings: list[tuple[int, str]]) -> str:
    idx = bisect.bisect_right(heading_positions, offset) - 1
    if idx < 0:
        return ""
    return headings[idx][1]


# --------------------------------------------------------------------------
# 4. Table detection -- tables are chunked as standalone units, never split
# --------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_MIN_ROWS = 2  # header + at least one data/separator row


def _detect_table_spans(text: str) -> list[tuple[int, int]]:
    """Find contiguous runs of markdown table rows ("| a | b |") and return
    their (start_offset, end_offset) spans in the whole-document text."""
    spans = []
    run_start = None
    run_rows = 0
    offset = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if _TABLE_ROW_RE.match(line):
            if run_start is None:
                run_start = offset
            run_rows += 1
        else:
            if run_start is not None and run_rows >= _TABLE_MIN_ROWS:
                spans.append((run_start, offset))
            run_start = None
            run_rows = 0
        offset += line_len
    if run_start is not None and run_rows >= _TABLE_MIN_ROWS:
        spans.append((run_start, offset))
    return spans


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace each span's characters 1:1 with a filler character. Because
    the replacement is the same length as the original, every other offset
    in the text (page starts, heading positions) stays valid -- and a chunk
    produced by the splitter can be mapped straight back to the original
    text's page/section lookup without any coordinate translation.

    INVARIANT this whole scheme depends on: len(_mask_spans(text, spans)) ==
    len(text), and every character OUTSIDE the given spans is untouched. That
    is what makes page_offsets / heading_positions -- both computed once
    against the pre-mask `full_text` in load_and_split -- still valid indices
    into the POST-mask `masked_text` that actually gets chunked in
    _split_prose. If this function is ever changed to insert/remove
    characters (e.g. a shorter placeholder token) instead of doing a same-
    length in-place replacement, that equivalence breaks and every citation
    after the first masked span on a page would silently drift.
    """
    for start, end in spans:
        text = text[:start] + (_FILLER_CHAR * (end - start)) + text[end:]
    return text


def _chunk_header(filename: str, section: str) -> str:
    return f"{filename} — {section}\n\n" if section else f"{filename}\n\n"


_SEPARATOR_ROW_RE = re.compile(r"^\s*\|[\s:\-\|]+\|\s*$")


def _split_table_header(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split a table's lines into its header row(s) and its data rows, so the
    header can be repeated at the top of every sub-chunk when the table gets
    split. Treats a markdown separator row ("|---|---|") right after the
    first row as part of the header; otherwise assumes a single header row."""
    if not lines:
        return [], []
    if len(lines) >= 2 and _SEPARATOR_ROW_RE.match(lines[1]):
        return lines[:2], lines[2:]
    return lines[:1], lines[1:]


def _split_long_row(row: str, available_tokens: int) -> list[str]:
    """Last-resort split of a single row that's over the cap even by itself --
    slices by raw tokens rather than by row, since there's no smaller natural
    unit than the row left to split on."""
    token_ids = _ENCODER.encode(row)
    available_tokens = max(available_tokens, 1)
    return [
        _ENCODER.decode(token_ids[i : i + available_tokens])
        for i in range(0, len(token_ids), available_tokens)
    ]


def _split_table_into_chunks(table_text: str, source: str, page: int) -> list[str]:
    """Split an oversized table BY ROWS (never by raw characters/tokens
    across a row boundary), repeating the header row(s) at the top of every
    sub-chunk so each piece is self-describing on its own. Returns a list of
    table-text pieces (without the outer "{filename} — {section}" chunk
    header, which the caller adds uniformly)."""
    lines = [line for line in table_text.split("\n") if line.strip()]
    header_lines, data_lines = _split_table_header(lines)
    header_text = "\n".join(header_lines)
    header_tokens = _token_len(header_text)

    # Greedily pack data rows into groups that stay under TABLE_TOKEN_CAP
    # together with the repeated header.
    groups: list[list[str]] = []
    current_rows: list[str] = []
    for row in data_lines:
        candidate = current_rows + [row]
        candidate_text = header_text + "\n" + "\n".join(candidate)
        if current_rows and _token_len(candidate_text) > TABLE_TOKEN_CAP:
            groups.append(current_rows)
            current_rows = [row]
        else:
            current_rows = candidate
    if current_rows:
        groups.append(current_rows)

    sub_tables = []
    for group in groups:
        group_text = header_text + "\n" + "\n".join(group)
        if _token_len(group_text) <= TABLE_TOKEN_CAP:
            sub_tables.append(group_text)
            continue

        # This only happens when a SINGLE row (plus the header) is already
        # over the cap -- the greedy loop above never lets a group grow past
        # the cap once it holds more than one row.
        print(
            f"[ingest] WARNING: {source} p.{page}: a table row exceeds "
            f"TABLE_TOKEN_CAP ({TABLE_TOKEN_CAP} tokens) even on its own -- "
            f"splitting it by tokens instead of by row.",
            file=sys.stderr,
        )
        available = TABLE_TOKEN_CAP - header_tokens
        for row in group:
            for piece in _split_long_row(row, available):
                sub_tables.append(header_text + "\n" + piece)

    if not sub_tables:
        # Pathological edge case: a "table" with header/separator rows but no
        # data rows at all. Still emit something rather than silently
        # dropping this span's content.
        sub_tables = [header_text or table_text]

    return sub_tables


def _build_table_chunks(
    filename: str,
    full_text: str,
    table_spans: list[tuple[int, int]],
    page_offsets: list[int],
    headings: list[tuple[int, str]],
    heading_positions: list[int],
) -> list[Document]:
    chunks = []
    for start, end in table_spans:
        table_text = full_text[start:end].strip("\n")
        if not table_text.strip():
            continue
        page = _offset_to_page(start, page_offsets)
        section = _offset_to_section(start, heading_positions, headings)
        chunk_header = _chunk_header(filename, section)

        if _token_len(chunk_header + table_text) <= TABLE_TOKEN_CAP:
            # Common case: the whole table fits comfortably -- keep it as one
            # self-contained chunk, same as before.
            sub_tables = [table_text]
        else:
            # Oversized table (problem #1): split BY ROWS instead of letting
            # it get silently truncated at embed time.
            sub_tables = _split_table_into_chunks(table_text, filename, page)

        for part_index, sub_table_text in enumerate(sub_tables):
            chunks.append(
                Document(
                    page_content=chunk_header + sub_table_text,
                    metadata={
                        "source": filename,
                        "page": page,
                        "section": section,
                        "is_table": True,
                        "table_part": part_index,
                    },
                )
            )
    return chunks


# --------------------------------------------------------------------------
# 2 & 3. Token-aware prose splitting, mapped back to page + section
# --------------------------------------------------------------------------


def _split_prose(
    filename: str,
    masked_text: str,
    page_offsets: list[int],
    headings: list[tuple[int, str]],
    heading_positions: list[int],
) -> list[Document]:
    # separators bottom out at ". " (sentence level) before falling back to
    # " " (word) / "" (character) splitting -- combined with chunk_overlap
    # only ever carrying back WHOLE atomic pieces (never a fragment; see the
    # CHUNK_OVERLAP comment above for why), this is what keeps overlap
    # sentence/paragraph-boundary-safe without any custom post-processing.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=_token_len,
        separators=["\n\n", "\n", ". ", " ", ""],
        add_start_index=True,
    )
    raw_docs = splitter.create_documents([masked_text])

    chunks = []
    for doc in raw_docs:
        # `start` is an offset into masked_text (that's what was split), but
        # page_offsets/headings were computed from the pre-mask full_text --
        # this is safe only because _mask_spans guarantees masked_text is the
        # same length as full_text with identical content outside the masked
        # spans (see the INVARIANT note on _mask_spans). So `start` is used
        # directly here with no translation between the two streams.
        start = doc.metadata.get("start_index", 0)
        # Strip masked table characters back out. Any chunk that fell
        # entirely inside a masked span becomes empty here and is dropped --
        # that table already has its own dedicated chunk from
        # _build_table_chunks, so nothing is lost.
        cleaned = doc.page_content.replace(_FILLER_CHAR, "").strip()
        if not cleaned:
            continue
        page = _offset_to_page(start, page_offsets)
        section = _offset_to_section(start, heading_positions, headings)
        chunks.append(
            Document(
                page_content=_chunk_header(filename, section) + cleaned,
                metadata={"source": filename, "page": page, "section": section},
            )
        )
    return chunks


# --------------------------------------------------------------------------
# Per-document pipeline
# --------------------------------------------------------------------------


def load_and_split(pdf_paths: list[Path]) -> list[Document]:
    """Load each PDF, chunk it, and return chunks carrying
    metadata {"source": <filename>, "page": <page_number>, "section": <heading>}.

    This is what lets rag.py produce citations like "Employee Handbook →
    Parental Leave, p.12" later, since Chroma stores and returns this
    metadata (and the header baked into page_content) untouched.
    """
    all_chunks = []
    for pdf_path in pdf_paths:
        page_texts, ocr_pages = _extract_pages(pdf_path)
        if ocr_pages:
            print(f"[ingest] {pdf_path.name}: OCR fallback used for page(s) {ocr_pages}")

        page_texts = _strip_boilerplate(page_texts)
        full_text, page_offsets = _build_full_text(page_texts)

        if not full_text.strip():
            # Never silently drop a document: log loudly and move on, rather
            # than pretending ingestion succeeded.
            print(
                f"[ingest] WARNING: {pdf_path.name} yielded no extractable text "
                f"even after OCR -- it was NOT added to the vector store.",
                file=sys.stderr,
            )
            continue

        headings = _detect_headings(full_text)
        heading_positions = [h[0] for h in headings]
        table_spans = _detect_table_spans(full_text)

        all_chunks.extend(
            _build_table_chunks(pdf_path.name, full_text, table_spans, page_offsets, headings, heading_positions)
        )

        masked_text = _mask_spans(full_text, table_spans)
        all_chunks.extend(_split_prose(pdf_path.name, masked_text, page_offsets, headings, heading_positions))

    return all_chunks


def get_vector_store() -> Chroma:
    """Return a handle to the persisted Chroma collection (read or write).

    embedding_function comes from the shared embeddings.get_embeddings(), not
    a locally-constructed OpenAIEmbeddings -- rag.py must use the exact same
    function for query embedding, or similarity search is comparing vectors
    from two different embedding spaces and retrieval quietly breaks.

    collection_metadata sets cosine distance, which is what OpenAI's
    embeddings (including text-embedding-3-small) are designed to be compared
    with. NOTE: Chroma only applies this at collection CREATION time -- if
    ./chroma_db already has an "internal_docs" collection from before this
    change (default space, not cosine), this metadata is silently ignored on
    the existing collection. Delete ./chroma_db and re-ingest fresh (already
    the plan given the chunking-schema changes) to actually pick this up.
    """
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=PERSIST_DIR,
        # is_persistent=True is REQUIRED here, not implied by passing
        # persist_directory -- langchain_chroma only auto-sets it when
        # client_settings is omitted entirely. Without this, Chroma silently
        # falls back to an in-memory-only client: writes "succeed" within
        # the current process but chroma_db/ is never created and nothing
        # survives a restart (found via eval/run_eval.py returning 0 hits
        # against a store that ingest.py had just reported success on).
        client_settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        collection_metadata={"hnsw:space": "cosine"},
    )


def ingest_files(pdf_paths: list[Path]) -> int:
    """Embed and persist the given PDFs into Chroma. Returns chunk count added.

    Safe to call repeatedly (e.g. once per uploaded file) — Chroma appends new
    vectors to the existing persisted collection rather than rebuilding it.
    """
    _require_api_key()
    if not pdf_paths:
        return 0

    chunks = load_and_split(pdf_paths)
    if not chunks:
        return 0

    store = get_vector_store()
    store.add_documents(chunks)
    return len(chunks)


def ingest_all() -> int:
    """Rebuild/update the store from every PDF currently in data/pdfs/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))
    return ingest_files(pdf_paths)


if __name__ == "__main__":
    try:
        _require_api_key()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))

    if not pdf_paths:
        print(f"No PDFs found in {DATA_DIR}. Add some and re-run.")
        sys.exit(0)

    print(f"Found {len(pdf_paths)} PDF(s): {[p.name for p in pdf_paths]}")
    count = ingest_files(pdf_paths)
    print(f"Ingested {count} chunks into '{COLLECTION_NAME}' at {PERSIST_DIR}")
