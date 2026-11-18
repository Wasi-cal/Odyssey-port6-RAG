"""
api.py — thin FastAPI serving layer in front of the existing RAG pipeline.

This file is purely a transport layer: it never reimplements retrieval,
chunking, grounding, citation, or persistence logic -- all of that behavior
lives in rag.py / ingest.py (and the assistant/ package underneath them),
completely untouched by anything here.

/ask calls rag.answer_question() directly -- a single fast request/response
with nothing worth retrying independently. /ingest only stages an upload now
(see pending_documents in assistant/db.py); the Temporal workflow defined in
assistant/orchestration/ (one activity per file, each retried independently)
only runs once an admin approves it via the separate admin app, from
POST /admin/pending-documents/{id}/approve. Requires a Temporal server +
`uv run worker.py` running alongside this API; see
assistant/orchestration/__init__.py.

The actual endpoints live in routers/ now, one file per concern
(auth/admin/documents/chat/voice -- see each module's docstring), moved out
of this file verbatim in a structural-only split; this file is just app
creation, the startup/shutdown lifecycle, and wiring each router in.
get_current_user/get_current_admin and the few other pieces genuinely
shared by 2+ routers live in routers/_shared.py.

Run with:
    uvicorn api:app --reload

app.py (Streamlit) is a client of this API, not an importer of rag.py/
ingest.py -- see app.py's docstring. eval/run_eval.py is NOT a client of
this API; it imports rag.py directly, since it tests the pipeline itself,
not this transport layer.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from assistant import auth, config_store, db
from assistant.retrieval.store import get_retriever
from routers import admin, auth as auth_router, chat, documents, voice
from routers._shared import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.require_auth_secrets()
    db.init_db()
    config_store.seed_defaults()

    # Warm the embedding backend once at startup, not on the first real
    # request -- assistant/embeddings.py's "local" provider loads a
    # ~1.3GB model into memory (and, without a persisted cache volume,
    # re-downloads it from the HuggingFace Hub) the first time it's used
    # in a process. Paying that cost inline during a live user's first
    # /ask or /voice/ask turn is exactly what caused a real incident (a
    # 110-second voice response, indistinguishable from a hang) -- this
    # makes the container's healthcheck (and therefore "ready to take
    # traffic") wait for it instead. Runs in a thread so it doesn't block
    # the event loop while it happens; best-effort -- a warmup failure
    # here shouldn't crash startup, since a real request would just pay
    # the same cost inline afterward anyway, same as before this existed.
    try:
        await asyncio.to_thread(lambda: get_retriever().invoke("warmup"))
    except Exception as e:
        print(f"[startup] embedding warmup failed (non-fatal): {e}")

    yield
    db.close_db()


app = FastAPI(title="Internal Documents Assistant API", lifespan=lifespan)

app.include_router(auth_router.router)
app.include_router(admin.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(voice.router)


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/config")
def get_config(user_id: str = Depends(get_current_user)) -> dict:
    """The current effective config (system prompt, retrieval tuning, etc.),
    as read through the same Redis-cached path /ask and ingestion use --
    mainly for confirming a direct Postgres edit to config_settings has
    taken effect, without needing DB access to check. Requires login -- it's
    a debug view, not something to leave open to anyone unauthenticated.

    Strips auth/admin_password specifically -- that row lives in the same
    config_settings table (see config_store.seed_defaults) so the separate
    admin app can read it live, but this endpoint is reachable by ANY logged-
    in chatbot user, not just an admin, and must never hand that secret back.
    """
    try:
        cfg = config_store.get_all()
        cfg.get("auth", {}).pop("admin_password", None)
        return cfg
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Config unavailable: {e}") from e
