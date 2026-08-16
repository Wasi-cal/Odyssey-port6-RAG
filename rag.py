"""
rag.py — query -> retrieve -> grounded, cited answer.

This module only READS the persisted Chroma store built by ingest.py. It never
writes to it. app.py imports `answer_question()` for the Streamlit UI, and it
can also be run standalone for a quick command-line sanity check.
"""

import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from chromadb.config import Settings as ChromaSettings

from ingest import PERSIST_DIR, COLLECTION_NAME, EMBEDDING_MODEL

load_dotenv()

# --------------------------------------------------------------------------
# Retrieval constants
# --------------------------------------------------------------------------

# k=4: enough retrieved chunks to cover a multi-part answer without flooding
# the prompt with marginally-relevant text that could dilute grounding.
K = 4

# search_type="mmr" (Maximal Marginal Relevance) instead of plain similarity:
# plain top-k similarity search on a well-populated store tends to return
# several near-duplicate chunks of the same passage. MMR re-ranks results to
# balance relevance against diversity, so the k chunks we hand to the LLM
# cover more of the document's actual content instead of repeating one spot.
SEARCH_TYPE = "mmr"

GENERATION_MODEL = "gpt-4o-mini"

FALLBACK_ANSWER = "I don't know based on the provided documents."

# The grounding prompt is the most important piece of this file: it forbids
# outside knowledge and mandates the exact fallback string when the retrieved
# context doesn't contain the answer, so the assistant never hallucinates.
SYSTEM_PROMPT = """You are an internal-documents assistant. Answer the user's \
question using ONLY the context below, which was retrieved from the \
company's internal PDF library (HR policies, SOPs, manuals, onboarding docs).

Rules you must follow exactly:
1. Base every claim in your answer strictly on the provided context. Never \
use outside knowledge, training data, or assumptions, even if you believe \
you know the answer.
2. If the context does not contain enough information to answer the \
question, respond with EXACTLY this sentence and nothing else: \
"I don't know based on the provided documents."
3. Do not mention "the context" or "the documents" explicitly in your \
answer (e.g. do not say "According to the context...") — just answer \
naturally as if you already knew the policy. Do not fabricate sources, \
page numbers, or details beyond what is given.
4. Keep the answer concise and directly responsive to the question.

Context:
{context}"""


@dataclass
class RagResult:
    answer: str
    sources: list[dict] = field(default_factory=list)  # [{"source": ..., "page": ...}, ...]
    num_chunks_retrieved: int = 0


def _require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )


def _get_store() -> Chroma:
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIR,
        client_settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_retriever(k: int = K):
    store = _get_store()
    return store.as_retriever(search_type=SEARCH_TYPE, search_kwargs={"k": k})


def store_is_empty() -> bool:
    """True if the Chroma collection has no documents yet (no PDFs ingested)."""
    return _get_store()._collection.count() == 0


def _format_context(docs) -> str:
    parts = []
    for doc in docs:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        parts.append(f"[Source: {source}, Page: {page}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


def _dedupe_sources(docs) -> list[dict]:
    seen = set()
    sources = []
    for doc in docs:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        key = (source, page)
        if key not in seen:
            seen.add(key)
            sources.append({"source": source, "page": page})
    # Stable, readable ordering: by document name, then page number.
    sources.sort(key=lambda s: (s["source"], s["page"] if isinstance(s["page"], int) else 0))
    return sources


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

    llm = ChatOpenAI(model=GENERATION_MODEL, temperature=0)
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

    return RagResult(
        answer=answer_text,
        sources=_dedupe_sources(docs),
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
            print(f"  - {s['source']} (page {s['page']})")
    print(f"\n[{result.num_chunks_retrieved} chunk(s) retrieved]")
