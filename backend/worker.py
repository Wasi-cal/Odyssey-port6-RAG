"""
worker.py — Temporal worker process entrypoint.

Polls the ingestion task queue and executes IngestDocumentsWorkflow /
ingest_document_activity (see assistant/orchestration/). Run alongside a
Temporal server and api.py:

    uv run worker.py
"""

import asyncio

from assistant.orchestration.worker import main

if __name__ == "__main__":
    asyncio.run(main())
