"""RagResult + answer_question(): retrieve relevant chunks and generate a
grounded, cited answer -- ties retrieval/store.py, retrieval/citations.py,
and retrieval/prompt.py together.
"""

import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from openai import OpenAI

from .. import config_store
from ..openai_key import require_openai_api_key
from ..paths import DATA_DIR
from .citations import dedupe_sources, extract_cited_docs, format_context
from .prompt import (
    FALLBACK_ABUSE,
    FALLBACK_DANGEROUS,
    FALLBACK_GIBBERISH,
    FALLBACK_GREETING,
    FALLBACK_HANDOFF,
    FALLBACK_UNANSWERED,
    FALLBACK_UNCLEAR,
    FALLBACK_UNRELATED,
    GENERATION_MODEL,
    GENERATION_TEMPERATURE,
    INJECTION_DEFENSE_PREAMBLE,
    SYSTEM_PROMPT,
)
from .store import get_retriever, store_is_empty


@dataclass
class RagResult:
    answer: str
    sources: list[dict] = field(default_factory=list)  # [{"source":..., "page":..., "section":..., "subsection":...}, ...]
    num_chunks_retrieved: int = 0
    title: str | None = None  # a short chat-session title, from the same LLM call -- None if none was generated (e.g. the empty-store/no-docs early returns below, which never call the LLM)
    # Token usage from the generation call, for the admin monitoring
    # dashboard's cost/usage figures -- all None for the early-return paths
    # below that never call the LLM at all (abuse/list-documents/empty-store/
    # nothing-retrieved), since there's no cost to attribute to those.
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


# Matches system_prompt's "TITLE: ...\nANSWER: ..." envelope (see prompt.py)
# -- DOTALL so ANSWER's captured group can span the answer's own newlines
# (multi-paragraph answers, bulleted lists, a trailing "Citations:" line).
_TITLE_ANSWER_RE = re.compile(r"TITLE:\s*(.*?)\s*\n+ANSWER:\s*(.*)", re.DOTALL)

# Status text handed to the model as "Previous title: ..." on a session's
# first message (see the invoke() call below) -- system_prompt tells it this
# is never a value to echo, but a plain greeting with nothing else to name
# has occasionally come back verbatim anyway. _split_title_and_answer
# catches that as a defensive backstop, not just a prompt instruction.
_NO_PREVIOUS_TITLE = "(none yet -- this is the first message)"

# Fallback only -- live value is config_settings' generation/history_messages
# (see config_store.seed_defaults). Counts messages (user + assistant), not
# turns, so this is ~3 back-and-forth exchanges by default.
_HISTORY_MESSAGES_DEFAULT = 12
# Each prior message is truncated to this many characters before being handed
# back to the model -- a single very long past answer (this tool's answers
# can run long, see prompt.py's completeness rules) shouldn't be able to
# balloon every subsequent call's prompt size just by having happened once.
_HISTORY_MESSAGE_MAX_CHARS = 1000


def _build_history_messages(chat_history: list[dict] | None) -> list:
    """Turns [{"role": "user"|"assistant", "content": str}, ...] (oldest
    first, as api.py reads them from db.get_messages) into LangChain message
    objects for MessagesPlaceholder("chat_history") below -- this is what
    lets the model resolve a follow-up question ("what about part-time
    employees?") against what was actually discussed earlier in the same
    session, instead of treating every question as if it were the first.
    Retrieval itself still only searches on the current question's text;
    only the generation call sees prior turns.
    """
    limit = config_store.get("generation", "history_messages", _HISTORY_MESSAGES_DEFAULT)
    trimmed = (chat_history or [])[-limit:] if limit > 0 else []
    messages = []
    for m in trimmed:
        content = (m.get("content") or "")[:_HISTORY_MESSAGE_MAX_CHARS]
        cls = HumanMessage if m.get("role") == "user" else AIMessage
        messages.append(cls(content=content))
    return messages


def _split_title_and_answer(raw_text: str) -> tuple[str | None, str]:
    """Splits the model's "TITLE: ...\\nANSWER: ..." response into (title,
    answer). Falls back to (None, raw_text) if the model ever doesn't follow
    that format, so a formatting slip degrades to "no title this time"
    rather than showing the user a garbled "TITLE: ..." response.
    """
    match = _TITLE_ANSWER_RE.match(raw_text.strip())
    if not match:
        return None, raw_text.strip()
    title, answer = match.groups()
    title = title.strip()
    if not title or title == _NO_PREVIOUS_TITLE:
        title = None
    return title, answer.strip()


def _list_documents_answer() -> str:
    """Builds the real "here's what I have access to" answer -- the actual
    current filenames on disk (the same set Chroma's chunks are drawn from),
    not something the LLM tries to recall on its own.
    """
    names = sorted(p.name for p in DATA_DIR.glob("*.pdf"))
    if not names:
        return "I don't have any documents available right now."
    listing = "\n".join(f"- {name}" for name in names)
    return f"I have access to the following documents:\n\n{listing}"


# Deliberately NOT an LLM classification (see prompt.py's docstring for why:
# gpt-4o-mini kept pattern-matching "what leave policies do you have" onto
# this despite two rounds of explicit prompt instructions to the contrary).
# This only needs to catch questions about the file/document system itself
# -- keep it narrow. A question that happens to also name a policy topic
# (e.g. "what leave documents do you have") is rare enough, and still
# fundamentally a documents question, that matching it here is fine.
_LIST_DOCUMENTS_PHRASES = (
    "what documents",
    "what files",
    "which documents",
    "which files",
    "how many documents",
    "how many files",
    "how many pdfs",
    "what pdfs",
    "which pdfs",
    "list documents",
    "list files",
    "list the documents",
    "list the files",
    "your knowledge base",
    "in your library",
    "documents do you have",
    "files do you have",
)


def _is_list_documents_question(question: str) -> bool:
    q = question.lower()
    return any(phrase in q for phrase in _LIST_DOCUMENTS_PHRASES)


def _is_abusive(question: str) -> bool:
    """OpenAI's Moderation API, not the generation model's own judgment --
    a purpose-built, separately-trained classifier for harassment/hate/
    sexual/violent content is meaningfully more reliable against adversarial
    input than asking gpt-4o-mini to police itself in the same prompt that
    also has to produce the actual answer. It's a small, fast, cheap
    classification call, not a second generation call.

    Fails OPEN (returns False -- lets the question through) if the
    moderation call itself errors: for this internal HR tool, a real
    question failing because a third-party classifier hiccuped is worse
    than the rare abusive message getting through to a fixed, harmless
    refusal path anyway once it reaches rule 2 or generation.
    """
    try:
        result = OpenAI().moderations.create(input=question)
        return bool(result.results[0].flagged)
    except Exception:
        return False


def answer_question(
    question: str,
    previous_title: str | None = None,
    chat_history: list[dict] | None = None,
) -> RagResult:
    """Retrieve relevant chunks and generate a grounded, cited answer.

    chat_history (oldest first, [{"role": "user"|"assistant", "content": str}, ...],
    as api.py reads them from db.get_messages before adding the new question)
    is given to the generation model as prior turns -- see
    _build_history_messages -- so it can resolve a follow-up question
    against what was actually discussed earlier, e.g. "what about part-time
    employees?" after a question about full-time PTO. Retrieval is
    unaffected: it still searches on only the current question's text.

    Returns one of several fixed responses (with empty sources) instead of a
    grounded content answer when one isn't appropriate. Two of these are
    caught before the LLM is ever called: abusive/harassing input (see
    _is_abusive, an OpenAI Moderation API call) and "what documents do you
    have" (see _is_list_documents_question, a plain keyword check -- gets
    the real current library). The rest are the generation model's own
    judgment, made in the same call that also tries to answer: a
    greeting/small talk gets a friendly intro, a request for a human gets
    pointed at HR, gibberish gets asked to be retyped, a real-but-vague
    question asks the user to rephrase, an unrelated one says so, and a
    clear-but-uncovered one points the user at HR to escalate. The
    empty-store and nothing-retrieved cases below use the last of those,
    since there's no context for the LLM to classify against.

    The system prompt and these fixed strings, plus the generation
    model/temperature, are read fresh from config_store on every call (not
    at import time) -- that's what lets a direct Postgres edit to
    config_settings take effect on its own, without restarting this process.
    Each config_store.get() falls back to this module's own constant if the
    config subsystem is unreachable.

    RagResult.title comes from the same LLM call, not a second dedicated
    one -- system_prompt asks for a short "TITLE: ...\nANSWER: ..." envelope
    on every response, and _split_title_and_answer pulls the two apart
    before anything else here runs. previous_title (the session's current
    title, or None on its first message) is handed back to the model so it
    can keep, refine, or broaden it as the conversation actually evolves,
    instead of the title being frozen at whatever the first message alone
    suggested -- api.py is what calls this on every /ask, not just the
    first. RagResult.title is None for the empty-store and nothing-
    retrieved cases below, since those never call the LLM at all -- api.py
    falls back to its own naive truncation of the question in that case
    (only when there's no previous_title yet to just keep instead).
    """
    require_openai_api_key()

    system_prompt = config_store.get("generation", "system_prompt", SYSTEM_PROMPT)
    fallback_greeting = config_store.get("generation", "fallback_greeting", FALLBACK_GREETING)
    fallback_handoff = config_store.get("generation", "fallback_handoff", FALLBACK_HANDOFF)
    fallback_unclear = config_store.get("generation", "fallback_unclear", FALLBACK_UNCLEAR)
    fallback_gibberish = config_store.get("generation", "fallback_gibberish", FALLBACK_GIBBERISH)
    fallback_unrelated = config_store.get("generation", "fallback_unrelated", FALLBACK_UNRELATED)
    fallback_unanswered = config_store.get(
        "generation", "fallback_unanswered", FALLBACK_UNANSWERED
    )
    fallback_abuse = config_store.get("generation", "fallback_abuse", FALLBACK_ABUSE)
    fallback_dangerous = config_store.get("generation", "fallback_dangerous", FALLBACK_DANGEROUS)
    generation_model = config_store.get("generation", "model", GENERATION_MODEL)
    generation_temperature = config_store.get("generation", "temperature", GENERATION_TEMPERATURE)

    question = (question or "").strip()
    if not question:
        return RagResult(answer="Please enter a question.", sources=[], num_chunks_retrieved=0)

    if _is_abusive(question):
        return RagResult(answer=fallback_abuse, sources=[], num_chunks_retrieved=0)

    if _is_list_documents_question(question):
        return RagResult(answer=_list_documents_answer(), sources=[], num_chunks_retrieved=0)

    if store_is_empty():
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    retriever = get_retriever()
    docs = retriever.invoke(question)

    if not docs:
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    context = format_context(docs)

    llm = ChatOpenAI(model=generation_model, temperature=generation_temperature)
    # INJECTION_DEFENSE_PREAMBLE always goes first, ahead of the
    # config-editable system_prompt -- see prompt.py's docstring for why
    # it's a separate, non-editable constant rather than folded into
    # SYSTEM_PROMPT itself.
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", INJECTION_DEFENSE_PREAMBLE + system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{question}"),
        ]
    )
    chain = prompt | llm

    # These fixed strings are interpolated into system_prompt's rule 2 (see
    # prompt.py) so editing one of these config values updates both what the
    # model is told to say AND what this function compares its output
    # against below -- editing one without the other would otherwise
    # silently break the fallback-detection check.
    response = chain.invoke(
        {
            "chat_history": _build_history_messages(chat_history),
            "context": context,
            "question": question,
            "previous_title": previous_title or _NO_PREVIOUS_TITLE,
            "fallback_greeting": fallback_greeting,
            "fallback_handoff": fallback_handoff,
            "fallback_unclear": fallback_unclear,
            "fallback_gibberish": fallback_gibberish,
            "fallback_unrelated": fallback_unrelated,
            "fallback_unanswered": fallback_unanswered,
            "fallback_dangerous": fallback_dangerous,
        }
    )
    title, answer_text = _split_title_and_answer(response.content)

    # LangChain's ChatOpenAI populates usage_metadata on every AIMessage --
    # a standardized {"input_tokens", "output_tokens", "total_tokens"} dict,
    # not OpenAI's own prompt_tokens/completion_tokens naming, but the same
    # figures. Missing entirely only if a future model/provider swap doesn't
    # support it; api.py treats total_tokens=None as "nothing to log".
    usage = getattr(response, "usage_metadata", None) or {}
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")

    # If the model correctly declined to answer (any of the fixed-response
    # paths), don't attach sources that would falsely imply the documents
    # supported a claim.
    if answer_text in (
        fallback_greeting,
        fallback_handoff,
        fallback_gibberish,
        fallback_unclear,
        fallback_unrelated,
        fallback_unanswered,
        fallback_dangerous,
    ):
        return RagResult(
            answer=answer_text,
            sources=[],
            num_chunks_retrieved=len(docs),
            title=title,
            model=generation_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

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
        title=title,
        model=generation_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
