"""
eval/run_eval.py — evaluation harness for the RAG assistant.

Turns "the prompt looks reasonable" into hard numbers for retrieval, citations,
and hallucination, run against a hand-labeled golden question set
(eval/golden_questions.yaml).

This file REUSES rag.py's own query entrypoint (answer_question) and retriever
(get_retriever) rather than reimplementing retrieval or generation -- the whole
point of an eval harness is to measure the real pipeline app.py calls, not a
parallel copy of it that could quietly drift out of sync. rag.py itself is not
modified by anything here.

Run from the project root:
    uv run eval/run_eval.py                 # cheap metrics only (no judge calls)
    uv run eval/run_eval.py --judge         # also runs the LLM-as-judge check
    uv run eval/run_eval.py --questions eval/my_other_set.yaml

See eval/README.md for what each metric means and what "good" looks like.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import yaml

# rag.py, ingest.py, embeddings.py all live at the project root, one level up
# from this file -- add it to sys.path so `uv run eval/run_eval.py` works
# regardless of the caller's current working directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from langchain_openai import ChatOpenAI  # noqa: E402  (after sys.path insert)

from rag import (  # noqa: E402
    K,
    FALLBACK_GIBBERISH,
    FALLBACK_GREETING,
    FALLBACK_HANDOFF,
    FALLBACK_UNANSWERED,
    FALLBACK_UNCLEAR,
    FALLBACK_UNRELATED,
    answer_question,
    format_citation,
    get_retriever,
    store_is_empty,
)

# A correct refusal can land on any of the fixed-response paths (rule 2 in
# retrieval/prompt.py) -- an out_of_scope golden question isn't labeled with
# which one it should trigger, so any of these counts as "didn't
# hallucinate", which is what this eval is actually checking for.
_FALLBACK_RESPONSES = {
    FALLBACK_GREETING,
    FALLBACK_HANDOFF,
    FALLBACK_UNCLEAR,
    FALLBACK_GIBBERISH,
    FALLBACK_UNRELATED,
    FALLBACK_UNANSWERED,
}

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Cross-page chunks are tagged with the page they START on (see ingest.py's
# _offset_to_page) -- a fact that actually reads naturally on page N+1 can
# still get attributed to page N if the chunk boundary lands just before the
# page break. A tolerance of 1 absorbs that quirk without being so loose that
# a genuinely wrong page still counts as a hit.
PAGE_TOLERANCE = 1

# Fixed model + temperature=0 (set where judge_llm is constructed in main())
# so judge verdicts are reproducible run-to-run on an unchanged pipeline --
# a flaky judge would make it impossible to tell whether a correctness
# score changed because the RAG pipeline changed or because the judge
# happened to roll differently this time.
JUDGE_MODEL = "gpt-4o-mini"

JUDGE_SYSTEM_PROMPT = """You are a strict grading assistant for a RAG system's \
generated answers. You will be given a question, a list of key facts the \
correct answer must contain, and the system's generated answer.

Judge ONLY these two things:
1. Does the answer state every key fact (paraphrasing is fine; omitting one \
is not)?
2. Does the answer contradict any key fact?

Do not penalize style, verbosity, extra correct detail, or citation \
formatting -- those are scored separately by other metrics. If the answer is \
the literal refusal "I don't know based on the provided documents." while key \
facts were supplied, that is INCORRECT (a miss, not a pass).

Respond with ONLY a JSON object and nothing else, no markdown fences: \
{"correct": true or false, "reason": "<one short sentence>"}"""

REPORTS_DIR = _PROJECT_ROOT / "reports"

# Fixed column order so the CSV has one consistent header even though
# in_scope and out_of_scope rows populate different subsets of these fields.
FIELDNAMES = [
    "id",
    "type",
    "question",
    "error",
    "answer",
    "num_chunks_retrieved",
    "cited_sources",
    "retrieval_hit",
    "hit_rank",
    "mrr",
    "citation_recall_hit",
    "citation_precision",
    "num_cited",
    "num_relevant_cited",
    "facts_in_context",
    "num_key_facts",
    "fact_retrieval_gap",
    "answer_correct",
    "judge_reason",
    "refusal_correct",
]


# --------------------------------------------------------------------------
# Golden set loading
# --------------------------------------------------------------------------


def load_questions(path: str) -> list[dict]:
    """Load and validate the golden question set. Malformed items are
    skipped with a warning rather than crashing the whole run -- one typo in
    question #9 shouldn't cost you the other ten results."""
    path = Path(path)
    if not path.exists():
        print(f"WARNING: golden question file not found: {path}", file=sys.stderr)
        return []

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        return []

    questions = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or not {"id", "question", "type"} <= item.keys():
            print(f"WARNING: skipping malformed item at index {i} (needs id/question/type): {item!r}", file=sys.stderr)
            continue
        if item["type"] not in ("in_scope", "out_of_scope"):
            print(f"WARNING: skipping item {item['id']!r} with unknown type {item['type']!r}", file=sys.stderr)
            continue
        if item["type"] == "in_scope":
            missing = [k for k in ("expected_source", "expected_pages", "key_facts") if k not in item]
            if missing:
                print(f"WARNING: skipping in_scope item {item['id']!r}, missing fields: {missing}", file=sys.stderr)
                continue
        questions.append(item)
    return questions


# --------------------------------------------------------------------------
# Metric scoring
# --------------------------------------------------------------------------


def _page_matches(actual_page, expected_pages: list[int]) -> bool:
    if not isinstance(actual_page, int):
        return False
    return any(abs(actual_page - p) <= PAGE_TOLERANCE for p in expected_pages)


def score_retrieval(docs, expected_source: str, expected_pages: list[int]) -> tuple[bool, float, int | None]:
    """docs: ranked chunks from get_retriever().invoke(question), rank 0 =
    most relevant (MMR order). Returns (hit, mrr, hit_rank)."""
    for rank, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source")
        page = doc.metadata.get("page")
        if source == expected_source and _page_matches(page, expected_pages):
            return True, 1.0 / rank, rank
    return False, 0.0, None


def score_citations(sources: list[dict], expected_source: str) -> tuple[bool, float | None, int, int]:
    """sources: RagResult.sources (already deduped by rag.py). Citation
    correctness is judged at the SOURCE level here (per the task spec) --
    page-level accuracy is what Retrieval Recall@K/MRR already measure.

    NOTE: this assumes a single relevant source document per question (the
    golden set only labels one). If your questions could legitimately be
    answered by facts spread across multiple documents, precision will
    under-count correct multi-source citations as false positives -- see
    eval/README.md.
    """
    num_cited = len(sources)
    num_relevant = sum(1 for s in sources if s.get("source") == expected_source)
    recall_hit = num_relevant > 0
    precision = (num_relevant / num_cited) if num_cited > 0 else None
    return recall_hit, precision, num_cited, num_relevant


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def score_fact_presence(docs, key_facts: list[str]) -> int:
    """Case-insensitive, whitespace-normalized substring check: was each
    key_fact actually present somewhere in the retrieved chunk text?

    This is the diagnostic that separates a CHUNKING/RETRIEVAL failure from a
    GENERATION failure: if a key_fact never made it into the context handed
    to the LLM, no prompt fix can produce it in the answer -- that's on
    chunking/retrieval (see fact_retrieval_gap in evaluate_question). If
    every key_fact WAS in context and the judge still marked the answer
    incorrect, that's on generation/the prompt.
    """
    context_text = _normalize_ws(" ".join(doc.page_content for doc in docs))
    return sum(1 for fact in key_facts if _normalize_ws(fact) in context_text)


def judge_answer(question: str, key_facts: list[str], answer: str, judge_llm: ChatOpenAI) -> tuple[bool, str]:
    """LLM-as-judge: does `answer` state every key fact and contradict none?
    Returns (correct, reason). Never raises -- an unparseable judge response
    is scored as incorrect with the raw output attached as the reason, so one
    flaky judge call doesn't crash the whole eval run.
    """
    user_msg = (
        f"Question: {question}\n\n"
        "Key facts the answer must contain:\n"
        + "\n".join(f"- {fact}" for fact in key_facts)
        + f"\n\nGenerated answer:\n{answer}"
    )
    try:
        response = judge_llm.invoke(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]
        )
        raw = response.content.strip()
    except Exception as e:  # network/API error -- don't crash the run over it
        return False, f"judge call failed: {type(e).__name__}: {e}"

    # The judge is asked not to wrap its output in a markdown fence, but
    # models don't always comply -- strip one defensively if present.
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        parsed = json.loads(raw)
        return bool(parsed.get("correct", False)), str(parsed.get("reason", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        return False, f"judge output unparseable: {raw[:200]!r}"


# --------------------------------------------------------------------------
# Per-question evaluation
# --------------------------------------------------------------------------


def _blank_row(item: dict) -> dict:
    return {field: "" for field in FIELDNAMES} | {
        "id": item["id"],
        "type": item["type"],
        "question": item["question"],
    }


def evaluate_question(item: dict, judge_llm: ChatOpenAI | None) -> dict:
    row = _blank_row(item)

    try:
        # Two calls to the SAME retrieval config (get_retriever() defaults to
        # rag.py's own K/SEARCH_TYPE) -- one for ranked docs (Recall@K/MRR
        # need rank order), one via answer_question() for the actual
        # generated answer + its deduped citation list. answer_question()'s
        # own RagResult.sources is re-sorted alphabetically by rag.py (for
        # display), which destroys the rank order MRR needs, so it can't be
        # reused for that -- hence the separate get_retriever() call. Both
        # calls are deterministic (temperature=0, same embeddings), so they
        # see identical retrieval results.
        docs = get_retriever().invoke(item["question"])
        rag_result = answer_question(item["question"])
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
        if item["type"] == "in_scope":
            row["retrieval_hit"] = False
            row["mrr"] = 0.0
            row["citation_recall_hit"] = False
            row["answer_correct"] = False
            row["judge_reason"] = "question errored before evaluation"
        else:
            row["refusal_correct"] = False
        return row

    row["answer"] = rag_result.answer
    row["num_chunks_retrieved"] = rag_result.num_chunks_retrieved
    row["cited_sources"] = "; ".join(format_citation(s) for s in rag_result.sources)

    if item["type"] == "in_scope":
        expected_source = item["expected_source"]
        expected_pages = item["expected_pages"]
        key_facts = item.get("key_facts", [])

        hit, mrr, hit_rank = score_retrieval(docs, expected_source, expected_pages)
        row["retrieval_hit"] = hit
        row["mrr"] = mrr
        row["hit_rank"] = hit_rank if hit_rank is not None else ""

        cite_recall_hit, cite_precision, num_cited, num_relevant = score_citations(
            rag_result.sources, expected_source
        )
        row["citation_recall_hit"] = cite_recall_hit
        row["citation_precision"] = cite_precision if cite_precision is not None else ""
        row["num_cited"] = num_cited
        row["num_relevant_cited"] = num_relevant

        # facts_in_context is retrieval-only (no judge needed) -- computed
        # regardless of --judge, since it's just a substring check against
        # what was actually retrieved.
        facts_in_context = score_fact_presence(docs, key_facts)
        row["facts_in_context"] = facts_in_context
        row["num_key_facts"] = len(key_facts)

        if judge_llm is not None:
            correct, reason = judge_answer(item["question"], key_facts, rag_result.answer, judge_llm)
            row["answer_correct"] = correct
            row["judge_reason"] = reason
            # Self-classifies the failure: incorrect AND a fact was missing
            # from context -> chunking/retrieval problem, no prompt can fix
            # it. Incorrect with all facts present -> generation problem,
            # the prompt/model is the thing to look at.
            row["fact_retrieval_gap"] = (not correct) and (facts_in_context < len(key_facts))
        else:
            row["answer_correct"] = ""
            row["judge_reason"] = "(judge not run -- pass --judge)"
            # Needs a correctness verdict to classify -- undetermined without --judge.
            row["fact_retrieval_gap"] = ""

    else:  # out_of_scope
        row["refusal_correct"] = rag_result.answer.strip() in _FALLBACK_RESPONSES

    return row


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None and v != ""]
    return (sum(values) / len(values)) if values else None


def compute_summary(rows: list[dict], judge_ran: bool) -> dict:
    in_scope = [r for r in rows if r["type"] == "in_scope"]
    out_scope = [r for r in rows if r["type"] == "out_of_scope"]

    recall_at_k = _mean([1.0 if r["retrieval_hit"] else 0.0 for r in in_scope]) if in_scope else None
    mean_mrr = _mean([r["mrr"] for r in in_scope]) if in_scope else None
    citation_recall = _mean([1.0 if r["citation_recall_hit"] else 0.0 for r in in_scope]) if in_scope else None
    # citation_precision is undefined (skipped, not zero) for questions where
    # nothing was cited at all -- see score_citations' docstring.
    citation_precision = _mean([r["citation_precision"] for r in in_scope]) if in_scope else None

    if judge_ran and in_scope:
        judged = [r for r in in_scope if r["answer_correct"] != ""]
        answer_correctness_rate = _mean([1.0 if r["answer_correct"] else 0.0 for r in judged]) if judged else None
    else:
        answer_correctness_rate = None

    refusal_accuracy = _mean([1.0 if r["refusal_correct"] else 0.0 for r in out_scope]) if out_scope else None
    hallucination_count = sum(1 for r in out_scope if not r["refusal_correct"])

    return {
        "num_in_scope": len(in_scope),
        "num_out_of_scope": len(out_scope),
        "k": K,
        "page_tolerance": PAGE_TOLERANCE,
        "judge_ran": judge_ran,
        "retrieval_recall_at_k": recall_at_k,
        "mean_mrr": mean_mrr,
        "citation_recall": citation_recall,
        "citation_precision": citation_precision,
        "answer_correctness_rate": answer_correctness_rate,
        "refusal_accuracy": refusal_accuracy,
        "hallucination_count": hallucination_count,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _fmt(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def print_table(rows: list[dict]) -> None:
    print("\n=== Per-question results ===")
    for r in rows:
        print(f"\n[{r['id']}] ({r['type']}) {r['question']}")
        if r["error"]:
            print(f"  ERROR: {r['error']}")
            continue
        if r["type"] == "in_scope":
            print(
                f"  retrieval_hit={_fmt(r['retrieval_hit'])}  hit_rank={_fmt(r['hit_rank'])}  "
                f"mrr={_fmt(r['mrr'])}"
            )
            print(
                f"  citation_recall={_fmt(r['citation_recall_hit'])}  "
                f"citation_precision={_fmt(r['citation_precision'])}  "
                f"({r['num_relevant_cited']}/{r['num_cited']} cited sources relevant)"
            )
            print(f"  facts_in_context={r['facts_in_context']}/{r['num_key_facts']}")
            # NOT routed through _fmt()'s PASS/FAIL bool mapping: for this
            # field True means "there IS a gap" (bad) and False means "no
            # gap" (good) -- the inverse of every other boolean here, where
            # True is the good outcome. PASS/FAIL would read backwards.
            gap_str = f"  fact_retrieval_gap={r['fact_retrieval_gap']}" if r["fact_retrieval_gap"] != "" else ""
            print(f"  answer_correct={_fmt(r['answer_correct'])}  ({r['judge_reason']}){gap_str}")
        else:
            print(f"  refusal_correct={_fmt(r['refusal_correct'])}")
        print(f"  cited: {r['cited_sources'] or '(none)'}")


def print_summary(summary: dict) -> None:
    print("\n=== Aggregate summary ===")
    print(f"Questions: {summary['num_in_scope']} in_scope, {summary['num_out_of_scope']} out_of_scope "
          f"(k={summary['k']}, page tolerance ±{summary['page_tolerance']})")
    print(f"Retrieval Recall@K:      {_fmt(summary['retrieval_recall_at_k'])}")
    print(f"Mean MRR:                {_fmt(summary['mean_mrr'])}")
    print(f"Citation recall:         {_fmt(summary['citation_recall'])}")
    print(f"Citation precision:      {_fmt(summary['citation_precision'])}")
    if summary["judge_ran"]:
        print(f"Answer correctness:     {_fmt(summary['answer_correctness_rate'])}")
    else:
        print("Answer correctness:      (skipped -- run with --judge)")
    print(f"Refusal accuracy:        {_fmt(summary['refusal_accuracy'])}")
    print(f"Hallucination count:     {summary['hallucination_count']} / {summary['num_out_of_scope']} out_of_scope questions")


def write_reports(rows: list[dict], summary: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS_DIR / "eval_results.csv"
    json_path = REPORTS_DIR / "eval_summary.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nWrote {csv_path}")
    print(f"Wrote {json_path}")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RAG evaluation harness.")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Also run the LLM-as-judge answer-correctness check (extra OpenAI calls, one per in_scope question).",
    )
    parser.add_argument(
        "--questions",
        default=str(Path(__file__).parent / "golden_questions.yaml"),
        help="Path to the golden question set YAML (default: eval/golden_questions.yaml).",
    )
    args = parser.parse_args()

    # This is a report, not a gate (per spec: exit code 0 always) -- so on a
    # missing key we print a clear error and return rather than raising.
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "ERROR: OPENAI_API_KEY is not set. Copy .env.example to .env and add "
            "your key -- the eval harness calls the same OpenAI-backed retrieval "
            "and generation the app uses, so it needs a real key.",
            file=sys.stderr,
        )
        return

    if store_is_empty():
        print(
            "WARNING: the vector store is empty (no PDFs ingested yet). Every "
            "in_scope question will fail retrieval, and every out_of_scope "
            "question will trivially 'pass' refusal. Run `uv run ingest.py` "
            "first for a meaningful report. Continuing anyway...",
            file=sys.stderr,
        )

    questions = load_questions(args.questions)
    if not questions:
        print(f"No usable questions found in {args.questions} -- nothing to evaluate. See eval/README.md.")
        write_reports([], compute_summary([], args.judge))
        return

    # temperature=0 + a fixed JUDGE_MODEL: see the determinism comment above
    # JUDGE_MODEL's definition -- this is what makes verdicts reproducible
    # run-to-run for the same pipeline output.
    judge_llm = ChatOpenAI(model=JUDGE_MODEL, temperature=0) if args.judge else None
    if args.judge:
        print(f"Running with --judge: answer correctness will be scored by {JUDGE_MODEL} (extra API calls).")

    # Each question makes 2-4 sequential network calls (retrieval, generation,
    # and a judge call when --judge is set), so a full run can take several
    # minutes -- print progress as we go rather than staying silent until the
    # very end, which otherwise looks indistinguishable from a hang.
    rows = []
    for i, item in enumerate(questions, start=1):
        print(f"[{i}/{len(questions)}] {item['id']}: {item['question']!r} ...", end=" ", flush=True)
        row = evaluate_question(item, judge_llm)
        rows.append(row)
        print("error" if row["error"] else "done", flush=True)

    print_table(rows)
    summary = compute_summary(rows, args.judge)
    print_summary(summary)
    write_reports(rows, summary)


if __name__ == "__main__":
    main()
    sys.exit(0)  # report, not a gate -- always exit clean, per spec
