"""The remaining prose (everything outside a masked table span), split at
heading boundaries FIRST, then by token budget within each heading segment --
mapped back to page/section as it goes.
"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..structure import offset_to_page, resolve_heading_path
from .masking import chunk_header, strip_filler
from .tokens import CHUNK_OVERLAP, CHUNK_SIZE, token_len


def _segment_bounds(text_len: int, heading_positions: list[int]) -> list[tuple[int, int]]:
    """One (start, end) span per heading -- from that heading's own offset to
    the next heading's offset, or end of document -- plus a leading span for
    any front matter before the first heading (title, version table, etc).

    This is what makes a heading a HARD cut: every downstream split (the
    per-segment token splitter below) operates on ONE of these spans at a
    time and can never see across it, so a chunk can no longer straddle two
    subsections' content the way the old whole-document split could.
    """
    if not heading_positions:
        return [(0, text_len)] if text_len > 0 else []
    starts = heading_positions if heading_positions[0] == 0 else [0] + heading_positions
    ends = starts[1:] + [text_len]
    return [(s, e) for s, e in zip(starts, ends) if e > s]


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
    # Now only ever invoked on ONE heading segment at a time (see below), so
    # overlap can no longer carry content across a heading boundary either --
    # that's an intentional consequence of making headings a hard cut, not
    # an oversight: a fact that straddles exactly a heading boundary was
    # previously rescued by overlap into whichever chunk needed it, but
    # letting that happen was also exactly what let one subsection's content
    # bleed into an adjacent subsection's chunk (see git history: this
    # caused two real production retrieval bugs, eval/golden_questions.yaml's
    # q6 and q8, where a chunk's reported section didn't match what its
    # drifted-in content actually needed to be found under).
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=token_len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = []
    for seg_start, seg_end in _segment_bounds(len(masked_text), heading_positions):
        segment_text = masked_text[seg_start:seg_end]

        # Resolved ONCE per segment, at the segment's own start offset -- and
        # now EXACT, not approximate: every character in [seg_start, seg_end)
        # belongs to this same heading by construction (see _segment_bounds),
        # so there's no longer any risk of a chunk's section/subsection
        # metadata not matching a heading its own trailing content has
        # drifted into. resolve_heading_path itself didn't need to change --
        # the old inaccuracy was entirely a consequence of calling it on a
        # chunk whose content could span past the heading its start offset
        # pointed at; that's now structurally impossible.
        page = offset_to_page(seg_start, page_offsets)
        section, subsection = resolve_heading_path(seg_start, heading_positions, headings, section_level)
        header = chunk_header(filename, section, subsection)

        cleaned_segment = strip_filler(segment_text).strip()
        if not cleaned_segment:
            continue

        if token_len(cleaned_segment) <= CHUNK_SIZE:
            # Whole segment fits in one chunk -- kept as its own chunk even
            # if short (e.g. a 3-sentence "1.1 Objective" section), rather
            # than merged with whatever segment comes before or after it.
            chunks.append(
                Document(
                    page_content=header + cleaned_segment,
                    metadata={"source": filename, "page": page, "section": section, "subsection": subsection},
                )
            )
            continue

        # Oversized segment: split IT ALONE with the token-aware splitter, so
        # a long section still becomes several ~200-token pieces -- but every
        # piece stays inside this segment's own [seg_start, seg_end) span,
        # never reaching into the next heading.
        #
        # NOT using the splitter's own add_start_index here either, for the
        # same reason the old whole-document split didn't: measured on this
        # project's own sample PDFs, it returns -1 ("couldn't relocate this
        # chunk") for roughly a third of chunks once chunk_overlap is this
        # large (~32%, see tokens.py) -- recomputing positions ourselves with
        # a plain forward `str.find` from the previous piece's own start
        # (pieces are guaranteed non-decreasing in position within a segment,
        # same as chunks used to be within the whole document) is safe and
        # exact, now scoped to the smaller per-segment search space.
        raw_pieces = splitter.create_documents([segment_text])
        search_from = 0
        for piece in raw_pieces:
            local_start = segment_text.find(piece.page_content, search_from)
            if local_start == -1:
                local_start = segment_text.find(piece.page_content)  # pathological fallback
            if local_start != -1:
                search_from = local_start
            local_start = max(local_start, 0)

            piece_cleaned = strip_filler(piece.page_content).strip()
            if not piece_cleaned:
                continue

            piece_page = offset_to_page(seg_start + local_start, page_offsets)
            chunks.append(
                Document(
                    page_content=header + piece_cleaned,
                    metadata={"source": filename, "page": piece_page, "section": section, "subsection": subsection},
                )
            )

    return chunks
