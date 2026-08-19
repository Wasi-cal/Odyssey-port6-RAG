"""
api.py — thin FastAPI serving layer in front of the existing RAG pipeline.

This file is purely a transport layer: it never reimplements retrieval,
chunking, grounding, citation, or persistence logic -- all of that behavior
lives in rag.py / ingest.py (and the assistant/ package underneath them),
completely untouched by anything here.

/ask calls rag.answer_question() directly -- a single fast request/response
with nothing worth retrying independently. /ingest instead starts the
Temporal workflow defined in assistant/orchestration/ (one activity per
uploaded file, each retried independently) and awaits its result -- durable
against a transient OpenAI rate-limit or a worker crash mid-batch, with the
exact same {ingested, chunk_count} response contract as a direct call would
have had. Requires a Temporal server + `uv run worker.py` running alongside
this API; see assistant/orchestration/__init__.py.

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
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from assistant import auth, config_store, db, rate_limit
from assistant.orchestration.client import get_temporal_client
from assistant.orchestration.config import TASK_QUEUE
from assistant.orchestration.workflows.ingestion_workflow import IngestDocumentsWorkflow
from ingest import DATA_DIR, delete_document
from rag import answer_question, format_citation

_DATA_DIR_RESOLVED = DATA_DIR.resolve()

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


def require_admin_password(admin_password: str) -> None:
    if not auth.verify_admin_password(admin_password):
        raise HTTPException(status_code=403, detail="Incorrect admin password.")


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
    admin_password: str


class AuditLogEntry(BaseModel):
    action: str
    filename: str
    performed_by: str
    performed_at: str


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


class IngestResponse(BaseModel):
    ingested: list[str]
    chunk_count: int
    skipped: list[str] = []  # names that already existed -- not (re-)ingested


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


@app.post("/auth/admin-reset-password")
def admin_reset_password(payload: AdminResetPasswordRequest) -> dict:
    """Forgot-password recovery for an internal tool with no email system:
    whoever holds the admin password can reset ANY account's password
    directly, without needing to know the old one. Deliberately doesn't
    require being logged in as anyone -- that's the whole point of a
    recovery path -- so the admin password is the only thing gating it.
    """
    require_admin_password(payload.admin_password)
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    username = payload.username.strip()
    if not db.set_password_hash(username, auth.hash_password(payload.new_password)):
        raise HTTPException(status_code=404, detail="No such user.")
    return {"reset": username}


@app.get("/admin/audit-log", response_model=list[AuditLogEntry])
def get_audit_log(user_id: str = Depends(get_current_user)) -> list[AuditLogEntry]:
    """Who uploaded/deleted what, and when -- see db.admin_audit_log's
    comment for why this exists (the admin password itself is a shared
    secret, not a per-user credential, so it alone doesn't say who used it;
    this does, since every /ingest and delete call is authenticated as a
    specific logged-in user before it even checks that password). Viewing
    this only requires being logged in, not the admin password -- reading
    the log isn't a mutating action on the library the way upload/delete are.
    """
    return [AuditLogEntry(**row) for row in db.list_admin_audit_log()]


@app.get("/config")
def get_config(user_id: str = Depends(get_current_user)) -> dict:
    """The current effective config (system prompt, retrieval tuning, etc.),
    as read through the same Redis-cached path /ask and ingestion use --
    mainly for confirming a direct Postgres edit to config_settings has
    taken effect, without needing DB access to check. Requires login -- it's
    a debug view, not something to leave open to anyone unauthenticated.
    """
    try:
        return config_store.get_all()
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

    db.add_message(payload.session_id, "user", question, None)
    previous_title = db.get_session_title(payload.session_id)

    start = time.perf_counter()
    try:
        # Reused as-is: same retrieval, grounding prompt, citation assembly
        # as the CLI (rag.py's __main__) and the previous direct-import UI.
        # previous_title lets the model evolve the session's title turn by
        # turn instead of freezing it at the first message (see qa.py).
        result = answer_question(question, previous_title=previous_title)
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


@app.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(
    files: list[UploadFile] = File(...),
    admin_password: str = Form(...),
    user_id: str = Depends(get_current_user),
) -> IngestResponse:
    require_admin_password(admin_password)

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Checked against Postgres (the same source /library reads), not disk --
    # filenames are the shared identity a document is stored/retrieved under
    # (one physical file, one set of Chroma chunks, for everyone), so an
    # existing name is a global collision, not just a this-user-already-has-
    # it check. Checking Postgres rather than disk keeps this in lockstep
    # with what the library actually shows: a stray file left on disk by a
    # prior partial failure, with no matching library row, is *not* treated
    # as a collision here -- it gets overwritten, which is the correct
    # recovery, not a false "already exists".
    existing_filenames = db.list_all_filenames()

    saved_paths = []
    filenames = []
    skipped = []
    for uploaded in files:
        name = uploaded.filename or ""
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{name!r} is not a PDF.")
        if name in existing_filenames:
            skipped.append(name)
            continue
        dest = DATA_DIR / name
        dest.write_bytes(await uploaded.read())
        saved_paths.append(dest)
        filenames.append(name)

    if not saved_paths:
        return IngestResponse(ingested=[], chunk_count=0, skipped=skipped)

    try:
        # Runs as a Temporal workflow (one activity per file, each
        # independently retried) instead of calling ingest_files() directly
        # -- same underlying pipeline, now durable against a transient
        # OpenAI rate-limit or a worker crash mid-batch. See
        # assistant/orchestration/ for the workflow/activity definitions.
        client = await get_temporal_client()
        chunk_counts = await client.execute_workflow(
            IngestDocumentsWorkflow.run,
            [str(p) for p in saved_paths],
            id=f"ingest-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_unwrap_temporal_error(e)) from e

    for filename, chunk_count in zip(filenames, chunk_counts):
        db.add_document(user_id, filename, chunk_count)
        db.log_admin_action("upload", filename, user_id)

    return IngestResponse(ingested=filenames, chunk_count=sum(chunk_counts), skipped=skipped)


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
    click, not a fetch call) -- just not the separate admin password, which
    only gates changing the library, not reading from it.
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


@app.delete("/documents/{filename}")
def delete_document_endpoint(
    filename: str,
    x_admin_password: str = Header(...),
    user_id: str = Depends(get_current_user),
) -> dict:
    """Deletes a document everywhere: its chunks from Chroma, the raw PDF
    from disk, and its library row (see db.delete_document). Global, not
    scoped to whichever user clicks delete -- there is one shared vector
    store collection for everyone, so a document either exists for
    everyone or, after this, no one.

    Requires the admin password on every single call (not a persistent
    "unlocked" session) -- see require_admin_password.

    Tolerates the three stores (disk, Chroma, Postgres) already being out of
    sync with each other -- e.g. a prior partial failure, or the Chroma
    collection having been wiped directly -- rather than requiring all three
    to agree before doing anything. 404 only if there's genuinely nothing
    to clean up in any of them; each cleanup step is itself a safe no-op
    if that particular store never had this filename to begin with.
    """
    require_admin_password(x_admin_password)

    safe_name = Path(filename).name
    path = _DATA_DIR_RESOLVED / safe_name

    file_exists = path.is_file() and path.suffix.lower() == ".pdf"
    if not file_exists and not db.document_exists(safe_name):
        raise HTTPException(status_code=404, detail="Document not found.")

    delete_document(safe_name)  # Chroma chunks -- no-op if there aren't any
    if file_exists:
        path.unlink()
    db.delete_document(safe_name)  # no-op if there's no row
    db.log_admin_action("delete", safe_name, user_id)

    return {"deleted": safe_name}
