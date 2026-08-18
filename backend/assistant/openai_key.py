"""Shared OPENAI_API_KEY presence check.

Both the ingestion pipeline (embedding documents) and the retrieval pipeline
(embedding queries + generation) call OpenAI directly, so both need this
guard before doing any real work -- previously defined identically in both
ingest.py and rag.py; consolidated here so the two copies can't drift.
"""

import os


def require_openai_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )
