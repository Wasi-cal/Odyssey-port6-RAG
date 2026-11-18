"""
routers/admin.py — /admin/* endpoints (login, password reset, document
approve/reject/delete/direct-upload, audit log, monitoring), moved verbatim
out of api.py during the router split. No logic changed from what api.py
had before.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from assistant import auth, config_store, db, pricing, rate_limit
from assistant.embeddings import resolve_embed_model_name
from assistant.ingestion import store as ingestion_store
from assistant.orchestration.client import get_temporal_client
from assistant.orchestration.config import TASK_QUEUE
from assistant.orchestration.workflows.ingestion_workflow import IngestDocumentsWorkflow
from assistant.retrieval.store import count_embeddings
from ingest import DATA_DIR

from ._shared import _DATA_DIR_RESOLVED, DocumentInfo, _dedupe_filename, get_current_admin

router = APIRouter()


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


class AdminUploadResponse(BaseModel):
    ingested: list[str]  # accepted (post-rename, if any) and immediately searchable -- no approval step
    skipped: list[str] = []  # duplicate CONTENT of something already in the library or pending
    renamed: dict[str, str] = {}  # original filename -> the disambiguated name it was stored as


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


@router.post("/admin/login", response_model=AdminTokenResponse)
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


@router.post("/admin/change-password")
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


@router.post("/admin/reset-password")
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


@router.get("/admin/audit-log", response_model=list[AuditLogEntry])
def get_audit_log(_: None = Depends(get_current_admin)) -> list[AuditLogEntry]:
    """Who uploaded what, and when -- see db.admin_audit_log's comment
    (the admin password is a shared secret, so it alone doesn't say who
    used it; every upload is attributed to the user who requested it,
    recorded on approval). Admin-only -- moved out of the chatbot sidebar.
    """
    return [AuditLogEntry(**row) for row in db.list_admin_audit_log()]


@router.get("/admin/pending-documents", response_model=list[AdminPendingDocumentInfo])
def list_pending_for_admin(_: None = Depends(get_current_admin)) -> list[AdminPendingDocumentInfo]:
    """Every not-yet-reviewed upload, across all users -- the approval queue."""
    return [AdminPendingDocumentInfo(**d) for d in db.list_all_pending_documents()]


@router.get("/admin/documents", response_model=list[DocumentInfo])
def list_documents_for_admin(_: None = Depends(get_current_admin)) -> list[DocumentInfo]:
    """Same data as GET /library, but reachable with the admin JWT -- the
    admin app has no regular user session to satisfy get_current_user, and
    needs this list to show a Delete button per document.
    """
    return [DocumentInfo(**d) for d in db.list_documents()]


@router.post("/admin/documents", response_model=AdminUploadResponse)
async def admin_upload_documents(
    files: list[UploadFile] = File(...), _: None = Depends(get_current_admin)
) -> AdminUploadResponse:
    """Admin-direct upload: ingests immediately, no approval step -- unlike
    POST /ingest (a regular user's upload, staged for review), an admin
    approving their own upload would just be a pointless extra click. Same
    dedupe-by-content-hash and dedupe-by-filename-collision rules as
    POST /ingest (see _dedupe_filename), checked against both the live
    library and the pending queue so this can't collide with either.

    Unlike approve_pending_document, a failed workflow here removes the file
    it just wrote instead of leaving it in place -- approve leaves it
    because re-approving the SAME pending row retries from that exact staged
    copy; there's no equivalent pending row here to retry from, so an
    unembedded, un-tracked PDF left behind would just be dead weight.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    reserved_hashes = db.list_all_content_hashes() | db.list_pending_content_hashes()
    reserved_names = db.list_all_filenames() | db.list_pending_filenames()
    admin_user_id = db.ensure_admin_user()

    ingested = []
    skipped = []
    renamed = {}
    for uploaded in files:
        name = uploaded.filename or ""
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{name!r} is not a PDF.")

        content = await uploaded.read()
        content_hash = hashlib.sha256(content).hexdigest()

        if content_hash in reserved_hashes:
            skipped.append(name)
            continue

        stored_name = _dedupe_filename(name, reserved_names)
        if stored_name != name:
            renamed[name] = stored_name

        dest = DATA_DIR / stored_name
        dest.write_bytes(content)

        try:
            client = await get_temporal_client()
            results = await client.execute_workflow(
                IngestDocumentsWorkflow.run,
                [str(dest)],
                id=f"ingest-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
        except Exception as e:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=_unwrap_temporal_error(e)) from e

        chunk_count = results[0]["chunk_count"]
        embed_tokens = results[0]["embed_tokens"]

        db.add_document(admin_user_id, stored_name, chunk_count, content_hash)
        db.log_admin_action("upload", stored_name, admin_user_id)
        if embed_tokens:
            cost = pricing.embedding_cost_usd(embed_tokens)
            db.log_token_usage("embedding", resolve_embed_model_name(), None, None, embed_tokens, cost)

        reserved_hashes.add(content_hash)
        reserved_names.add(stored_name)
        ingested.append(stored_name)

    return AdminUploadResponse(ingested=ingested, skipped=skipped, renamed=renamed)


@router.post("/admin/pending-documents/{pending_id}/approve")
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

    db.add_document(pending["uploaded_by"], pending["filename"], chunk_count, pending["content_hash"])
    db.log_admin_action("upload", pending["filename"], pending["uploaded_by"])
    db.mark_pending_approved(pending_id, chunk_count)
    if embed_tokens:
        cost = pricing.embedding_cost_usd(embed_tokens)
        db.log_token_usage("embedding", resolve_embed_model_name(), None, None, embed_tokens, cost)

    return {"approved": pending["filename"], "chunk_count": chunk_count}


@router.post("/admin/pending-documents/{pending_id}/reject")
def reject_pending_document(pending_id: str, _: None = Depends(get_current_admin)) -> dict:
    pending = db.get_pending_document(pending_id)
    if pending is None or pending["status"] != "pending":
        raise HTTPException(status_code=404, detail="No such pending upload.")

    staged_path = Path(pending["staged_path"])
    if staged_path.is_file():
        staged_path.unlink()
    db.mark_pending_rejected(pending_id)
    return {"rejected": pending["filename"]}


@router.delete("/admin/documents/{filename}")
def delete_document(filename: str, _: None = Depends(get_current_admin)) -> dict:
    """Removes a document from the shared library entirely: its Chroma
    chunks (so it stops being retrievable/citable), its `documents` row (so
    it disappears from every user's Library sidebar), and the PDF itself
    from disk. Chroma first -- if that fails, the documents row and file
    stay put and the admin can just retry, rather than the library still
    listing (and /documents/{filename} still serving) a file whose chunks
    are already gone.

    filename is reduced to its final path component before touching the
    filesystem, same defense as GET /documents/{filename} -- this is an
    admin-only endpoint, but there's no reason to trust the path segment
    over that anyway.
    """
    safe_name = Path(filename).name

    ingestion_store.delete_document(safe_name)

    existed = db.remove_document(safe_name)
    if not existed:
        raise HTTPException(status_code=404, detail="No such document.")

    path = _DATA_DIR_RESOLVED / safe_name
    if path.is_file():
        path.unlink()

    db.log_admin_action("delete", safe_name, db.ensure_admin_user())
    return {"deleted": safe_name}


@router.get("/admin/monitoring", response_model=MonitoringResponse)
def get_monitoring(_: None = Depends(get_current_admin)) -> MonitoringResponse:
    usage = db.get_usage_summary()
    return MonitoringResponse(
        pending_approvals=db.count_pending_documents(),
        embeddings_present=count_embeddings(),
        tokens_consumed=usage["tokens_consumed"],
        cost_usd=usage["cost_usd"],
        average_token_usage=usage["average_token_usage"],
    )
