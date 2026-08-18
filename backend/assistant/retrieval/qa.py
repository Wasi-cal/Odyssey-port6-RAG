"""RagResult + answer_question(): retrieve relevant chunks and generate a
grounded, cited answer -- ties retrieval/store.py, retrieval/citations.py,
and retrieval/prompt.py together.
"""

from dataclasses import dataclass, field

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from ..openai_key import require_openai_api_key
from .citations import dedupe_sources, extract_cited_docs, format_context
from .prompt import FALLBACK_ANSWER, GENERATION_MODEL, GENERATION_TEMPERATURE, SYSTEM_PROMPT
from .store import get_retriever, store_is_empty


@dataclass
class RagResult:
    answer: str
    sources: list[dict] = field(default_factory=list)  # [{"source":..., "page":..., "section":..., "subsection":...}, ...]
    num_chunks_retrieved: int = 0


def answer_question(question: str) -> RagResult:
    """Retrieve relevant chunks and generate a grounded, cited answer.

    Returns the fallback "I don't know..." string (with empty sources) both
    when nothing is retrieved and whenever the LLM itself decides the
    retrieved context doesn't answer the question.
    """
    require_openai_api_key()

    question = (question or "").strip()
    if not question:
        return RagResult(answer="Please enter a question.", sources=[], num_chunks_retrieved=0)

    if store_is_empty():
        return RagResult(answer=FALLBACK_ANSWER, sources=[], num_chunks_retrieved=0)

    retriever = get_retriever()
    docs = retriever.invoke(question)

    if not docs:
        return RagResult(answer=FALLBACK_ANSWER, sources=[], num_chunks_retrieved=0)

    context = format_context(docs)

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
