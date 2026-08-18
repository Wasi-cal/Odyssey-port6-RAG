"""RagResult + answer_question(): retrieve relevant chunks and generate a
grounded, cited answer -- ties retrieval/store.py, retrieval/citations.py,
and retrieval/prompt.py together.
"""

from dataclasses import dataclass, field

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .. import config_store
from ..openai_key import require_openai_api_key
from .citations import dedupe_sources, extract_cited_docs, format_context
from .prompt import (
    FALLBACK_UNANSWERED,
    FALLBACK_UNCLEAR,
    FALLBACK_UNRELATED,
    GENERATION_MODEL,
    GENERATION_TEMPERATURE,
    SYSTEM_PROMPT,
)
from .store import get_retriever, store_is_empty


@dataclass
class RagResult:
    answer: str
    sources: list[dict] = field(default_factory=list)  # [{"source":..., "page":..., "section":..., "subsection":...}, ...]
    num_chunks_retrieved: int = 0


def answer_question(question: str) -> RagResult:
    """Retrieve relevant chunks and generate a grounded, cited answer.

    Returns one of three fallback strings (with empty sources), depending on
    why a grounded answer isn't possible: the question was unclear (asks the
    user to rephrase), unrelated to the document set (says so), or clear and
    in scope but genuinely uncovered by the documents (points the user at HR
    to escalate). The empty-store and nothing-retrieved cases below use the
    last of those, since there's no context for the LLM to classify against.

    The system prompt and these three strings, plus the generation
    model/temperature, are read fresh from config_store on every call (not
    at import time) -- that's what lets a direct Postgres edit to
    config_settings take effect on its own, without restarting this process.
    Each config_store.get() falls back to this module's own constant if the
    config subsystem is unreachable.
    """
    require_openai_api_key()

    system_prompt = config_store.get("generation", "system_prompt", SYSTEM_PROMPT)
    fallback_unclear = config_store.get("generation", "fallback_unclear", FALLBACK_UNCLEAR)
    fallback_unrelated = config_store.get("generation", "fallback_unrelated", FALLBACK_UNRELATED)
    fallback_unanswered = config_store.get(
        "generation", "fallback_unanswered", FALLBACK_UNANSWERED
    )
    generation_model = config_store.get("generation", "model", GENERATION_MODEL)
    generation_temperature = config_store.get("generation", "temperature", GENERATION_TEMPERATURE)

    question = (question or "").strip()
    if not question:
        return RagResult(answer="Please enter a question.", sources=[], num_chunks_retrieved=0)

    if store_is_empty():
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    retriever = get_retriever()
    docs = retriever.invoke(question)

    if not docs:
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    context = format_context(docs)

    llm = ChatOpenAI(model=generation_model, temperature=generation_temperature)
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{question}")]
    )
    chain = prompt | llm

    # The three fallback strings are interpolated into system_prompt's rule 2
    # (see prompt.py) so editing one of these config values updates both what
    # the model is told to say AND what this function compares its output
    # against below -- editing one without the other would otherwise silently
    # break the fallback-detection check.
    response = chain.invoke(
        {
            "context": context,
            "question": question,
            "fallback_unclear": fallback_unclear,
            "fallback_unrelated": fallback_unrelated,
            "fallback_unanswered": fallback_unanswered,
        }
    )
    answer_text = response.content.strip()

    # If the model correctly declined to answer (any of the three fallback
    # paths), don't attach sources that would falsely imply the documents
    # supported a claim.
    if answer_text in (fallback_unclear, fallback_unrelated, fallback_unanswered):
        return RagResult(answer=answer_text, sources=[], num_chunks_retrieved=len(docs))

    # Sources come from only the [n] labels the model actually cited in its
    # answer, NOT from every chunk that was retrieved -- see format_context
    # and extract_cited_docs for why (this is the citation-precision fix:
    # retrieved-but-unused chunks, e.g. a same-shaped chunk from the wrong
    # company's handbook, no longer show up as "sources").
    cited_docs = extract_cited_docs(answer_text, docs)

    return RagResult(
        answer=answer_text,
        sources=dedupe_sources(cited_docs),
        num_chunks_retrieved=len(docs),
    )
