"""
routers/_shared.py — pieces genuinely used by 2+ routers, moved verbatim
out of api.py during the router split. Pure structural move: no logic
changed from what api.py had before.

Auth dependencies (get_current_user, get_current_admin) are needed by
every router except auth.py's register/login (which issue the JWT rather
than checking one) -- so they live here rather than in any single router.
SourceInfo/DocumentInfo, _log_query, and _dedupe_filename are each used by
exactly two routers (chat.py+voice.py; admin.py+documents.py; admin.py+
documents.py respectively) -- same reason.

run_ask_and_log() is the one piece here that's NOT a straight verbatim
move: it's the logic /ask and /voice/ask had duplicated (session-ownership
check, chat_history fetch, add_message, timing, source formatting,
_log_query, token-usage logging), extracted so both endpoints call it
instead of each having their own copy. See its docstring for exactly what
it does and doesn't own.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from assistant import auth, db, pricing
from assistant.retrieval.qa import RagResult
from ingest import DATA_DIR
from rag import format_citation

_DATA_DIR_RESOLVED = DATA_DIR.resolve()

# The JWT cookie name the frontend sets (doc_assist/domain/auth.py) --
# read here only as a fallback, see get_current_user.
_JWT_COOKIE_NAME = "doc_assist_jwt"

# auto_error=False: a missing Authorization header should fall through to
# the cookie check below, not hard-fail before get_current_user even runs.
_bearer_scheme = HTTPBearer(auto_error=False)

REPORTS_DIR = Path(__file__).parent.parent / "reports"
QUERY_LOG_PATH = REPORTS_DIR / "query_log.jsonl"


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Every endpoint except /health and /auth/* depends on this -- the
    username is ALWAYS decoded from a verified JWT, never trusted from a
    client-supplied field (an earlier version of /ask and /ingest took
    user_id directly in the request, which any caller could set to anyone
    they wanted).

    Checks the Authorization header first (what ApiClient sends on every
    fetch-style call), then falls back to the doc_assist_jwt cookie. The
    cookie fallback exists because the Library/citation links are plain
    <a href> browser navigations, not fetch calls -- there's no way to
    attach a custom header to those, so the same JWT is also stored as a
    cookie the browser sends automatically. That only works when the
    frontend and this API share a hostname (differing only by port, as in
    this project's docker-compose setup); across genuinely different
    domains the cookie wouldn't be sent and those links would need a
    different mechanism (e.g. a short-lived signed URL).
    """
    token = credentials.credentials if credentials else request.cookies.get(_JWT_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated -- please log in.")
    try:
        return auth.decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired -- please log in again.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Every /admin/* endpoint except POST /admin/login depends on this --
    verifies a distinct admin JWT (auth.create_admin_token), never the
    regular user JWT get_current_user checks. No cookie fallback: the
    separate admin app always sends a header, no plain-<a href> links.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated as admin -- please log in.")
    try:
        auth.decode_admin_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Admin session expired -- please log in again.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid admin authentication token.")


class SourceInfo(BaseModel):
    label: str  # pre-formatted via rag.format_citation, e.g. "Doc → Section, p.N"
    filename: str  # the real file on disk -- GET /documents/{filename} serves it
    page: int | None = None  # for a #page=N link fragment; None if the chunk's page wasn't known


class DocumentInfo(BaseModel):
    name: str
    chunk_count: int
    ingested_at: str


def _log_query(question: str, num_chunks: int, latency_ms: float, cited_sources: list[str]) -> None:
    """Append one JSON line per /ask (or /voice/ask) call. Never let a
    logging failure break the actual request -- this is purely for future
    monitoring, not correctness."""
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "num_chunks": num_chunks,
            "latency_ms": round(latency_ms, 2),
            "cited_sources": cited_sources,
        }
        with open(QUERY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def run_ask_and_log(
    session_id: str,
    user_id: str,
    question: str,
    generate: Callable[[str, list[dict]], RagResult],
) -> tuple[RagResult, list[SourceInfo], float]:
    """Shared body of /ask and /voice/ask, extracted verbatim from both
    (same session-ownership check, chat_history fetch, add_message, timing,
    SourceInfo formatting, _log_query, and token-usage/cost logging both
    endpoints had duplicated).

    `generate` is whichever answer-generation call the caller wants run
    against (question, chat_history) -- /ask passes a closure around
    answer_question(q, previous_title=..., chat_history=h), /voice/ask
    passes one around answer_question_voice(q, chat_history=h) -- so this
    function never needs to know either signature or which prompt path is
    in play.

    Returns (result, formatted_sources, latency_ms) rather than a response
    model, since /ask's AskResponse has a `title` field (from its own
    title-writeback logic, using this same result) that VoiceAskResponse
    doesn't -- shaping the final response stays with each caller.
    """
    owner = db.get_session_owner(session_id)
    if owner is not None and owner != user_id:
        # Never confirm *why* -- "not yours" and "doesn't exist" both read
        # as 404 to the caller, so a session id can't be used to probe
        # whether it belongs to someone else.
        raise HTTPException(status_code=404, detail="Session not found.")

    # Fetched BEFORE add_message below, so this is every PRIOR message in
    # the session (oldest first, matching what qa.py's chat_history param
    # expects) -- not including the question just asked this call.
    chat_history = db.get_messages(session_id)
    db.add_message(session_id, "user", question, None)

    start = time.perf_counter()
    try:
        result = generate(question, chat_history)
    except RuntimeError as e:
        # e.g. OPENAI_API_KEY missing -- rag.py already raises a clear
        # message here; surface it as a clean 500, not a stack trace.
        raise HTTPException(status_code=500, detail=str(e)) from e
    latency_ms = (time.perf_counter() - start) * 1000

    formatted_sources = [
        SourceInfo(
            label=format_citation(s),
            filename=s["source"],
            page=s["page"] if isinstance(s["page"], int) else None,
        )
        for s in result.sources
    ]
    raw_source_filenames = [s["source"] for s in result.sources]

    _log_query(question, result.num_chunks_retrieved, latency_ms, raw_source_filenames)
    if result.total_tokens is not None:
        try:
            cost = pricing.chat_cost_usd(result.prompt_tokens or 0, result.completion_tokens or 0)
            db.log_token_usage(
                "chat", result.model, result.prompt_tokens, result.completion_tokens, result.total_tokens, cost
            )
        except Exception:
            pass  # best-effort -- never break the endpoint over logging

    meta = {
        "sources": [s.model_dump() for s in formatted_sources],
        "num_chunks": result.num_chunks_retrieved,
        "latency_ms": latency_ms,
    }
    db.add_message(session_id, "assistant", result.answer, meta)

    return result, formatted_sources, latency_ms


def _dedupe_filename(name: str, reserved_names: set[str]) -> str:
    """If `name` is already taken (by different content -- callers only
    reach this after content_hash has already ruled out a true duplicate),
    returns a disambiguated variant instead: "handbook.pdf" -> "handbook
    (2).pdf" -> "handbook (3).pdf", etc. Filename collisions are avoided by
    construction rather than by rejecting the upload -- two different files
    are always allowed to coexist, they just can't share the exact string
    that's Chroma's chunk "source" metadata and the documents table's
    primary key.
    """
    if name not in reserved_names:
        return name
    stem, dot, ext = name.rpartition(".")
    stem, ext = (stem, f".{ext}") if dot else (name, "")
    n = 2
    while True:
        candidate = f"{stem} ({n}){ext}"
        if candidate not in reserved_names:
            return candidate
        n += 1
