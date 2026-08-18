# Evaluation harness

Turns "the retrieval/prompt looks reasonable" into hard numbers, run against a
hand-labeled set of questions (`golden_questions.yaml`) with known-correct
answers.

This harness **reuses the real pipeline** — it imports and calls
`rag.answer_question()` and `rag.get_retriever()` directly (the same
entrypoints `app.py` uses), so it measures exactly what a user gets, not a
parallel copy of the logic that could drift out of sync. It never modifies
`rag.py`, `ingest.py`, or `embeddings.py`.

## Setup

1. Make sure your PDFs are ingested: `uv run ingest.py`
2. Make sure `OPENAI_API_KEY` is set (`.env`) — the harness calls the same
   OpenAI-backed embeddings and generation the app uses; there's no offline
   mode for the RAG pipeline itself.
3. Add your own questions to `golden_questions.yaml` (see the comment block
   at the top of that file for the schema and instructions). The file ships
   pre-populated with 8 in_scope + 3 out_of_scope questions against the
   sample HR handbooks in `data/pdfs/` — replace them with questions grounded
   in your own documents once you swap those PDFs out.

## Running it

```bash
# Cheap metrics only: retrieval, citations, refusal accuracy (no LLM judge calls)
uv run eval/run_eval.py

# Also score answer correctness with an LLM judge (1 extra API call per in_scope question)
uv run eval/run_eval.py --judge

# Use a different question set
uv run eval/run_eval.py --questions eval/my_other_set.yaml
```

Output:
- A per-question breakdown printed to the console.
- An aggregate summary printed to the console.
- `reports/eval_results.csv` — one row per question, every metric as a column.
- `reports/eval_summary.json` — the aggregate numbers, for tracking over time
  (e.g. diffing two runs after a chunking change).

This is a **report, not a gate** — the script always exits 0, even if every
metric is terrible or the question set is empty. It's meant to be read, not
wired into a CI pass/fail check as-is.

## Metrics, and what "good" looks like

### Retrieval Recall@K
Out of the `k` chunks retrieved (`k` is `rag.py`'s own `K` constant — the
harness doesn't second-guess it), did at least one come from the
`expected_source` PDF on one of the `expected_pages` (± the page tolerance
below)? Averaged across all in_scope questions.

**What's good:** high 0.8s–1.0 for a small, well-labeled golden set. If
Recall@K is low (under ~0.8), **the problem is retrieval or chunking, not the
generation prompt** — no prompt engineering fixes a wrong answer if the right
chunk was never handed to the model in the first place. Look at chunk size,
`k`, MMR diversity, or whether the fact is buried in a chunk that's
competing with too many near-duplicates.

### Mean MRR (Mean Reciprocal Rank)
For each in_scope question, `1 / rank` of the *first* relevant chunk among
the retrieved results (0 if none was relevant). Averaged across questions.

**What's good:** close to 1.0 means relevant chunks tend to rank first, which
is what you want, since gpt-4o-mini reads the context in order and a
correct-but-buried chunk is more likely to get glossed over than one at the
top. A Recall@K near 1.0 but a much lower MRR means retrieval usually *finds*
the right chunk, just doesn't rank it highly — a good sign MMR's diversity
tradeoff or `k` might be worth revisiting even though recall looks fine.

### Page tolerance (±1)
Chunks are tagged with the page they **start on** (see `ingest.py`), not
every page their text touches. A chunk whose real content mostly falls on
page 5 might get tagged page 4 if the chunk boundary landed just before that
page break. The ±1 tolerance absorbs that labeling quirk. It does NOT mean
"off by a page is fine" for a human reading a citation — it exists purely so
the *harness* doesn't penalize the pipeline for a known metadata artifact
that has nothing to do with retrieval quality.

### Citation recall / precision
- **Citation recall**: of the in_scope questions, what fraction had
  `expected_source` present *somewhere* in the final answer's cited sources?
  (Source-level only — page correctness is what Recall@K/MRR already cover.)
- **Citation precision**: of the sources the answer actually cited, what
  fraction were the expected one? Averaged only over questions where at
  least one source was cited (a "no citations" answer has undefined
  precision, not zero — it's a recall failure, already counted there).

**What's good:** both close to 1.0. Low citation recall with high retrieval
Recall@K means the right chunk WAS retrieved but the model didn't cite it —
that's a prompt/generation problem, not a retrieval one. Low citation
precision means the model is citing sources that aren't actually relevant —
watch for this specifically on documents with very similar structure/wording
(the three sample HR handbooks are a deliberate stress test for this: same
section headings, different numbers).

**Known limitation:** this assumes one relevant source document per
question (the golden set only labels one). If a question could legitimately
be answered by facts spread across multiple real documents, precision will
under-count a correct multi-source citation as a false positive. Splitting
such a question into two single-source questions is usually the simpler fix;
labeling multiple `expected_source`s per question would be the alternative
if you hit this often.

### Answer correctness (`--judge` only)
An LLM judge (`gpt-4o-mini`, temperature 0) is shown the question, the
`key_facts` you labeled, and the generated answer, and asked only: are all
key facts present, and does nothing contradict them? It explicitly does not
score style, verbosity, or citation formatting — that's what the other
metrics are for. Skipped entirely without `--judge` (no extra API calls).

**What's good:** close to 1.0. If retrieval Recall@K is high but answer
correctness is low, the right information was available but the model
didn't extract/state it correctly — check the grounding prompt's clarity, or
whether the retrieved chunk's phrasing is more ambiguous than the golden
`key_facts` assume.

### Facts in context / fact retrieval gap

`facts_in_context` (shown as e.g. `1/2`) is a plain, judge-free check: for
each `key_fact` you labeled, is it present (case-insensitive, whitespace-
normalized substring match) somewhere in the actual retrieved chunk text?
This runs unconditionally — no `--judge` needed — since it's just checking
what was retrieved, not what the model said about it.

`fact_retrieval_gap` (only computed with `--judge`, since it needs a
correctness verdict) is `True` when an answer was marked incorrect **and**
at least one key fact was never in the retrieved context at all. This is
the instant self-classifier for a failure:

- **`fact_retrieval_gap=True`** → the missing fact was never handed to the
  model. This is a **chunking/retrieval problem** — go look at how the
  source document is chunked (is a fact orphaned at a chunk boundary the
  way q5's Harborlight parental-leave sentence was?), not at the prompt.
  No amount of prompt tuning fixes a fact the model never saw.
- **`fact_retrieval_gap=False`** on an incorrect answer → every key fact
  *was* in context, but the model still didn't state it (or contradicted
  it, or answered incompletely). That's a **generation/prompt problem** —
  the grounding prompt's completeness rules, phrasing, or the model itself
  is what to revisit.

Without this column, both failure modes just look like "answer_correct:
FAIL" and you're back to manually re-running retrieval by hand to figure
out which one you're looking at (which is exactly what happened
investigating q5 before this column existed).

### Refusal accuracy / hallucination count (out_of_scope questions)
For each out_of_scope question, does the answer match, **character for
character**, `"I don't know based on the provided documents."`? Anything
else — a partial answer, a hedge, an answer to a *different* but
similar-sounding question — counts as a failure, and the **hallucination
count** is exactly the number of out_of_scope questions that failed this
check.

**What's good:** refusal accuracy at 1.0 and hallucination count at 0. This
is the metric to take most seriously for an internal-docs tool: a wrong
"I don't know" costs a user a follow-up question; a hallucinated answer to an
out-of-scope question (especially a "near miss" one that name-drops a real
document, like `q10`/`q11` in the sample set) can cost real trust in the
tool. Any hallucination here is worth investigating before anything else on
this list.

## Adding more questions

See the schema and instructions in the comment block at the top of
`golden_questions.yaml`. A few tips beyond what's there:

- Spread in_scope questions across **all** your documents, not just one —
  otherwise a single badly-chunked document can hide behind good numbers
  from the rest of the library.
- Include at least one table-derived fact and one prose fact per document if
  you can — they exercise different parts of `ingest.py` (table chunks vs.
  prose chunks) and can fail independently.
- For out_of_scope questions, include at least one "near miss" — plausible,
  maybe naming a real document or company, but genuinely not covered. Purely
  random unrelated questions (weather, trivia) are the easy case; a near
  miss is what actually tests whether the grounding prompt holds up.
