"""5. The persisted Chroma collection -- write handle. Retrieval's own
store.py opens the same collection read-only.
"""

from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma

from ..embeddings import get_embeddings
from ..paths import COLLECTION_NAME, PERSIST_DIR


def get_vector_store() -> Chroma:
    """Return a handle to the persisted Chroma collection (read or write).

    embedding_function comes from the shared embeddings.get_embeddings(), not
    a locally-constructed OpenAIEmbeddings -- retrieval must use the exact
    same function for query embedding, or similarity search is comparing
    vectors from two different embedding spaces and retrieval quietly breaks.

    collection_metadata sets cosine distance, which is what OpenAI's
    embeddings (including text-embedding-3-small) are designed to be compared
    with. NOTE: Chroma only applies this at collection CREATION time -- if
    ./chroma_db already has an "internal_docs" collection from before this
    change (default space, not cosine), this metadata is silently ignored on
    the existing collection. Delete ./chroma_db and re-ingest fresh (already
    the plan given the chunking-schema changes) to actually pick this up.
    """
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=PERSIST_DIR,
        # is_persistent=True is REQUIRED here, not implied by passing
        # persist_directory -- langchain_chroma only auto-sets it when
        # client_settings is omitted entirely. Without this, Chroma silently
        # falls back to an in-memory-only client: writes "succeed" within
        # the current process but chroma_db/ is never created and nothing
        # survives a restart (found via eval/run_eval.py returning 0 hits
        # against a store that ingest.py had just reported success on).
        client_settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        collection_metadata={"hnsw:space": "cosine"},
    )


def delete_document(filename: str) -> None:
    """Removes every chunk whose "source" metadata matches filename from the
    Chroma collection -- the same delete-by-metadata call pipeline.py already
    makes before a re-ingest (see its idempotent delete-then-add), just
    without the follow-up add_documents.
    """
    get_vector_store()._collection.delete(where={"source": filename})
