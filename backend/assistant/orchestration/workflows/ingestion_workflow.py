"""Workflow: ingest a batch of already-uploaded PDFs, one activity per file,
running concurrently.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# imports_passed_through(): tells Temporal's workflow sandbox not to
# re-execute/isolate this import -- we're only referencing the activity
# function (to pass to execute_activity below), not calling it, so its own
# (heavy, non-deterministic-looking) imports are irrelevant to workflow
# determinism and shouldn't be sandboxed.
with workflow.unsafe.imports_passed_through():
    from ..activities.ingestion_activities import ingest_document_activity

# Generous but bounded: PDF extraction + OCR + one embedding call per chunk
# for a large scanned document can genuinely take minutes, but a stuck
# activity still shouldn't hold a task queue slot forever.
_ACTIVITY_TIMEOUT = timedelta(minutes=10)

# 3 attempts with exponential backoff absorbs a transient OpenAI rate-limit
# or network blip on a single file without needing the caller to retry the
# whole batch themselves.
_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
)


@workflow.defn
class IngestDocumentsWorkflow:
    """Each PDF's activity is independent and retried independently -- a
    transient failure on one file doesn't force the whole batch to restart,
    and a worker crash mid-run only re-attempts whichever files hadn't
    completed yet.
    """

    @workflow.run
    async def run(self, pdf_paths: list[str]) -> list[dict]:
        """Returns one {"chunk_count", "embed_tokens"} dict per input path,
        same order as pdf_paths -- callers that only want the batch totals
        can sum() the fields themselves; api.py's admin approve endpoint
        needs the per-file breakdown to record accurate library entries and
        usage-log rows per document.
        """
        return await asyncio.gather(
            *[
                workflow.execute_activity(
                    ingest_document_activity,
                    pdf_path,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )
                for pdf_path in pdf_paths
            ]
        )
