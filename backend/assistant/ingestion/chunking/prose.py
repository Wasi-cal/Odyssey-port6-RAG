"""The remaining prose (everything outside a masked table span), split with
a token-aware RecursiveCharacterTextSplitter and mapped back to page/section.
"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..structure import offset_to_page, resolve_heading_path
from .masking import chunk_header, strip_filler
from .tokens import CHUNK_OVERLAP, CHUNK_SIZE, token_len


def split_prose(
    filename: str,
    masked_text: str,
    page_offsets: list[int],
    headings: list[tuple[int, int, str]],
    heading_positions: list[int],
    section_level: int,
) -> list[Document]:
    # separators bottom out at ". " (sentence level) before falling back to
    # " " (word) / "" (character) splitting -- combined with chunk_overlap
    # only ever carrying back WHOLE atomic pieces (never a fragment; see the
    # CHUNK_OVERLAP comment in tokens.py for why), this is what keeps overlap
    # sentence/paragraph-boundary-safe without any custom post-processing.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=token_len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    raw_docs = splitter.create_documents([masked_text])

    # NOT using the splitter's own add_start_index: measured on this
    # project's own sample PDFs, it returns -1 ("couldn't relocate this
    # chunk") for roughly a THIRD of chunks once chunk_overlap is this large
    # (~32%, see tokens.py) -- a known limitation of its search heuristic,
    # not something specific to these documents. Every -1 chunk silently
    # lost its page/section/subsection attribution, which is a large chunk
    # of exactly the "citations aren't detailed enough" complaint this was
    # written to fix. Recomputing positions ourselves with a plain forward
    # `str.find` from the previous chunk's own start (chunks are guaranteed
    # non-decreasing in position, so this is safe even with overlap) located
    # every single chunk correctly in that same measurement.
    chunks = []
    search_from = 0
    for doc in raw_docs:
        start = masked_text.find(doc.page_content, search_from)
        if start == -1:
            start = masked_text.find(doc.page_content)  # pathological fallback
        if start != -1:
            search_from = start
        start = max(start, 0)

        # `start` is an offset into masked_text (that's what was split), but
        # page_offsets/headings were computed from the pre-mask full_text --
        # this is safe only because masking.mask_spans guarantees masked_text
        # is the same length as full_text with identical content outside the
        # masked spans (see the INVARIANT note on mask_spans). So `start` is
        # used directly here with no translation between the two streams.
        cleaned = strip_filler(doc.page_content).strip()
        if not cleaned:
            continue
        page = offset_to_page(start, page_offsets)
        section, subsection = resolve_heading_path(start, heading_positions, headings, section_level)
        chunks.append(
            Document(
                page_content=chunk_header(filename, section, subsection) + cleaned,
                metadata={"source": filename, "page": page, "section": section, "subsection": subsection},
            )
        )
    return chunks
