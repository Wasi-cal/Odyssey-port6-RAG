"""
routers/voice.py — /voice/* endpoints (session minting, the search_policies
tool bridge, the BYO-LLM proxy), moved verbatim out of api.py during the
router split (except voice_ask()'s body, which now calls
_shared.run_ask_and_log() -- see that function's docstring for what moved
there and why).
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from assistant import config_store
from assistant.voice import ToolSpec, get_voice_provider
from rag import answer_question_voice

from ._shared import SourceInfo, get_current_user, run_ask_and_log

router = APIRouter()

# One line per /voice/llm-proxy call -- see llm_proxy()'s docstring.
_VOICE_LLM_LOG_PATH = Path(__file__).parent.parent / "reports" / "voice_llm_log.jsonl"

# Spoken by Deepgram's TTS when the think call itself failed -- an actual
# apology beats dead air, matching session_instructions' own "never go
# silent" guidance for a failed/empty search_policies lookup; this covers
# the case one level up, where the think call that would have decided
# whether to even use search_policies never completed at all.
_LLM_PROXY_FALLBACK_TEXT = "Sorry, I'm having some trouble right now -- one moment, please try again."


class VoiceAskRequest(BaseModel):
    question: str
    session_id: str


class VoiceAskResponse(BaseModel):
    answer: str  # short, spoken-style text (see qa.answer_question_voice) -- meant to be spoken aloud by the realtime voice model
    sources: list[SourceInfo]  # citation data for on-screen display only -- never spoken (see prompt.py's <voice_response_style>)
    num_chunks: int
    latency_ms: float


class VoiceSessionResponse(BaseModel):
    """Provider-agnostic shape returned by POST /voice/session -- consistent
    regardless of which RealtimeVoiceProvider (assistant/voice/) is
    configured (config_store's voice/provider), so the frontend picks its
    client integration off `provider` and never needs to know which vendor
    minted the credential.
    """

    provider: str  # "openai" | "deepgram" -- selects which frontend connection path to use
    credential: str  # ephemeral, session-scoped token -- NEVER the underlying provider API key
    expires_at: int  # unix seconds since epoch
    connection: dict  # provider-specific connection details (see RealtimeVoiceProvider.create_session docstring)


@router.post("/voice/ask", response_model=VoiceAskResponse)
def voice_ask(payload: VoiceAskRequest, user_id: str = Depends(get_current_user)) -> VoiceAskResponse:
    """Voice counterpart to POST /ask -- calls qa.answer_question_voice()
    instead of answer_question(), so the realtime voice model's
    search_policies tool call gets a short, spoken-style answer
    (VOICE_SYSTEM_PROMPT, k=6 -- see qa.py) instead of the text chat's
    fuller one. Fully additive: does not modify /ask above, SYSTEM_PROMPT,
    or retrieval.k's config-driven default (15) that /ask still uses.

    Same auth and session-ownership check as /ask, and the same chat_history/
    message-persistence wiring, so a voice turn and a text turn sharing one
    session_id see each other's prior turns. One thing deliberately NOT
    mirrored from /ask: session-title writeback. answer_question_voice()
    always treats previous_title as unset (it has no titled-session concept
    -- see its docstring), so writing its title back here would repeatedly
    overwrite whatever title the text path already established for a shared
    session; this endpoint leaves the session's title alone entirely.
    """
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty.")

    result, formatted_sources, latency_ms = run_ask_and_log(
        payload.session_id,
        user_id,
        question,
        lambda q, chat_history: answer_question_voice(q, chat_history=chat_history),
    )

    return VoiceAskResponse(
        answer=result.answer,
        sources=formatted_sources,
        num_chunks=result.num_chunks_retrieved,
        latency_ms=latency_ms,
    )


# Provider-agnostic ToolSpec (see assistant/voice/base.py) -- each
# RealtimeVoiceProvider adapts this into its own wire shape (OpenAI's flat
# function-tool vs Deepgram's agent.think.functions entry).
_SEARCH_POLICIES_TOOL: ToolSpec = {
    "name": "search_policies",
    "description": (
        "Look up grounded, cited HR policy information or compose an "
        "in-policy leave plan for the employee's stated question or goal. "
        "Always use this tool for any factual or policy claim -- never "
        "answer from your own knowledge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The employee's question or goal, in their own words.",
            }
        },
        "required": ["question"],
    },
}


def _log_voice_llm_call(
    voice_session_id: str,
    latest_user_message: str | None,
    num_messages: int,
    ok: bool,
    latency_ms: float,
    error: str | None,
) -> None:
    """One JSONL line per /voice/llm-proxy call -- scheduled via
    BackgroundTasks (see llm_proxy) so it runs after the response is
    already on the wire and never adds latency to the happy path. Best-
    effort: a logging failure must never affect the actual proxy call,
    same reasoning as _shared._log_query.

    Keyed by voice_session_id, not our app's chat session_id -- Deepgram's
    think request carries no identifier of its own (confirmed live: its
    body is just {model, stream, messages, tools}), so this is a UUID
    minted once per realtime voice session at /voice/session time and
    threaded through via the endpoint URL's query string (see
    deepgram_provider.py). Every call's `messages` array is already
    cumulative (Deepgram forwards the full running conversation on every
    think call, confirmed live) -- logging just the latest user turn per
    line, grouped by voice_session_id, is enough to reconstruct the whole
    conversation in order without repeating everything already-logged.
    """
    try:
        _VOICE_LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "voice_session_id": voice_session_id,
            "num_messages": num_messages,
            "latest_user_message": latest_user_message,
            "ok": ok,
            "latency_ms": round(latency_ms, 2),
            "error": error,
        }
        with open(_VOICE_LLM_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _fallback_sse(text: str) -> bytes:
    """A minimal but valid OpenAI-streaming-chat-completions-shaped SSE
    body carrying `text` as the assistant's entire reply, followed by the
    usual stop chunk and [DONE] -- Deepgram's think stage always requests
    `stream: true` (confirmed live), so a plain JSON error body here would
    fail to parse exactly like the original bug this endpoint already had
    (see llm_proxy's docstring) and Deepgram would still speak nothing.
    """
    chunk_id = f"chatcmpl-fallback-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    content_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
    }
    stop_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    return (
        f"data: {json.dumps(content_chunk)}\n\ndata: {json.dumps(stop_chunk)}\n\ndata: [DONE]\n\n"
    ).encode("utf-8")


@router.post("/voice/llm-proxy")
async def llm_proxy(request: Request, background_tasks: BackgroundTasks):
    """Called by DEEPGRAM'S SERVERS (never the browser) when the Deepgram
    Voice Agent's "think" stage needs an LLM completion -- see
    assistant/voice/deepgram_provider.py's module docstring for why this
    exists: agent.think.endpoint has to be a publicly reachable URL, and
    its auth header travels through the browser-sent Settings message, so
    it can't carry the real OPENAI_API_KEY. This endpoint is what actually
    holds that key and calls OpenAI -- the only thing that ever does, for
    the Deepgram provider.

    Auth is a static shared secret (voice_provider_credentials' deepgram
    llm_proxy_secret, config_store-backed -- see assistant/voice/
    deepgram_provider.py), not a user JWT -- Deepgram's servers have no
    user session to present. Body is forwarded to OpenAI's chat
    completions endpoint as-is. Confirmed via a live end-to-end test (raw
    websocket + InjectUserMessage against Deepgram's agent) that Deepgram's
    think requests set `"stream": true` -- OpenAI responds with an SSE
    stream of `data: {...}` chunks, NOT one JSON object, so this must
    stream the response through byte-for-byte rather than buffering and
    re-encoding it; the original non-streaming version 500'd on every real
    request (resp.json() on an SSE body).

    Two things added on top of that (both purely observability/failure-
    handling, no prompt/instruction content touched): every call is logged
    (see _log_voice_llm_call) via BackgroundTasks -- scheduled here, run
    by Starlette after the response is already sent, so it never blocks
    the streamed reply -- and a request that fails before OpenAI ever
    starts responding (connection error, timeout, or a non-2xx status) now
    gets a spoken fallback (_fallback_sse) instead of whatever OpenAI's raw
    error body would have been, which -- being neither valid SSE nor a
    successful completion -- previously left Deepgram with nothing
    speakable, i.e. dead air with no trace anywhere.
    """
    proxy_secret = config_store.get_voice_secret("deepgram", "llm_proxy_secret")
    auth_header = request.headers.get("authorization", "")
    if not proxy_secret or auth_header != f"Bearer {proxy_secret}":
        raise HTTPException(status_code=401, detail="Invalid or missing proxy credential.")

    body = await request.body()
    voice_session_id = request.query_params.get("voice_session_id", "unknown")

    # Best-effort peek at the payload for logging only -- never let a
    # parse hiccup here affect the actual proxy call below. Every call's
    # `messages` array is cumulative (see _log_voice_llm_call's docstring),
    # so the latest `user` turn is the new part worth recording each time.
    latest_user_message = None
    num_messages = 0
    try:
        parsed = json.loads(body)
        messages = parsed.get("messages", [])
        num_messages = len(messages)
        for m in reversed(messages):
            if m.get("role") == "user":
                latest_user_message = m.get("content")
                break
    except Exception:
        pass

    start = time.perf_counter()
    try:
        upstream = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            data=body,
            stream=True,
            timeout=30,
        )
        if upstream.status_code >= 400:
            # Read (and discard) the error body so the connection is
            # released back to the pool, then treat it the same as a
            # connection-level failure below -- OpenAI's raw error JSON
            # isn't valid SSE, so forwarding it as-is would leave Deepgram
            # with nothing speakable, same failure shape as the original
            # non-streaming bug.
            detail = upstream.text[:500]
            upstream.close()
            raise RuntimeError(f"OpenAI returned {upstream.status_code}: {detail}")
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        background_tasks.add_task(
            _log_voice_llm_call,
            voice_session_id,
            latest_user_message,
            num_messages,
            False,
            latency_ms,
            str(e),
        )
        return StreamingResponse(iter([_fallback_sse(_LLM_PROXY_FALLBACK_TEXT)]), media_type="text/event-stream")

    latency_ms = (time.perf_counter() - start) * 1000
    background_tasks.add_task(
        _log_voice_llm_call, voice_session_id, latest_user_message, num_messages, True, latency_ms, None
    )

    def iter_and_close():
        try:
            yield from upstream.iter_content(chunk_size=None)
        except Exception as e:
            # Streaming had already started (status/headers already sent
            # to Deepgram) -- can't retroactively inject a fallback chunk
            # at this point, but a mid-stream break must still leave a
            # trace rather than disappearing silently.
            background_tasks.add_task(
                _log_voice_llm_call, voice_session_id, latest_user_message, num_messages, False, latency_ms, str(e)
            )
        finally:
            upstream.close()

    return StreamingResponse(
        iter_and_close(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


@router.post("/voice/session", response_model=VoiceSessionResponse)
def create_voice_session(user_id: str = Depends(get_current_user)) -> VoiceSessionResponse:
    """Mints a short-lived, session-scoped credential for this logged-in
    employee's voice session, via whichever RealtimeVoiceProvider
    config_store's voice/provider selects (assistant/voice/ -- "openai" or
    "deepgram"). The frontend uses the returned credential to open its
    realtime connection DIRECTLY to that provider -- never proxied through
    this backend, so audio latency stays off our servers. The underlying
    provider API key never reaches the browser; only the short-lived
    credential does.

    The realtime session (model, voice, persona instructions, greeting, and
    the ONE search_policies tool) is fully configured HERE, server-side --
    all of it read fresh from config_store by get_voice_provider() (hot-
    reloadable, no redeploy needed to change a prompt or model choice) --
    before minting the credential, so the browser can't change the model or
    add tools, only use the exact session this credential was scoped to.

    Same auth as /ask (get_current_user) -- only a logged-in employee can
    start a voice session. Does not touch /ask, /voice/ask, or
    answer_question_voice(); this is a new, additive endpoint.
    """
    try:
        provider = get_voice_provider()
        session = provider.create_session([_SEARCH_POLICIES_TOOL])
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Failed to create voice session: {e}") from e

    return VoiceSessionResponse(
        provider=session.provider,
        credential=session.credential,
        expires_at=session.expires_at,
        connection=session.connection,
    )
