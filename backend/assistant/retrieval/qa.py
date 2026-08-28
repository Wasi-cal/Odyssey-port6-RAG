"""RagResult + answer_question(): retrieve relevant chunks and generate a
grounded, cited answer -- ties retrieval/store.py, retrieval/citations.py,
and retrieval/prompt.py together.
"""

import asyncio
import re
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from openai import OpenAI

from .. import config_store
from ..leave_facts import (
    build_stated_balance_fact,
    compute_leave_ceiling,
    context_has_leave_policy,
    detect_stated_balance,
    is_ceiling_bucket,
)
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
    VOICE_SYSTEM_PROMPT,
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


# Matches system_prompt's "TITLE: ...\nANSWER: ...\nCitations: ..." envelope
# (see prompt.py's output_contract) -- DOTALL so ANSWER's captured group can
# span the answer's own newlines (multi-paragraph answers, bulleted lists).
# Citations is now its OWN group (the prompt mandates a "Citations:" line on
# every response, including fallbacks) so `answer` is just the ANSWER body,
# not ANSWER-plus-a-trailing-Citations-line -- that split matters because
# the fallback-string equality check below (`answer_text in (fallback_x,
# ...)`) needs the bare fallback text, not that text with "\nCitations:"
# stuck on the end. ANSWER's `(.*)` is greedy (not `.*?`): with DOTALL that
# naturally backtracks to the LAST "\nCitations:" in the string, which is
# what we want -- the actual final citations line, not any citation-like
# substring earlier in a multi-paragraph answer.
_TITLE_ANSWER_CITATIONS_RE = re.compile(
    r"TITLE:\s*(.*?)\s*\nANSWER:\s*(.*)\nCitations:\s*(.*)", re.DOTALL
)
# Older two-group shape, tried only if the three-group match above fails --
# keeps a malformed-but-still-parseable response (model forgot the
# Citations line entirely) from degrading all the way to "no title, show
# the raw text," same graceful-degradation intent as before.
_TITLE_ANSWER_RE = re.compile(r"TITLE:\s*(.*?)\s*\n+ANSWER:\s*(.*)", re.DOTALL)

# Status text handed to the model as the <previous_title> input on a
# session's first message (see the invoke() call below) -- title_rules in
# prompt.py explicitly checks for the literal string "None" ("use 'New
# Conversation' when <previous_title> is 'None' or empty"), so this must
# match that exactly, not a descriptive sentence. _split_title_and_answer's
# defensive check below catches the rare case where the model echoes it
# back as the title anyway.
_NO_PREVIOUS_TITLE = "None"

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
    Retrieval itself still only searches on the current question's text --
    a history-aware query rewrite was tried and reverted (see git history):
    diagnosis on the actual failure this was meant to fix (a "can I take 12
    this month" follow-up not getting an answer) showed the right chunk was
    already coming back on the raw question text alone, at k=10 -- the real
    bug was rule 2(f) treating "no literal number/timeframe match" as
    "context doesn't contain the answer" (see prompt.py's rule 7 addition on
    comparison questions). The extra condense call added a full LLM
    round-trip to every follow-up for a retrieval failure that wasn't
    actually happening, and its added latency contributed to autorefresh
    timing out in-flight /ask calls (see application.py's git history).
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
    """Splits the model's "TITLE: ...\\nANSWER: ...\\nCitations: ..." envelope
    into (title, answer) -- the Citations line itself is discarded here;
    extract_cited_docs (called later in answer_question) finds citation
    labels from the inline "[n]" markers in the answer body, which is a
    superset of what the trailing Citations line lists anyway.

    Tries the three-group TITLE/ANSWER/Citations shape first, falls back to
    the older two-group TITLE/ANSWER shape (no Citations line) if that
    doesn't match, and only falls back to (None, raw_text) if neither does
    -- three levels of graceful degradation so a formatting slip never
    shows the user a garbled "TITLE: ..." response.
    """
    raw_text = raw_text.strip()
    match = _TITLE_ANSWER_CITATIONS_RE.match(raw_text)
    if match:
        title, answer, _citations = match.groups()
    else:
        match = _TITLE_ANSWER_RE.match(raw_text)
        if not match:
            return None, raw_text
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


# Deliberately conservative, filename-driven document-name detection -- NOT
# an LLM classification (same reasoning as _is_list_documents_question
# above: this needs to be cheap and predictable, not a judgment call). The
# canonical document list is read fresh from DATA_DIR (the same source
# _list_documents_answer() already uses), never a separately maintained
# list, so it can't drift out of sync with what's actually ingested.
#
# A filename is reduced to its "core" (extension, version tokens like
# "Ver1.0"/"v4"/a bare year/a bare decimal version, and the company name
# "Calfus" all stripped) and only fires when that core phrase appears as a
# whole, contiguous, word-bounded run of text in the question -- e.g.
# "Communication Policy_Ver1.0.pdf" -> "communication policy", matched
# against "Under the Communication Policy specifically...". This is
# deliberately narrow: a question naming a document colloquially (e.g. "the
# Performance Appraisal Policy" when the real file is "...& Promotion
# Policy") or naming two documents at once (e.g. "the standalone Employee
# Referral Policy (not the Employee Handbook)", which superficially matches
# "employee handbook" too via the word "Handbook") won't fire -- multiple or
# zero matches both fall back to today's unfiltered retrieval unchanged,
# per the explicit "if ambiguous, don't filter" requirement this was built
# against. False negatives (a real single-document question that doesn't
# get detected) are an accepted tradeoff for never risking a false positive
# that would wrongly exclude a document a cross-document question actually
# needs.
_VER_TOKEN_RE = re.compile(r"\bver\.?\s*\d+(?:\.\d+)*\b")
_BARE_V_VERSION_RE = re.compile(r"\bv\d+(?:\.\d+)*\b")
_BARE_YEAR_RE = re.compile(r"\b\d{4}\b")
_BARE_DECIMAL_VERSION_RE = re.compile(r"\b\d+\.\d+\b")
_CALFUS_RE = re.compile(r"\bcalfus\b")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalize_doc_name(text: str) -> str:
    text = text.lower()
    if text.endswith(".pdf"):
        text = text[:-4]
    text = text.replace("&", " and ")
    text = text.replace("-", " ").replace("_", " ")
    text = _VER_TOKEN_RE.sub(" ", text)
    text = _BARE_V_VERSION_RE.sub(" ", text)
    text = _BARE_YEAR_RE.sub(" ", text)
    text = _BARE_DECIMAL_VERSION_RE.sub(" ", text)
    text = _CALFUS_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    return " ".join(text.split())


def _detect_named_document(question: str) -> str | None:
    """Returns the filename of the ONE document the question confidently,
    unambiguously names, or None if it names zero or more than one --
    None means "use today's existing unfiltered retrieval," never a guess.
    """
    normalized_question = _normalize_doc_name(question)
    if not normalized_question:
        return None
    filenames = sorted(p.name for p in DATA_DIR.glob("*.pdf"))
    matches = [
        filename
        for filename in filenames
        if (core := _normalize_doc_name(filename)) and re.search(rf"\b{re.escape(core)}\b", normalized_question)
    ]
    return matches[0] if len(matches) == 1 else None


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
    grounded content answer when one isn't appropriate. Abusive/harassing
    input (see _is_abusive, an OpenAI Moderation API call) always wins over
    any other result, but no longer GATES the rest of the pipeline the way
    it reads it might from the code shape below -- moderation and
    _generate_answer (list-documents / empty-store / retrieval / generation)
    now run CONCURRENTLY (see _run_moderation_and_generation), each in its
    own thread, joined with asyncio.gather. Moderation's result is only
    consulted right before this function returns: if it flagged the
    question, the generated answer -- list-documents answer, retrieved-and-
    generated answer, whatever _generate_answer produced -- is discarded and
    fallback_abuse is returned instead. This means an abusive question still
    always reaches the caller as a refusal, never a real answer (same safety
    behavior as before), it's just checked at the end instead of gating when
    generation starts -- so a normal, non-abusive question no longer pays
    moderation's network latency serially in front of retrieval+generation.
    "What documents do you have" (see _is_list_documents_question, a plain
    keyword check -- gets the real current library) is one of
    _generate_answer's own early returns. The rest are the generation
    model's own judgment, made in the same call that also tries to answer: a
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

    # Moderation and the rest of the pipeline now run CONCURRENTLY (see
    # _run_moderation_and_generation / _generate_answer below) instead of
    # moderation gating everything that follows -- moderation's result is
    # awaited only once _generate_answer's result is already in hand, right
    # here, before this function returns.
    abusive, result = asyncio.run(
        _run_moderation_and_generation(
            question,
            previous_title,
            chat_history,
            system_prompt,
            fallback_greeting,
            fallback_handoff,
            fallback_unclear,
            fallback_gibberish,
            fallback_unrelated,
            fallback_unanswered,
            fallback_dangerous,
            generation_model,
            generation_temperature,
        )
    )
    if abusive:
        return RagResult(answer=fallback_abuse, sources=[], num_chunks_retrieved=0)
    return result


async def _run_moderation_and_generation(
    question: str,
    previous_title: str | None,
    chat_history: list[dict] | None,
    system_prompt: str,
    fallback_greeting: str,
    fallback_handoff: str,
    fallback_unclear: str,
    fallback_gibberish: str,
    fallback_unrelated: str,
    fallback_unanswered: str,
    fallback_dangerous: str,
    generation_model: str,
    generation_temperature: float,
) -> tuple[bool, "RagResult"]:
    """Runs _is_abusive(question) (moderation) and _generate_answer(...)
    (list-documents / empty-store / retrieval / generation) concurrently,
    each in its own thread via asyncio.to_thread, joined with
    asyncio.gather -- this codebase's existing async-concurrency pattern for
    running blocking I/O side by side (see
    assistant/orchestration/workflows/ingestion_workflow.py's
    IngestDocumentsWorkflow.run, which gathers one activity per file the
    same way). Moderation used to gate _generate_answer from starting at
    all; now it runs alongside the full retrieval->generation pipeline, not
    just alongside retrieval, and answer_question() is the one that decides
    which of the two results to actually return.
    """
    return await asyncio.gather(
        asyncio.to_thread(_is_abusive, question),
        asyncio.to_thread(
            _generate_answer,
            question,
            previous_title,
            chat_history,
            system_prompt,
            fallback_greeting,
            fallback_handoff,
            fallback_unclear,
            fallback_gibberish,
            fallback_unrelated,
            fallback_unanswered,
            fallback_dangerous,
            generation_model,
            generation_temperature,
        ),
    )


def _generate_answer(
    question: str,
    previous_title: str | None,
    chat_history: list[dict] | None,
    system_prompt: str,
    fallback_greeting: str,
    fallback_handoff: str,
    fallback_unclear: str,
    fallback_gibberish: str,
    fallback_unrelated: str,
    fallback_unanswered: str,
    fallback_dangerous: str,
    generation_model: str,
    generation_temperature: float,
) -> RagResult:
    """Everything answer_question() used to do AFTER its (now-removed)
    inline `if _is_abusive(question): return ...` gate -- retrieval,
    chunking, the prompt, and citation logic here are byte-for-byte
    unchanged from before this function was split out; only moderation's
    place in the control flow moved (see _run_moderation_and_generation).
    """
    if _is_list_documents_question(question):
        return RagResult(answer=_list_documents_answer(), sources=[], num_chunks_retrieved=0)

    if store_is_empty():
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    history_messages = _build_history_messages(chat_history)

    # If the question confidently, unambiguously names one specific document
    # (see _detect_named_document), constrain retrieval to that document's
    # chunks only via a Chroma metadata filter on "source" -- the same field
    # every chunk's citation/dedup logic already keys off (citations.py).
    # None (no confident single match) falls through to unfiltered retrieval,
    # identical to today's behavior.
    named_document = _detect_named_document(question)
    retriever = get_retriever(where={"source": named_document} if named_document else None)
    docs = retriever.invoke(question)

    if not docs:
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    # GOAL-ORIENTED ADVISORY support (see prompt.py's <goal_oriented_advisory>
    # and leave_facts.py's module docstring): there's no query-intent
    # classifier for "this is an advisory goal, not a lookup" yet, so this is
    # the simplest thing that works -- whenever retrieval already surfaced
    # the Leave Policy page on its own (i.e. the question was leave-related
    # regardless of phrasing), also hand the model the pre-computed,
    # hardcoded ceiling as one more numbered, citable context chunk. This
    # replaces asking the model to derive that number itself every time,
    # which it did unreliably (see leave_facts.py).
    #
    # If the employee's own message states their remaining balance for a
    # bucket that WOULD have contributed to that generic ceiling (e.g. "I
    # only have 15 earned leave days left"), inject a scenario-specific fact
    # for that bucket instead of the generic one -- the model then never
    # sees both the generic default (21) and the stated number (15) in
    # context at once, so there's nothing to reconcile or accidentally
    # state side by side (see git history: asking it to resolve that
    # conflict itself was unreliable, same failure shape as the ceiling
    # arithmetic this whole module replaces). A stated balance for a bucket
    # OUTSIDE the generic ceiling (e.g. a stated Sick Leave balance) doesn't
    # affect it -- the generic ceiling still applies unmodified.
    if context_has_leave_policy(docs):
        stated = detect_stated_balance(question)
        if stated and is_ceiling_bucket(stated["bucket"]):
            fact_content = build_stated_balance_fact(stated["bucket"], stated["stated_amount"])
        else:
            fact_content = compute_leave_ceiling().fact_string

        docs = docs + [
            Document(
                page_content=fact_content,
                metadata={
                    "source": "Calfus India Employee Handbook v4.pdf",
                    "page": 13,
                    "section": "5.3 Leave Policy",
                    "subsection": "System-Verified Computed Fact",
                },
            )
        ]

    context = format_context(docs)

    llm = ChatOpenAI(model=generation_model, temperature=generation_temperature, seed=42)
    # INJECTION_DEFENSE_PREAMBLE always goes first, ahead of the
    # config-editable system_prompt -- see prompt.py's docstring for why
    # it's a separate, non-editable constant rather than folded into
    # SYSTEM_PROMPT itself.
    # {user_question} appears both inside system_prompt's <input_data> block
    # and in this final human turn -- ChatPromptTemplate fills the same
    # invoke() key into every template that references it, so the model
    # sees the question once written into <input_data> (as the new prompt's
    # spec expects it delivered) and once more as the actual last turn
    # (still needed: a chat completion wants its last message to be from
    # the user, and this is also what {question} used to be named before
    # the prompt rewrite -- see prompt.py's docstring).
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", INJECTION_DEFENSE_PREAMBLE + system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{user_question}"),
        ]
    )
    chain = prompt | llm

    # These fixed strings are interpolated into system_prompt's routing
    # section (see prompt.py) so editing one of these config values updates
    # both what the model is told to say AND what this function compares
    # its output against below -- editing one without the other would
    # otherwise silently break the fallback-detection check.
    response = chain.invoke(
        {
            "chat_history": history_messages,
            "context": context,
            "user_question": question,
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


# --------------------------------------------------------------------------
# Voice path -- fully additive parallel to answer_question() above. Nothing
# in this section is imported or called by answer_question()/_generate_answer,
# and nothing above this line was changed to add it. Used only by
# POST /voice/ask (see api.py), the realtime voice model's search_policies
# tool call.
# --------------------------------------------------------------------------

# Retrieval width for the voice path only -- shorter than the text-chat
# path's config-driven default (15, see config_store.seed_defaults) since a
# 1-3 sentence spoken answer doesn't need as much supporting context, and a
# smaller context/prompt keeps per-turn latency down for a realtime tool
# call. Deliberately NOT read from config_store -- a fixed characteristic of
# this path, not a knob shared with (or capable of drifting) answer_question()'s.
VOICE_RETRIEVAL_K = 6


def answer_question_voice(question: str, chat_history: list[dict] | None = None) -> RagResult:
    """Voice counterpart to answer_question() -- same RagResult shape
    (answer + sources, for a tool-call bridge to speak the answer and show
    the citations on screen), but VOICE_SYSTEM_PROMPT (1-3 spoken sentences,
    no lists -- see prompt.py) instead of SYSTEM_PROMPT, and
    get_retriever(k=VOICE_RETRIEVAL_K) instead of the text path's default.

    No previous_title concept here -- a voice tool call isn't a titled chat
    session the way the text UI is, so previous_title is always None/"None"
    in the underlying prompt (see _generate_voice_answer). chat_history
    still works exactly like answer_question()'s: the caller (POST
    /voice/ask) is expected to pass whatever prior turns exist for the
    session, same [{"role", "content"}, ...] shape.

    Moderation still runs CONCURRENTLY with retrieval+generation, same
    asyncio.gather/asyncio.to_thread pattern and the same _is_abusive check
    as answer_question() -- a voice question gets the identical abuse
    guardrail as a typed one, just checked against this call's own result
    (see _run_moderation_and_generation_voice).
    """
    require_openai_api_key()

    fallback_greeting = config_store.get("generation", "fallback_greeting", FALLBACK_GREETING)
    fallback_handoff = config_store.get("generation", "fallback_handoff", FALLBACK_HANDOFF)
    fallback_unclear = config_store.get("generation", "fallback_unclear", FALLBACK_UNCLEAR)
    fallback_gibberish = config_store.get("generation", "fallback_gibberish", FALLBACK_GIBBERISH)
    fallback_unrelated = config_store.get("generation", "fallback_unrelated", FALLBACK_UNRELATED)
    fallback_unanswered = config_store.get("generation", "fallback_unanswered", FALLBACK_UNANSWERED)
    fallback_abuse = config_store.get("generation", "fallback_abuse", FALLBACK_ABUSE)
    fallback_dangerous = config_store.get("generation", "fallback_dangerous", FALLBACK_DANGEROUS)
    generation_model = config_store.get("generation", "model", GENERATION_MODEL)
    generation_temperature = config_store.get("generation", "temperature", GENERATION_TEMPERATURE)

    question = (question or "").strip()
    if not question:
        return RagResult(answer="Please enter a question.", sources=[], num_chunks_retrieved=0)

    abusive, result = asyncio.run(
        _run_moderation_and_generation_voice(
            question,
            chat_history,
            fallback_greeting,
            fallback_handoff,
            fallback_unclear,
            fallback_gibberish,
            fallback_unrelated,
            fallback_unanswered,
            fallback_dangerous,
            generation_model,
            generation_temperature,
        )
    )
    if abusive:
        return RagResult(answer=fallback_abuse, sources=[], num_chunks_retrieved=0)
    return result


async def _run_moderation_and_generation_voice(
    question: str,
    chat_history: list[dict] | None,
    fallback_greeting: str,
    fallback_handoff: str,
    fallback_unclear: str,
    fallback_gibberish: str,
    fallback_unrelated: str,
    fallback_unanswered: str,
    fallback_dangerous: str,
    generation_model: str,
    generation_temperature: float,
) -> tuple[bool, "RagResult"]:
    """Voice counterpart to _run_moderation_and_generation -- identical
    concurrency shape (asyncio.gather over two asyncio.to_thread calls),
    calling _generate_voice_answer instead of _generate_answer.
    """
    return await asyncio.gather(
        asyncio.to_thread(_is_abusive, question),
        asyncio.to_thread(
            _generate_voice_answer,
            question,
            chat_history,
            fallback_greeting,
            fallback_handoff,
            fallback_unclear,
            fallback_gibberish,
            fallback_unrelated,
            fallback_unanswered,
            fallback_dangerous,
            generation_model,
            generation_temperature,
        ),
    )


def _generate_voice_answer(
    question: str,
    chat_history: list[dict] | None,
    fallback_greeting: str,
    fallback_handoff: str,
    fallback_unclear: str,
    fallback_gibberish: str,
    fallback_unrelated: str,
    fallback_unanswered: str,
    fallback_dangerous: str,
    generation_model: str,
    generation_temperature: float,
) -> RagResult:
    """Voice counterpart to _generate_answer -- same retrieval/generation
    shape and the same shared helpers (_is_list_documents_question,
    store_is_empty, _detect_named_document, the leave-ceiling advisory
    injection, format_context, citation extraction), deliberately
    duplicated rather than parameterizing _generate_answer, so the text
    path above is never at risk of being changed by voice-path work. The
    three real differences from _generate_answer: VOICE_SYSTEM_PROMPT
    instead of the config-driven system_prompt, get_retriever(k=
    VOICE_RETRIEVAL_K) instead of the default k, and previous_title is
    always _NO_PREVIOUS_TITLE (voice has no titled-session concept).
    """
    if _is_list_documents_question(question):
        return RagResult(answer=_list_documents_answer(), sources=[], num_chunks_retrieved=0)

    if store_is_empty():
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    history_messages = _build_history_messages(chat_history)

    named_document = _detect_named_document(question)
    retriever = get_retriever(
        k=VOICE_RETRIEVAL_K, where={"source": named_document} if named_document else None
    )
    docs = retriever.invoke(question)

    if not docs:
        return RagResult(answer=fallback_unanswered, sources=[], num_chunks_retrieved=0)

    # Same goal-oriented-advisory leave-ceiling injection as _generate_answer
    # -- see that function's comment for the full rationale.
    if context_has_leave_policy(docs):
        stated = detect_stated_balance(question)
        if stated and is_ceiling_bucket(stated["bucket"]):
            fact_content = build_stated_balance_fact(stated["bucket"], stated["stated_amount"])
        else:
            fact_content = compute_leave_ceiling().fact_string

        docs = docs + [
            Document(
                page_content=fact_content,
                metadata={
                    "source": "Calfus India Employee Handbook v4.pdf",
                    "page": 13,
                    "section": "5.3 Leave Policy",
                    "subsection": "System-Verified Computed Fact",
                },
            )
        ]

    context = format_context(docs)

    llm = ChatOpenAI(model=generation_model, temperature=generation_temperature, seed=42)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", INJECTION_DEFENSE_PREAMBLE + VOICE_SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{user_question}"),
        ]
    )
    chain = prompt | llm

    response = chain.invoke(
        {
            "chat_history": history_messages,
            "context": context,
            "user_question": question,
            "previous_title": _NO_PREVIOUS_TITLE,
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

    usage = getattr(response, "usage_metadata", None) or {}
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")

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
