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

Run with:
    uvicorn api:app --reload

app.py (Streamlit) is a client of this API, not an importer of rag.py/
ingest.py -- see app.py's docstring. eval/run_eval.py is NOT a client of
this API; it imports rag.py directly, since it tests the pipeline itself,
not this transport layer.
"""

import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from assistant import auth, config_store, db, pricing, rate_limit
from assistant.embeddings import resolve_embed_model_name
from assistant.orchestration.client import get_temporal_client
from assistant.orchestration.config import TASK_QUEUE
from assistant.orchestration.workflows.ingestion_workflow import IngestDocumentsWorkflow
from assistant.retrieval.store import count_embeddings
from ingest import DATA_DIR
from rag import answer_question, format_citation

_DATA_DIR_RESOLVED = DATA_DIR.resolve()
# Uploads wait here (not DATA_DIR) until an admin approves them -- a sibling
# of DATA_DIR under the same backend/data/ volume, so staging survives a
# container restart.
PENDING_DIR = DATA_DIR.parent / "pending"

# The JWT cookie name the frontend sets (doc_assist/domain/auth.py) --
# read here only as a fallback, see get_current_user.
_JWT_COOKIE_NAME = "doc_assist_jwt"

# auto_error=False: a missing Authorization header should fall through to
# the cookie check below, not hard-fail before get_current_user even runs.
_bearer_scheme = HTTPBearer(auto_error=False)


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


# Truncation matches the frontend's own ChatSession.add_message title logic
# (doc_assist/domain/models.py) -- kept in sync by eye since it's a one-liner
# duplicated on both sides of the API boundary, not worth sharing a package for.
_TITLE_MAX_LEN = 40


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.require_auth_secrets()
    db.init_db()
    config_store.seed_defaults()
    yield
    db.close_db()


app = FastAPI(title="Internal Documents Assistant API", lifespan=lifespan)

REPORTS_DIR = Path(__file__).parent / "reports"
QUERY_LOG_PATH = REPORTS_DIR / "query_log.jsonl"


# --------------------------------------------------------------------------
# Request/response models
# --------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class WhoAmIResponse(BaseModel):
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminResetPasswordRequest(BaseModel):
    username: str
    new_password: str


class AdminChangePasswordRequest(BaseModel):
    new_admin_password: str


class AuditLogEntry(BaseModel):
    action: str
    filename: str
    performed_by: str
    performed_at: str


class AdminLoginRequest(BaseModel):
    admin_password: str


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PendingDocumentInfo(BaseModel):
    id: str
    filename: str
    uploaded_at: str


class AdminPendingDocumentInfo(BaseModel):
    id: str
    filename: str
    uploaded_by: str
    uploaded_at: str


class MonitoringResponse(BaseModel):
    pending_approvals: int
    embeddings_present: int
    tokens_consumed: int
    cost_usd: float
    average_token_usage: float


class AskRequest(BaseModel):
    question: str
    session_id: str


class SourceInfo(BaseModel):
    label: str  # pre-formatted via rag.format_citation, e.g. "Doc → Section, p.N"
    filename: str  # the real file on disk -- GET /documents/{filename} serves it
    page: int | None = None  # for a #page=N link fragment; None if the chunk's page wasn't known


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]
    num_chunks: int
    latency_ms: float
    title: str | None = None  # the session's current title, possibly just updated by this call -- None only if nothing changed and there wasn't one already


class UploadResponse(BaseModel):
    queued: list[str]  # accepted, now awaiting admin approval
    skipped: list[str] = []  # names already in the library or already pending


class DocumentInfo(BaseModel):
    name: str
    chunk_count: int
    ingested_at: str


class SessionInfo(BaseModel):
    id: str
    title: str | None
    created_at: str


class MessageInfo(BaseModel):
    role: str
    content: str
    meta: dict | None = None


# --------------------------------------------------------------------------
# Query log -- best-effort, seeds a future monitoring dashboard
# --------------------------------------------------------------------------


def _unwrap_temporal_error(e: Exception) -> str:
    """Temporal wraps an activity's exception in its own error types
    (WorkflowFailureError -> ActivityError -> ApplicationError, ...) --
    unwrap down to the innermost message so a clear error (e.g. a missing
    OPENAI_API_KEY) still surfaces as a clean, readable string, the same as
    it did before ingestion ran inside a workflow, not as an opaque
    Temporal wrapper type."""
    cause = e
    seen = set()
    while getattr(cause, "cause", None) is not None and id(cause) not in seen:
        seen.add(id(cause))
        cause = cause.cause
    return str(cause) or str(e)


def _log_query(question: str, num_chunks: int, latency_ms: float, cited_sources: list[str]) -> None:
    """Append one JSON line per /ask call. Never let a logging failure break
    the actual request -- this is purely for future monitoring, not correctness."""
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


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# --------------------------------------------------------------------------
# Auth -- the only endpoints besides /health that don't require a JWT
# --------------------------------------------------------------------------


@app.post("/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest) -> TokenResponse:
    username = payload.username.strip()
    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if not payload.password or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    created = db.create_account(username, auth.hash_password(payload.password))
    if not created:
        raise HTTPException(status_code=409, detail="That username is already taken.")

    return TokenResponse(access_token=auth.create_access_token(username), username=username)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    username = payload.username.strip()
    client_ip = request.client.host if request.client else "unknown"

    # Locked out by EITHER key -- repeated failures against this one
    # username, or repeated failures from this one source regardless of
    # which username(s) it's trying.
    if rate_limit.is_locked_out("user", username) or rate_limit.is_locked_out("ip", client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again in a few minutes.",
        )

    password_hash = db.get_password_hash(username)
    # Same error for "no such user" and "wrong password" -- distinguishing
    # them tells an attacker which usernames exist.
    if not password_hash or not auth.verify_password(payload.password, password_hash):
        rate_limit.record_failure("user", username)
        rate_limit.record_failure("ip", client_ip)
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    rate_limit.clear_failures("user", username)
    rate_limit.clear_failures("ip", client_ip)
    return TokenResponse(access_token=auth.create_access_token(username), username=username)


@app.get("/auth/me", response_model=WhoAmIResponse)
def whoami(user_id: str = Depends(get_current_user)) -> WhoAmIResponse:
    """Lets the frontend confirm a stored JWT (from a browser cookie) is
    still valid and recover the username it belongs to after a page reload,
    without the user having to log in again just because the page reloaded.
    """
    return WhoAmIResponse(username=user_id)


@app.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest, user_id: str = Depends(get_current_user)
) -> dict:
    """Self-service -- proves identity with the CURRENT password, not the
    admin password (that gates the shared document library, not a person's
    own account). Doesn't help if you've actually forgotten your password;
    see /auth/admin-reset-password for that.
    """
    password_hash = db.get_password_hash(user_id)
    if not password_hash or not auth.verify_password(payload.current_password, password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    db.set_password_hash(user_id, auth.hash_password(payload.new_password))
    return {"changed": True}


@app.post("/admin/login", response_model=AdminTokenResponse)
def admin_login(payload: AdminLoginRequest, request: Request) -> AdminTokenResponse:
    """The only /admin/* endpoint that doesn't require get_current_admin --
    this is what issues that token. Never called from the chatbot -- the
    separate admin app is the only client. Rate-limited like user login:
    ADMIN_PASSWORD is one shared secret, worth brute-force protecting too.
    """
    client_ip = request.client.host if request.client else "unknown"
    if rate_limit.is_locked_out("admin_ip", client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    if not auth.verify_admin_password(payload.admin_password):
        rate_limit.record_failure("admin_ip", client_ip)
        raise HTTPException(status_code=401, detail="Incorrect admin password.")
    rate_limit.clear_failures("admin_ip", client_ip)
    return AdminTokenResponse(access_token=auth.create_admin_token())


@app.post("/admin/change-password")
def admin_change_password(
    payload: AdminChangePasswordRequest, _: None = Depends(get_current_admin)
) -> dict:
    """Changes the SHARED admin password (config_settings: auth/admin_password)
    -- the in-app alternative to editing that row by hand in psql. Requires
    already being logged in as admin; doesn't ask for the current password
    since there's no per-admin account to re-verify against, just the one
    shared secret this endpoint itself is gated by.
    """
    if len(payload.new_admin_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    config_store.set("auth", "admin_password", payload.new_admin_password)
    return {"changed": True}


@app.post("/admin/reset-password")
def admin_reset_password(payload: AdminResetPasswordRequest, _: None = Depends(get_current_admin)) -> dict:
    """Forgot-password recovery for an internal tool with no email system --
    the admin app resets any account's password directly, no old password
    needed. Lives under the admin app now, not the chatbot's login screen.
    """
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    username = payload.username.strip()
    if not db.set_password_hash(username, auth.hash_password(payload.new_password)):
        raise HTTPException(status_code=404, detail="No such user.")
    return {"reset": username}


@app.get("/admin/audit-log", response_model=list[AuditLogEntry])
def get_audit_log(_: None = Depends(get_current_admin)) -> list[AuditLogEntry]:
    """Who uploaded what, and when -- see db.admin_audit_log's comment
    (the admin password is a shared secret, so it alone doesn't say who
    used it; every upload is attributed to the user who requested it,
    recorded on approval). Admin-only -- moved out of the chatbot sidebar.
    """
    return [AuditLogEntry(**row) for row in db.list_admin_audit_log()]


@app.get("/admin/pending-documents", response_model=list[AdminPendingDocumentInfo])
def list_pending_for_admin(_: None = Depends(get_current_admin)) -> list[AdminPendingDocumentInfo]:
    """Every not-yet-reviewed upload, across all users -- the approval queue."""
    return [AdminPendingDocumentInfo(**d) for d in db.list_all_pending_documents()]


@app.post("/admin/pending-documents/{pending_id}/approve")
async def approve_pending_document(pending_id: str, _: None = Depends(get_current_admin)) -> dict:
    """Runs the same ingestion pipeline /ingest used to run inline before --
    now triggered by admin approval instead of the uploader's own admin
    password. Moves the staged file into DATA_DIR first (matching where
    /ingest used to write before running the workflow, so chunk metadata's
    "source" and get_document's lookup both see the real filename) --
    left in DATA_DIR even on a failed workflow, so re-approving retries
    cleanly rather than losing the file.
    """
    pending = db.get_pending_document(pending_id)
    if pending is None or pending["status"] != "pending":
        raise HTTPException(status_code=404, detail="No such pending upload.")

    staged_path = Path(pending["staged_path"])
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    final_path = DATA_DIR / pending["filename"]
    if staged_path.is_file():
        staged_path.replace(final_path)
    elif not final_path.is_file():
        raise HTTPException(status_code=404, detail="Staged file is missing on disk.")

    try:
        client = await get_temporal_client()
        results = await client.execute_workflow(
            IngestDocumentsWorkflow.run,
            [str(final_path)],
            id=f"ingest-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_unwrap_temporal_error(e)) from e

    chunk_count = results[0]["chunk_count"]
    embed_tokens = results[0]["embed_tokens"]

    db.add_document(pending["uploaded_by"], pending["filename"], chunk_count)
    db.log_admin_action("upload", pending["filename"], pending["uploaded_by"])
    db.mark_pending_approved(pending_id, chunk_count)
    if embed_tokens:
        cost = pricing.embedding_cost_usd(embed_tokens)
        db.log_token_usage("embedding", resolve_embed_model_name(), None, None, embed_tokens, cost)

    return {"approved": pending["filename"], "chunk_count": chunk_count}


@app.post("/admin/pending-documents/{pending_id}/reject")
def reject_pending_document(pending_id: str, _: None = Depends(get_current_admin)) -> dict:
    pending = db.get_pending_document(pending_id)
    if pending is None or pending["status"] != "pending":
        raise HTTPException(status_code=404, detail="No such pending upload.")

    staged_path = Path(pending["staged_path"])
    if staged_path.is_file():
        staged_path.unlink()
    db.mark_pending_rejected(pending_id)
    return {"rejected": pending["filename"]}


@app.get("/admin/monitoring", response_model=MonitoringResponse)
def get_monitoring(_: None = Depends(get_current_admin)) -> MonitoringResponse:
    usage = db.get_usage_summary()
    return MonitoringResponse(
        pending_approvals=db.count_pending_documents(),
        embeddings_present=count_embeddings(),
        tokens_consumed=usage["tokens_consumed"],
        cost_usd=usage["cost_usd"],
        average_token_usage=usage["average_token_usage"],
    )


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


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, user_id: str = Depends(get_current_user)) -> AskResponse:
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty.")

    owner = db.get_session_owner(payload.session_id)
    if owner is not None and owner != user_id:
        # Never confirm *why* -- "not yours" and "doesn't exist" both read
        # as 404 to the caller, so a session id can't be used to probe
        # whether it belongs to someone else.
        raise HTTPException(status_code=404, detail="Session not found.")

    # Fetched BEFORE add_message below, so this is every PRIOR message in
    # the session (oldest first, matching what qa.py's chat_history param
    # expects) -- not including the question just asked this call.
    chat_history = db.get_messages(payload.session_id)

    db.add_message(payload.session_id, "user", question, None)
    previous_title = db.get_session_title(payload.session_id)

    start = time.perf_counter()
    try:
        # Reused as-is: same retrieval, grounding prompt, citation assembly
        # as the CLI (rag.py's __main__) and the previous direct-import UI.
        # previous_title lets the model evolve the session's title turn by
        # turn instead of freezing it at the first message; chat_history
        # lets it resolve follow-up questions against earlier turns (see
        # qa.py).
        result = answer_question(question, previous_title=previous_title, chat_history=chat_history)
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
            pass  # best-effort, matching _log_query -- never break /ask over logging

    meta = {
        "sources": [s.model_dump() for s in formatted_sources],
        "num_chunks": result.num_chunks_retrieved,
        "latency_ms": latency_ms,
    }
    db.add_message(payload.session_id, "assistant", result.answer, meta)

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


@app.post("/ingest", response_model=UploadResponse)
async def ingest_endpoint(
    files: list[UploadFile] = File(...), user_id: str = Depends(get_current_user)
) -> UploadResponse:
    """Stages each upload for admin review -- no admin password needed here
    any more, and nothing is ingested/searchable until an admin approves it
    (see POST /admin/pending-documents/{id}/approve).
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    # Checked against both the live library AND anything already queued --
    # filenames are the shared identity a document is stored/retrieved
    # under, so a name can't be claimed twice before it's even reviewed.
    reserved = db.list_all_filenames() | db.list_pending_filenames()

    queued = []
    skipped = []
    for uploaded in files:
        name = uploaded.filename or ""
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{name!r} is not a PDF.")
        if name in reserved:
            skipped.append(name)
            continue
        dest = PENDING_DIR / name
        dest.write_bytes(await uploaded.read())
        db.create_pending_document(str(uuid.uuid4()), name, str(dest), user_id)
        reserved.add(name)
        queued.append(name)

    return UploadResponse(queued=queued, skipped=skipped)


@app.get("/documents/pending", response_model=list[PendingDocumentInfo])
def get_pending_documents(user_id: str = Depends(get_current_user)) -> list[PendingDocumentInfo]:
    """This user's own uploads still awaiting admin approval -- what the
    chatbot sidebar shows as "waiting for admin approval".
    """
    return [PendingDocumentInfo(**d) for d in db.list_pending_documents_for_user(user_id)]


@app.get("/library", response_model=list[DocumentInfo])
def get_library(user_id: str = Depends(get_current_user)) -> list[DocumentInfo]:
    """Global -- every user sees every document, matching the fact that
    there's one shared Chroma collection everyone's questions draw from, not
    one per user (chat sessions/history are the ones scoped per user).
    Still requires login (the dependency's return value is unused) -- the
    library isn't meant to be visible to anyone who isn't signed in.
    """
    return [DocumentInfo(**d) for d in db.list_documents()]


@app.get("/sessions", response_model=list[SessionInfo])
def get_sessions(user_id: str = Depends(get_current_user)) -> list[SessionInfo]:
    return [SessionInfo(**s) for s in db.list_sessions(user_id)]


@app.post("/sessions", response_model=SessionInfo)
def create_session(user_id: str = Depends(get_current_user)) -> SessionInfo:
    return SessionInfo(**db.create_session(user_id))


@app.get("/sessions/{session_id}/messages", response_model=list[MessageInfo])
def get_session_messages(
    session_id: str, user_id: str = Depends(get_current_user)
) -> list[MessageInfo]:
    owner = db.get_session_owner(session_id)
    if owner is not None and owner != user_id:
        raise HTTPException(status_code=404, detail="Session not found.")
    return [MessageInfo(**m) for m in db.get_messages(session_id)]


@app.get("/documents/{filename}")
def get_document(filename: str, user_id: str = Depends(get_current_user)) -> FileResponse:
    """Serves a previously-ingested PDF's raw bytes, for the frontend's
    Library links to view (inline, in a new tab) or download.

    filename is reduced to its final path component before touching the
    filesystem, so a value like "../../etc/passwd" can't escape DATA_DIR --
    it isn't validated against any particular user's library, since the
    underlying document set (Chroma's collection) is already shared across
    all users for retrieval, same as it is today. Login is still required
    (via get_current_user's cookie fallback, since this is a plain link
    click, not a fetch call).
    """
    safe_name = Path(filename).name
    path = _DATA_DIR_RESOLVED / safe_name
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Document not found.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=safe_name,
        content_disposition_type="inline",
    )
