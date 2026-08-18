"""Temporal worker process: polls TASK_QUEUE and executes
IngestDocumentsWorkflow + ingest_document_activity. Run via backend/worker.py.
"""

import asyncio
import concurrent.futures

from temporalio.worker import Worker

from .activities.ingestion_activities import ingest_document_activity
from .client import get_temporal_client
from .config import TASK_QUEUE
from .workflows.ingestion_workflow import IngestDocumentsWorkflow


async def main() -> None:
    client = await get_temporal_client()

    # ingest_document_activity does blocking I/O (PDF parsing, OCR, OpenAI
    # calls, Chroma writes) -- sync activities need a thread-pool executor;
    # they can't run directly on Temporal's asyncio event loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as activity_executor:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[IngestDocumentsWorkflow],
            activities=[ingest_document_activity],
            activity_executor=activity_executor,
        )
        print(f"[worker] polling task queue {TASK_QUEUE!r}...")
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
