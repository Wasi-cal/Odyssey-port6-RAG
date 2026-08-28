"""
ingest.py — CLI entrypoint + backward-compatible re-exports for the ingestion
pipeline. The actual pipeline lives in assistant/ingestion/ (see that
package's docstring for the stage-by-stage breakdown); this file is
deliberately thin, mirroring api.py's role as a thin transport layer.

Run standalone (`python ingest.py` or `uv run ingest.py`) to (re)build the
vector store from every PDF in data/pdfs/. api.py also calls `ingest_files()`
directly whenever a user uploads a new PDF through the Streamlit UI, so a
brand-new document works with zero code changes (M6S6).

This module OWNS writes to ./chroma_db. assistant/retrieval/ and api.py only
ever read from it.
"""

import argparse
import sys

from assistant.embeddings import resolve_collection_name
from assistant.ingestion.pipeline import ingest_all, ingest_files, load_and_split
from assistant.ingestion.store import get_vector_store
from assistant.openai_key import require_openai_api_key
from assistant.paths import COLLECTION_NAME, DATA_DIR, PERSIST_DIR

__all__ = [
    "DATA_DIR",
    "PERSIST_DIR",
    "COLLECTION_NAME",
    "load_and_split",
    "get_vector_store",
    "ingest_files",
    "ingest_all",
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=["openai", "local"],
        default=None,
        help=(
            "Embedding backend to ingest with (assistant/embeddings.py). Defaults to "
            "config_store's embeddings/embed_provider ('openai' unless changed). 'local' "
            "ingests the SAME PDFs into a separate collection (paths.LOCAL_COLLECTION_NAME) "
            "via the local (sentence-transformers) model -- never overwrites the OpenAI "
            "collection, for A/B comparison before committing to a switch."
        ),
    )
    args = parser.parse_args()

    try:
        require_openai_api_key()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))

    if not pdf_paths:
        print(f"No PDFs found in {DATA_DIR}. Add some and re-run.")
        sys.exit(0)

    collection_name = resolve_collection_name(args.provider)
    print(f"Found {len(pdf_paths)} PDF(s): {[p.name for p in pdf_paths]}")
    chunk_count, embed_tokens = ingest_files(pdf_paths, args.provider)
    print(
        f"Ingested {chunk_count} chunks ({embed_tokens} embedding tokens) "
        f"into '{collection_name}' at {PERSIST_DIR}"
    )
