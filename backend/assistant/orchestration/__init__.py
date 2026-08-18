"""
Temporal orchestration for ingestion.

Why: ingesting a PDF calls OpenAI once per chunk to embed it (rate-limit and
network-error prone) and then writes to Chroma -- previously this all ran
synchronously inside one FastAPI request with no durability: a failure
partway through a batch of PDFs meant redoing the whole batch, and a worker
crash mid-run lost all progress. Wrapping it in a Temporal workflow gives
per-document retries and resumability without changing the API contract --
POST /ingest still returns {ingested, chunk_count} synchronously; internally
it now runs the work as a Temporal workflow and awaits the result. answer_question
(/ask) is a single fast request/response with nothing to retry independently,
so it stays a plain function call -- not everything needs a workflow.

    config.py           task queue name + Temporal server address
    client.py           one shared, lazily-connected Client per process
    activities/          the actual (blocking, retryable) units of work
    workflows/            orchestrates activities; itself has no side effects
    worker.py             process entrypoint that polls the task queue

Run the worker alongside api.py and a Temporal server:
    uv run worker.py
"""
