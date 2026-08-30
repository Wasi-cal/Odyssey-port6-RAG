"""
routers/chat.py — chat session endpoints + /ask, moved verbatim out of
api.py during the router split (except /ask's body, which now calls
_shared.run_ask_and_log() -- see that function's docstring for what moved
there and why).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from assistant import db
from rag import answer_question

from ._shared import SourceInfo, get_current_user, run_ask_and_log

router = APIRouter()

# Truncation matches the frontend's own ChatSession.add_message title logic
# (doc_assist/domain/models.py) -- kept in sync by eye since it's a one-liner
# duplicated on both sides of the API boundary, not worth sharing a package for.
_TITLE_MAX_LEN = 40


class AskRequest(BaseModel):
    question: str
    session_id: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]
    num_chunks: int
    latency_ms: float
    title: str | None = None  # the session's current title, possibly just updated by this call -- None only if nothing changed and there wasn't one already


class SessionInfo(BaseModel):
    id: str
    title: str | None
    created_at: str


class MessageInfo(BaseModel):
    role: str
    content: str
    meta: dict | None = None


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, user_id: str = Depends(get_current_user)) -> AskResponse:
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty.")

    # Read once, reused both for the answer_question() call below (via the
    # closure) and for the title-writeback decision after -- get_session_title
    # doesn't interact with run_ask_and_log's internal add_message calls
    # (different tables), so fetching it here instead of mid-helper (where
    # the original inline code fetched it, right after the user message was
    # added) doesn't change what value comes back.
    previous_title = db.get_session_title(payload.session_id)

    # Reused as-is: same retrieval, grounding prompt, citation assembly as
    # the CLI (rag.py's __main__) and the previous direct-import UI.
    # previous_title lets the model evolve the session's title turn by turn
    # instead of freezing it at the first message; chat_history (supplied
    # by run_ask_and_log) lets it resolve follow-up questions against
    # earlier turns (see qa.py).
    result, formatted_sources, latency_ms = run_ask_and_log(
        payload.session_id,
        user_id,
        question,
        lambda q, chat_history: answer_question(q, previous_title=previous_title, chat_history=chat_history),
    )

    # result.title comes from the SAME LLM call (see qa.answer_question's
    # TITLE/ANSWER envelope) -- no second call just to name/rename the chat.
    # Updated on every exchange, not just the first, so it can track the
    # conversation as it evolves. Only falls back to a naive truncation of
    # the question when the LLM wasn't actually invoked (empty
    # question/store/retrieval, see qa.py) AND there's no previous title yet
    # to just leave alone -- past the first message, "LLM wasn't invoked"
    # means genuinely nothing changed, so the title is left untouched rather
    # than overwritten with a worse guess.
    if result.title:
        new_title = result.title
    elif previous_title is None:
        new_title = question[:_TITLE_MAX_LEN] + ("…" if len(question) > _TITLE_MAX_LEN else "")
    else:
        new_title = None

    if new_title is not None:
        db.set_session_title(payload.session_id, new_title)

    return AskResponse(
        answer=result.answer,
        sources=formatted_sources,
        num_chunks=result.num_chunks_retrieved,
        latency_ms=latency_ms,
        title=new_title,
    )


@router.get("/sessions", response_model=list[SessionInfo])
def get_sessions(user_id: str = Depends(get_current_user)) -> list[SessionInfo]:
    return [SessionInfo(**s) for s in db.list_sessions(user_id)]


@router.post("/sessions", response_model=SessionInfo)
def create_session(user_id: str = Depends(get_current_user)) -> SessionInfo:
    return SessionInfo(**db.create_session(user_id))


@router.get("/sessions/{session_id}/messages", response_model=list[MessageInfo])
def get_session_messages(
    session_id: str, user_id: str = Depends(get_current_user)
) -> list[MessageInfo]:
    owner = db.get_session_owner(session_id)
    if owner is not None and owner != user_id:
        raise HTTPException(status_code=404, detail="Session not found.")
    return [MessageInfo(**m) for m in db.get_messages(session_id)]
