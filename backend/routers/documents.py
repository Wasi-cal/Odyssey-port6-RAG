"""
routers/documents.py — document library/ingestion endpoints, moved
verbatim out of api.py during the router split. No logic changed from
what api.py had before.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from assistant import db
from ingest import DATA_DIR

from ._shared import _DATA_DIR_RESOLVED, DocumentInfo, _dedupe_filename, get_current_user

router = APIRouter()

# Uploads wait here (not DATA_DIR) until an admin approves them -- a sibling
# of DATA_DIR under the same backend/data/ volume, so staging survives a
# container restart.
PENDING_DIR = DATA_DIR.parent / "pending"


class PendingDocumentInfo(BaseModel):
    id: str
    filename: str
    uploaded_at: str


class UploadResponse(BaseModel):
    queued: list[str]  # accepted (post-rename, if any), now awaiting admin approval
    skipped: list[str] = []  # duplicate CONTENT of something already in the library or pending
    renamed: dict[str, str] = {}  # original filename -> the disambiguated name it was stored as


@router.post("/ingest", response_model=UploadResponse)
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
    # The only reason to ever skip an upload is duplicate CONTENT (same
    # sha256, see _dedupe_filename's docstring for why filename alone isn't
    # a reliable duplicate check). A filename that's merely already taken
    # by different content is never a reason to skip -- see
    # _dedupe_filename, which renames around it instead.
    reserved_hashes = db.list_all_content_hashes() | db.list_pending_content_hashes()
    reserved_names = db.list_all_filenames() | db.list_pending_filenames()

    queued = []
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

        dest = PENDING_DIR / stored_name
        dest.write_bytes(content)
        db.create_pending_document(str(uuid.uuid4()), stored_name, str(dest), user_id, content_hash)
        reserved_hashes.add(content_hash)
        reserved_names.add(stored_name)
        queued.append(stored_name)

    return UploadResponse(queued=queued, skipped=skipped, renamed=renamed)


@router.get("/documents/pending", response_model=list[PendingDocumentInfo])
def get_pending_documents(user_id: str = Depends(get_current_user)) -> list[PendingDocumentInfo]:
    """This user's own uploads still awaiting admin approval -- what the
    chatbot sidebar shows as "waiting for admin approval".
    """
    return [PendingDocumentInfo(**d) for d in db.list_pending_documents_for_user(user_id)]


@router.get("/library", response_model=list[DocumentInfo])
def get_library(user_id: str = Depends(get_current_user)) -> list[DocumentInfo]:
    """Global -- every user sees every document, matching the fact that
    there's one shared Chroma collection everyone's questions draw from, not
    one per user (chat sessions/history are the ones scoped per user).
    Still requires login (the dependency's return value is unused) -- the
    library isn't meant to be visible to anyone who isn't signed in.
    """
    return [DocumentInfo(**d) for d in db.list_documents()]


@router.get("/documents/{filename}")
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
