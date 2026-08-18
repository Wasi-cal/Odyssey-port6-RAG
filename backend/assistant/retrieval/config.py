"""Retrieval tuning constants."""

# k=10: bumped from 6 after an umbrella-style question ("what is the leave
# policy" -- an umbrella term spanning parental/sick/vacation leave, each its
# own section) only retrieved 2 of the 3 relevant sections at k=6, so the
# answer silently omitted vacation entirely. k=10 pulled in all 3 in testing,
# and rule 7 in prompt.py now also explicitly tells the model to enumerate
# every distinct policy an umbrella term could cover, not just the first
# match -- the two fixes address different failure modes (retrieval missing
# a chunk vs. the model stopping early even when it has the chunk) and both
# were needed. Still nowhere near the model's context limit: 10 chunks x
# (~200 content tokens + a short header) is at most a couple thousand
# tokens. Configurable live via config_settings (category='retrieval',
# key='k') without a redeploy -- see assistant/config_store.py.
K = 10

# search_type="mmr" (Maximal Marginal Relevance) instead of plain similarity:
# plain top-k similarity search on a well-populated store tends to return
# several near-duplicate chunks of the same passage. MMR re-ranks results to
# balance relevance against diversity, so the k chunks we hand to the LLM
# cover more of the document's actual content instead of repeating one spot.
SEARCH_TYPE = "mmr"
