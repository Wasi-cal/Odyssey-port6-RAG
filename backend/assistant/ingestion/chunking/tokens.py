"""tiktoken encoder + the token-budget constants every other chunking module
is sized against.
"""

import tiktoken

from ...embeddings import EMBED_MAX_TOKENS

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
# of per-page (see ingestion/structure.py's build_full_text), that overlap
# also spans PAGE boundaries, which it never did before.
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
# Because the merge algorithm only ever moves whole atomic pieces, and
# prose.py's separators list bottoms out at ". " (sentence level) before
# falling back to word/character splitting, overlap is already
# sentence/paragraph-boundary-safe by construction for normal prose -- there
# was no need to write a custom sentence-aware overlap step; the existing
# RecursiveCharacterTextSplitter mechanism already guarantees it as long as
# no single atomic piece is degenerate enough to require splitting below
# ". " (which would require an implausibly long, period-free run of text).
#
# Note: the "{filename} — {section}\n\n" header prepended to each chunk (see
# masking.chunk_header) is added AFTER splitting, so it's not counted
# against this budget -- a chunk's real embedded size is ~200 tokens plus a
# short header. That's an intentional tradeoff: the header materially
# improves retrieval and citation quality, and text-embedding-3-small's
# 8191-token limit leaves enormous headroom above ~200-230 tokens.
#
# IMPORTANT: changing either constant changes chunk boundaries, so the index
# must be rebuilt after editing them: rm -rf ./chroma_db && re-ingest (e.g.
# `uv run ingest.py`). Old chunks in a stale ./chroma_db reflect the OLD
# boundaries and will not pick this up.
CHUNK_SIZE = 200
CHUNK_OVERLAP = 64

# EMBED_MAX_TOKENS (the embedding model's hard input limit) lives in
# embeddings.py -- that module is the single source of truth for everything
# about the embedding model, since ingestion (documents) and retrieval
# (queries) both need to agree on it exactly. A table chunk built without
# any cap would silently get truncated by the embeddings API past that
# limit, so TABLE_TOKEN_CAP reserves a 10% margin under it for the
# "{filename} — {section}\n\n" header every chunk gets prepended with (see
# masking.chunk_header) -- callers only need to size the table's own content
# against TABLE_TOKEN_CAP, not the header too.
TABLE_TOKEN_CAP = int(EMBED_MAX_TOKENS * 0.9)

_ENCODER = tiktoken.get_encoding("cl100k_base")


def token_len(text: str) -> int:
    return len(_ENCODER.encode(text))


def encode(text: str) -> list[int]:
    return _ENCODER.encode(text)


def decode(token_ids: list[int]) -> str:
    return _ENCODER.decode(token_ids)
