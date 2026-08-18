"""Retrieval tuning constants."""

# k=6: bumped up from the original k=4 now that ingestion chunks are sized in
# TOKENS (~200 tokens each, see ingestion/chunking.py's CHUNK_SIZE) rather
# than the old ~800-character chunks -- each chunk now covers noticeably less
# ground, so a slightly higher k keeps total retrieved coverage roughly
# comparable to before. Still comfortably inside the ~4-8 range that's sane
# for a stuffed gpt-4o-mini context: 6 chunks x (~200 content tokens + a
# short header) is a few hundred tokens, nowhere near the model's context
# limit.
K = 6

# search_type="mmr" (Maximal Marginal Relevance) instead of plain similarity:
# plain top-k similarity search on a well-populated store tends to return
# several near-duplicate chunks of the same passage. MMR re-ranks results to
# balance relevance against diversity, so the k chunks we hand to the LLM
# cover more of the document's actual content instead of repeating one spot.
SEARCH_TYPE = "mmr"
