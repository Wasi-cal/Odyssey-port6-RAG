"""The persisted Chroma collection -- read handle. Ingestion's own store.py
opens the same collection to write.
"""

from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma

from .. import config_store
from ..embeddings import get_embeddings
from ..paths import COLLECTION_NAME, PERSIST_DIR
from .config import K, SEARCH_TYPE


def _get_store() -> Chroma:
    """Open the persisted Chroma collection for reading.

    embedding_function is get_embeddings() from the shared embeddings.py --
    the SAME function ingestion uses to embed documents. Query and document
    vectors must come from the identical model or similarity search is
    comparing incompatible embedding spaces.

    collection_metadata mirrors ingestion's cosine setting. Chroma only
    applies this at collection CREATION time, so it's a no-op if ingestion
    already created "internal_docs" -- it's set here too only so that if
    retrieval is ever the first thing to touch a fresh ./chroma_db (e.g.
    someone runs the app before ever running ingestion), the collection
    still gets created with the correct metric instead of Chroma's default.
    """
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=PERSIST_DIR,
        # is_persistent=True is REQUIRED alongside client_settings, or Chroma
        # silently runs in-memory-only despite persist_directory being set
        # (see the matching comment in ingestion/store.py's get_vector_store,
        # where this was actually diagnosed).
        client_settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        collection_metadata={"hnsw:space": "cosine"},
    )


def get_retriever(k: int | None = None):
    """k/search_type come from config_store (live, Postgres-backed via
    Redis) on every call, falling back to this module's K/SEARCH_TYPE
    constants if the config subsystem is unreachable -- same live-reload
    contract as retrieval/qa.py's generation settings.
    """
    if k is None:
        k = config_store.get("retrieval", "k", K)
    search_type = config_store.get("retrieval", "search_type", SEARCH_TYPE)
    store = _get_store()
    return store.as_retriever(search_type=search_type, search_kwargs={"k": k})


def store_is_empty() -> bool:
    """True if the Chroma collection has no documents yet (no PDFs ingested)."""
    return _get_store()._collection.count() == 0
