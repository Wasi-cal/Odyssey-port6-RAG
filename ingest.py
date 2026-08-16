"""
ingest.py — PDF -> chunk -> embed -> persist to Chroma.

Run standalone (`python ingest.py` or `uv run ingest.py`) to (re)build the vector
store from every PDF in data/pdfs/. app.py also calls `ingest_files()` directly
whenever a user uploads a new PDF through the Streamlit UI, so a brand-new
document works with zero code changes (M6S6).

This module OWNS writes to ./chroma_db. rag.py and app.py only ever read from it.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from chromadb.config import Settings as ChromaSettings

load_dotenv()

# --------------------------------------------------------------------------
# Constants — intentionally placed at the top of the file so they're easy to
# find and tune without digging through the ingestion logic below.
# --------------------------------------------------------------------------

# CHUNK_SIZE=800 / CHUNK_OVERLAP=150 (~18%):
# 800 characters is roughly one coherent paragraph or policy clause — long
# enough that the embedding captures a complete idea (not a sentence
# fragment), short enough that it doesn't blend multiple unrelated ideas into
# one vector, which would dilute similarity search. 150 chars of overlap
# protects rules/definitions that straddle a chunk boundary (e.g. "Employees
# are eligible for..." ending one chunk and "...12 weeks of leave" starting
# the next) — without overlap, a query could retrieve only half of a rule.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

DATA_DIR = Path(__file__).parent / "data" / "pdfs"
PERSIST_DIR = str(Path(__file__).parent / "chroma_db")
COLLECTION_NAME = "internal_docs"
EMBEDDING_MODEL = "text-embedding-3-small"


def _require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )


def load_and_split(pdf_paths: list[Path]) -> list:
    """Load each PDF page-by-page and split into overlapping chunks.

    Every chunk carries metadata {"source": <filename>, "page": <page_number>}
    captured here at ingestion time — this is what lets rag.py produce exact
    citations later, since Chroma stores and returns this metadata untouched.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    all_chunks = []
    for pdf_path in pdf_paths:
        loader = PyPDFLoader(str(pdf_path))
        pages = loader.load()  # one Document per PDF page, 0-indexed page metadata

        for page in pages:
            # Normalize metadata: filename only (not the full local path) and
            # a human-friendly 1-indexed page number.
            page.metadata = {
                "source": pdf_path.name,
                "page": page.metadata.get("page", 0) + 1,
            }

        chunks = splitter.split_documents(pages)
        all_chunks.extend(chunks)

    return all_chunks


def get_vector_store() -> Chroma:
    """Return a handle to the persisted Chroma collection (read or write)."""
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIR,
        client_settings=ChromaSettings(anonymized_telemetry=False),
    )


def ingest_files(pdf_paths: list[Path]) -> int:
    """Embed and persist the given PDFs into Chroma. Returns chunk count added.

    Safe to call repeatedly (e.g. once per uploaded file) — Chroma appends new
    vectors to the existing persisted collection rather than rebuilding it.
    """
    _require_api_key()
    if not pdf_paths:
        return 0

    chunks = load_and_split(pdf_paths)
    if not chunks:
        return 0

    store = get_vector_store()
    store.add_documents(chunks)
    return len(chunks)


def ingest_all() -> int:
    """Rebuild/update the store from every PDF currently in data/pdfs/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))
    return ingest_files(pdf_paths)


if __name__ == "__main__":
    try:
        _require_api_key()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))

    if not pdf_paths:
        print(f"No PDFs found in {DATA_DIR}. Add some and re-run.")
        sys.exit(0)

    print(f"Found {len(pdf_paths)} PDF(s): {[p.name for p in pdf_paths]}")
    count = ingest_files(pdf_paths)
    print(f"Ingested {count} chunks into '{COLLECTION_NAME}' at {PERSIST_DIR}")
