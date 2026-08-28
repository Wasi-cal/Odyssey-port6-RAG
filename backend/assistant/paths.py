"""Filesystem locations shared by the ingestion and retrieval pipelines."""

from pathlib import Path

# Resolved relative to THIS file (assistant/paths.py); .parent.parent walks
# back up out of assistant/ to the backend/ root that data/ and chroma_db/
# live at -- stays correct regardless of the caller's working directory.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = _BACKEND_ROOT / "data" / "pdfs"
PERSIST_DIR = str(_BACKEND_ROOT / "chroma_db")
COLLECTION_NAME = "internal_docs"

# A/B collection for the local (sentence-transformers) embedding provider --
# see embeddings.py's resolve_collection_name. Lives in the SAME chroma_db
# persist dir as COLLECTION_NAME (Chroma supports multiple named collections
# per client), so re-ingesting into this one never touches or overwrites
# the OpenAI-embedded collection.
LOCAL_COLLECTION_NAME = "internal_docs_local_bge"
