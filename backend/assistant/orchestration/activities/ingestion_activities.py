"""The ingestion activity: extract, chunk, embed, and persist ONE PDF.

One activity per file (not one big activity for the whole batch) is the
whole point -- it's what lets Temporal retry just the file that hit a
transient OpenAI rate-limit or network error, instead of redoing every file
in the batch, and lets a worker crash mid-run resume with only the
not-yet-completed files re-attempted.
"""

from pathlib import Path

from temporalio import activity


@activity.defn
def ingest_document_activity(pdf_path: str) -> dict:
    """Runs the existing, unmodified ingestion pipeline
    (assistant.ingestion.pipeline.ingest_files) against a single PDF path.
    Returns {"chunk_count": int, "embed_tokens": int} -- a plain dict since
    Temporal serializes the activity's return value, and the admin approve
    endpoint needs both figures (chunk_count for the documents/library row,
    embed_tokens as an estimate for the usage/cost dashboard). Imported
    inside the function rather than at module level so the (heavy:
    langchain, tiktoken, chromadb) pipeline is only ever loaded by the
    activity worker, never by anything that merely imports this module to
    reference the activity (e.g. the workflow, or the worker's own
    registration list).
    """
    from assistant.ingestion.pipeline import ingest_files

    chunk_count, embed_tokens = ingest_files([Path(pdf_path)])
    return {"chunk_count": chunk_count, "embed_tokens": embed_tokens}
