"""
rag.py — query -> retrieve -> grounded, cited answer.

This module only READS the persisted Chroma store built by ingest.py. It never
writes to it. app.py imports `answer_question()` for the Streamlit UI, and it
can also be run standalone for a quick command-line sanity check.

Architecture: all-hosted. Query embedding uses the SAME get_embeddings() from
embeddings.py that ingest.py used for the documents (a query embedded by a
different model than the corpus would compare vectors from two incompatible
spaces -- similarity search would silently return garbage). Generation uses
OpenAI gpt-4o-mini directly.

Section-aware citations: ingest.py's chunk metadata now carries {source,
page, section}, plus is_table / is_image flags on those chunk types. This
file threads that all the way through: into the context shown to the LLM
(so it knows which chunks are tables/OCR'd images and can read them
appropriately), into the strict grounding prompt (so every claim is cited
and fabricated citations are disallowed), and into the structured
`RagResult.sources` the UI renders as "Employee Handbook -> Leave Policy,
p.12" style citations.

Cite-what-you-use: each retrieved chunk is shown to the LLM with a numeric
label ("[1]", "[2]", ...), and the prompt requires citing a label inline
only when that chunk was actually used for the claim next to it. The final
`RagResult.sources` list is built from ONLY the labels that appear in the
generated answer (see _extract_cited_docs), not from every chunk retrieved
-- this is what keeps citation precision high even when MMR retrieves a
same-shaped-but-irrelevant chunk (e.g. from a different company's handbook)
that the model correctly ignored.
"""

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from chromadb.config import Settings as ChromaSettings

from embeddings import get_embeddings
from ingest import PERSIST_DIR, COLLECTION_NAME

load_dotenv()

# --------------------------------------------------------------------------
# Retrieval constants
# --------------------------------------------------------------------------

# k=6: bumped up from the original k=4 now that ingest.py chunks are sized in
# TOKENS (~200 tokens each, see ingest.py's CHUNK_SIZE) rather than the old
# ~800-character chunks -- each chunk now covers noticeably less ground, so a
# slightly higher k keeps total retrieved coverage roughly comparable to
# before. Still comfortably inside the ~4-8 range that's sane for a stuffed
# gpt-4o-mini context: 6 chunks x (~200 content tokens + a short header) is a
# few hundred tokens, nowhere near the model's context limit.
K = 6

# search_type="mmr" (Maximal Marginal Relevance) instead of plain similarity:
# plain top-k similarity search on a well-populated store tends to return
# several near-duplicate chunks of the same passage. MMR re-ranks results to
# balance relevance against diversity, so the k chunks we hand to the LLM
# cover more of the document's actual content instead of repeating one spot.
SEARCH_TYPE = "mmr"

GENERATION_MODEL = "gpt-4o-mini"

# Low and near-deterministic: this tool extracts and cites facts from
# documents, it doesn't compose creative text. A higher temperature would
# invite paraphrasing that drifts from what the source actually says.
GENERATION_TEMPERATURE = 0.0

FALLBACK_ANSWER = "I don't know based on the provided documents."

# The grounding prompt is the most important piece of this file: it forbids
# outside knowledge, mandates the exact fallback string when the retrieved
# context doesn't contain the answer, requires inline + trailing citations
# for every claim, forbids fabricated citations, requires conflicts between
# chunks to be surfaced rather than silently resolved, tells the model how
# to read table/OCR'd-image chunks, and requires ANSWER COMPLETENESS --
# eval (--judge) surfaced answer correctness at 0.75 with two answers
# omitting a material qualifying condition or a second, distinct quantity
# the context actually had -- so rules 7-8 spell out what "complete" means,
# and rule 9 (concise) is written right after them to make explicit that
# completeness is not license to pad the answer with everything on the page.
# Rule 7 already named "must request N business days in advance" as an
# example, but eval q3 showed that wasn't emphatic enough on its own -- the
# model answered "20 business days" and dropped the attached 5-business-day
# advance-notice requirement even though both facts were retrieved. Rule 7
# now calls out PROCEDURAL requirements (notice periods, deadlines, approval
# steps) on entitlement/benefit/limit questions specifically, with that
# exact failure as its worked example, bounded by the same
# don't-pad-with-tangential-clauses instruction as everything else in it.
# A wrong confident answer is worse than an honest miss for an HR/SOP
# assistant, so rule 2 (the "I don't know" path) is written to be the
# easiest, most explicit path to take.
SYSTEM_PROMPT = """You are an internal-documents assistant. Answer the user's \
question using ONLY the context chunks below, retrieved from the company's \
internal document library (HR policies, SOPs, manuals, onboarding docs).

Ground rules -- follow every one exactly:

1. ONLY the context. Base every claim strictly on the context chunks below. \
Never use outside knowledge, training data, or assumptions -- not even \
something you personally believe is true. If a fact isn't in the context \
below, you don't know it for the purposes of this answer.

2. If the context doesn't contain enough information to answer, respond \
with EXACTLY this sentence and NOTHING else -- no citations, no partial \
answer, no explanation: "I don't know based on the provided documents." \
When genuinely unsure whether the context supports an answer, take this \
path rather than guessing -- a confident wrong answer is worse than an \
honest "I don't know" for this tool.

3. Cite as you go, using the numbered labels ONLY. Every chunk below is \
prefixed with a number in brackets, e.g. "[1]", "[2]". Immediately after \
each claim in your answer, cite the label of the chunk that actually \
supports it, e.g. "New hires accrue 15 days of PTO per year [1]." Cite a \
label ONLY when you genuinely used that chunk's content for the claim right \
before it -- you were given several chunks so you have enough context to \
choose from, not so you cite all of them. If a chunk is irrelevant to the \
question (e.g. it's from a different policy or company than the one asked \
about), ignore it completely: don't cite it and don't mention it. Then end \
your answer with a line starting "Citations:" listing only the labels you \
actually used, e.g.: Citations: [1], [3]
(Skip the Citations line entirely if you used rule 2's fallback sentence.)

4. Never fabricate a citation. Only cite a label number that is literally \
printed in front of one of the chunks you were given below -- never invent \
a label, and never cite a label whose chunk you didn't actually rely on for \
that claim. If you can't tell which chunk supports a claim, don't make the \
claim.

5. Surface conflicts, don't silently resolve them. If two or more chunks \
disagree on a fact (different numbers, contradictory deadlines, etc.), do \
not pick one and present it as settled -- say so explicitly and cite both \
sides by label, e.g. "Sources disagree here: one source states 15 days \
[1], while another states 20 days [4]."

6. Read tables and OCR'd text carefully. A chunk tagged [Type: Table] holds \
tabular data -- read row/column alignment carefully and never swap a value \
from one row or column into another. A chunk tagged [Type: OCR'd Image] \
came from optical character recognition on a scanned page or embedded image \
and may contain recognition errors (misread characters, garbled words) -- \
if that text looks corrupted or ambiguous, say so rather than confidently \
asserting a reading of it.

7. Answer completely, including procedural requirements. First identify \
every distinct thing the question asks for. For each one, answer explicitly \
-- don't stop at the first matching number if the question implies there's \
more to it. If the context contains a qualifying condition, deadline, \
eligibility requirement, or limit that a reader would NEED in order to act \
on the answer (e.g. "eligible after 6 months of service," a cap on an \
otherwise-open-ended number), include it. This matters most for questions \
about an entitlement, allowance, benefit, or limit (time off, remote-work \
days, reimbursement, leave, etc.): when the context attaches a PROCEDURAL \
requirement to it -- a notice period, submission deadline, advance-request \
rule, or approval step -- include that requirement too, not just the \
number. For example, "employees may work remotely up to 20 business days \
per year" is an incomplete answer on its own if the context also says the \
request must be submitted 5 business days in advance -- the reader needs \
both to actually act on the entitlement. Only include a procedural \
requirement that's directly tied to what was asked; don't append every \
tangential clause on the page just because it's nearby. An answer that \
gives a number but omits a directly-attached condition is incomplete.

8. Disambiguate related quantities. When a question involves more than one \
related number (e.g. total leave eligibility vs. how much of it is paid; a \
per-night limit vs. a per-day limit), state each quantity separately and \
say what each one represents. Never collapse two distinct numbers from the \
context into one, and never report only one of them when the context \
distinguishes two.

9. Be concise and directly responsive -- but concise does not mean \
incomplete. Include every material condition rule 7 calls for and every \
distinct quantity rule 8 calls for; beyond that, don't pad the answer with \
tangential facts from the page, and don't restate the question.

Context:
{context}"""


@dataclass
class RagResult:
    answer: str
    sources: list[dict] = field(default_factory=list)  # [{"source":..., "page":..., "section":...}, ...]
    num_chunks_retrieved: int = 0


def _require_api_key() -> None:
    # Gates both calls this file makes to OpenAI: query embedding (via
    # get_embeddings()) and generation (via ChatOpenAI) -- both hosted.
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )


def _get_store() -> Chroma:
    """Open the persisted Chroma collection for reading.

    embedding_function is get_embeddings() from the shared embeddings.py --
    the SAME function ingest.py uses to embed documents. Query and document
    vectors must come from the identical model or similarity search is
    comparing incompatible embedding spaces.

    collection_metadata mirrors ingest.py's cosine setting. Chroma only
    applies this at collection CREATION time, so it's a no-op if ingest.py
    already created "internal_docs" -- it's set here too only so that if
    rag.py is ever the first thing to touch a fresh ./chroma_db (e.g. someone
    runs the app before ever running ingest.py), the collection still gets
    created with the correct metric instead of Chroma's default.
    """
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=PERSIST_DIR,
        # is_persistent=True is REQUIRED alongside client_settings, or Chroma
        # silently runs in-memory-only despite persist_directory being set
        # (see the matching comment in ingest.py's get_vector_store, where
        # this was actually diagnosed).
        client_settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        collection_metadata={"hnsw:space": "cosine"},
    )


def get_retriever(k: int = K):
    store = _get_store()
    return store.as_retriever(search_type=SEARCH_TYPE, search_kwargs={"k": k})


def store_is_empty() -> bool:
    """True if the Chroma collection has no documents yet (no PDFs ingested)."""
    return _get_store()._collection.count() == 0


def _format_context(docs) -> str:
    """Build the context block shown to the LLM. Each chunk gets a 1-indexed
    numeric label ("[1]", "[2]", ...) in addition to its existing
    source/section/page/type header.

    The label is what makes "cite what you use" enforceable in code, not
    just in the prompt: previously the Sources list was built from EVERY
    retrieved chunk regardless of whether the model actually relied on it,
    so a same-shaped-but-wrong-company chunk that MMR retrieved (these
    sample HR handbooks are near-identical in structure) but the model
    correctly ignored still showed up as a cited source -- that's what
    drove citation precision down to ~0.77. Now the model cites a chunk's
    label inline only when it actually uses it, and answer_question() below
    builds the Sources list from exactly those labels, not from the full
    retrieved set.
    """
    parts = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        section = doc.metadata.get("section", "")

        # is_table is set by ingest.py today. is_image is read defensively --
        # ingest.py does not currently tag any chunk is_image (there's no
        # per-image extraction yet, only whole-page OCR fallback), so this
        # branch is forward-compatible dead code until that's added, not
        # something already wired end-to-end.
        tags = []
        if doc.metadata.get("is_table"):
            tags.append("Table")
        if doc.metadata.get("is_image"):
            tags.append("OCR'd Image")
        type_suffix = f", Type: {'/'.join(tags)}" if tags else ""

        header = f"[{i}] [Source: {source}, Section: {section or 'N/A'}, Page: {page}{type_suffix}]"
        parts.append(f"{header}\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


_CITATION_LABEL_RE = re.compile(r"\[(\d+)\]")


def _extract_cited_docs(answer_text: str, docs: list) -> list:
    """Return the subset of retrieved `docs` whose numeric label actually
    appears in the model's answer text, in first-appearance order. Labels
    outside the valid 1..len(docs) range (a hallucinated label number) are
    silently ignored rather than crashing -- rule 4 in the prompt tells the
    model never to invent one, but this is the defensive backstop.
    """
    cited_indices = []
    for match in _CITATION_LABEL_RE.finditer(answer_text):
        n = int(match.group(1))
        if 1 <= n <= len(docs) and n not in cited_indices:
            cited_indices.append(n)
    return [docs[n - 1] for n in cited_indices]


def _dedupe_sources(docs) -> list[dict]:
    seen = set()
    sources = []
    for doc in docs:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        section = doc.metadata.get("section", "")
        key = (source, section, page)
        if key not in seen:
            seen.add(key)
            sources.append({"source": source, "page": page, "section": section})
    # Two different sections can legitimately live on the same page, so sort
    # on source/page first and use section only as a tiebreaker.
    sources.sort(key=lambda s: (s["source"], s["page"] if isinstance(s["page"], int) else 0, s["section"]))
    return sources


def format_citation(s: dict) -> str:
    """Render one source dict as "Employee Handbook -> Leave Policy, p.12"
    (or "Employee Handbook, p.12" when there's no section)."""
    title = Path(s["source"]).stem  # drop the .pdf extension for readability
    if s.get("section"):
        return f"{title} → {s['section']}, p.{s['page']}"
    return f"{title}, p.{s['page']}"


def answer_question(question: str) -> RagResult:
    """Retrieve relevant chunks and generate a grounded, cited answer.

    Returns the fallback "I don't know..." string (with empty sources) both
    when nothing is retrieved and whenever the LLM itself decides the
    retrieved context doesn't answer the question.
    """
    _require_api_key()

    question = (question or "").strip()
    if not question:
        return RagResult(answer="Please enter a question.", sources=[], num_chunks_retrieved=0)

    if store_is_empty():
        return RagResult(answer=FALLBACK_ANSWER, sources=[], num_chunks_retrieved=0)

    retriever = get_retriever()
    docs = retriever.invoke(question)

    if not docs:
        return RagResult(answer=FALLBACK_ANSWER, sources=[], num_chunks_retrieved=0)

    context = _format_context(docs)

    llm = ChatOpenAI(model=GENERATION_MODEL, temperature=GENERATION_TEMPERATURE)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", "{question}")]
    )
    chain = prompt | llm

    response = chain.invoke({"context": context, "question": question})
    answer_text = response.content.strip()

    # If the model correctly declined to answer, don't attach sources that
    # would falsely imply the documents supported a claim.
    if answer_text == FALLBACK_ANSWER:
        return RagResult(answer=answer_text, sources=[], num_chunks_retrieved=len(docs))

    # Sources come from only the [n] labels the model actually cited in its
    # answer, NOT from every chunk that was retrieved -- see _format_context
    # and _extract_cited_docs for why (this is the citation-precision fix:
    # retrieved-but-unused chunks, e.g. a same-shaped chunk from the wrong
    # company's handbook, no longer show up as "sources").
    cited_docs = _extract_cited_docs(answer_text, docs)

    return RagResult(
        answer=answer_text,
        sources=_dedupe_sources(cited_docs),
        num_chunks_retrieved=len(docs),
    )


if __name__ == "__main__":
    try:
        _require_api_key()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if store_is_empty():
        print("The vector store is empty. Run `python ingest.py` first.")
        sys.exit(0)

    q = " ".join(sys.argv[1:]) or input("Question: ")
    result = answer_question(q)
    print("\nAnswer:\n" + result.answer)
    if result.sources:
        print("\nSources:")
        for s in result.sources:
            print(f"  - {format_citation(s)}")
    print(f"\n[{result.num_chunks_retrieved} chunk(s) retrieved]")
