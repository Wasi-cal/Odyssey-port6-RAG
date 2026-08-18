"""The "{filename} — {section} > {subsection}" chunk header, and masking
table regions in the whole-document text so the prose splitter never cuts
into the middle of one.
"""

# Placeholder character used to "mask" table regions (see mask_spans) so the
# prose splitter never cuts into the middle of a table. Chosen because it's a
# single character (preserves 1:1 offset alignment with the original text)
# and effectively never appears in real documents.
_FILLER_CHAR = "￼"


def chunk_header(filename: str, section: str, subsection: str = "") -> str:
    """Prepended to every chunk before embedding -- this is what lets a
    retrieved chunk be traced back to exactly where in the document it came
    from (both for the LLM's own context and for the final citation string),
    and it materially improves retrieval quality by giving the embedding
    model that same location context.
    """
    heading = " > ".join(part for part in (section, subsection) if part)
    return f"{filename} — {heading}\n\n" if heading else f"{filename}\n\n"


def mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace each span's characters 1:1 with a filler character. Because
    the replacement is the same length as the original, every other offset
    in the text (page starts, heading positions) stays valid -- and a chunk
    produced by the splitter can be mapped straight back to the original
    text's page/section lookup without any coordinate translation.

    INVARIANT this whole scheme depends on: len(mask_spans(text, spans)) ==
    len(text), and every character OUTSIDE the given spans is untouched. That
    is what makes page_offsets / heading_positions -- both computed once
    against the pre-mask `full_text` in pipeline.load_and_split -- still
    valid indices into the POST-mask `masked_text` that actually gets
    chunked in prose.split_prose. If this function is ever changed to
    insert/remove characters (e.g. a shorter placeholder token) instead of
    doing a same-length in-place replacement, that equivalence breaks and
    every citation after the first masked span on a page would silently
    drift.
    """
    for start, end in spans:
        text = text[:start] + (_FILLER_CHAR * (end - start)) + text[end:]
    return text


def strip_filler(text: str) -> str:
    """Remove the filler character mask_spans inserted. A chunk that fell
    entirely inside a masked span comes back empty here -- that table already
    has its own dedicated chunk from tables.build_table_chunks, so nothing is
    lost by dropping it.
    """
    return text.replace(_FILLER_CHAR, "")
