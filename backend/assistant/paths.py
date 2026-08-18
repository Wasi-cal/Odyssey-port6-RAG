"""Filesystem locations shared by the ingestion and retrieval pipelines."""

from pathlib import Path

# Resolved relative to THIS file (assistant/paths.py); .parent.parent walks
# back up out of assistant/ to the backend/ root that data/ and chroma_db/
# live at -- stays correct regardless of the caller's working directory.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = _BACKEND_ROOT / "data" / "pdfs"
PERSIST_DIR = str(_BACKEND_ROOT / "chroma_db")
COLLECTION_NAME = "internal_docs"
