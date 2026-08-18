"""
api.py — thin FastAPI serving layer in front of the existing RAG pipeline.

This file is purely a transport layer: it never reimplements retrieval,
chunking, grounding, citation, or persistence logic -- all of that behavior
lives in rag.py / ingest.py (and the assistant/ package underneath them),
completely untouched by anything here.

/ask calls rag.answer_question() directly -- a single fast request/response
with nothing worth retrying independently. /ingest instead starts the
Temporal workflow defined in assistant/orchestration/ (one activity per
uploaded file, each retried independently) and awaits its result -- durable
against a transient OpenAI rate-limit or a worker crash mid-batch, with the
exact same {ingested, chunk_count} response contract as a direct call would
have had. Requires a Temporal server + `uv run worker.py` running alongside
this API; see assistant/orchestration/__init__.py.

Run with:
    uvicorn api:app --reload

app.py (Streamlit) is a client of this API, not an importer of rag.py/
ingest.py -- see app.py's docstring. eval/run_eval.py is NOT a client of
this API; it imports rag.py directly, since it tests the pipeline itself,
not this transport layer.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from assistant.orchestration.client import get_temporal_client
from assistant.orchestration.config import TASK_QUEUE
from assistant.orchestration.workflows.ingestion_workflow import IngestDocumentsWorkflow
from ingest import DATA_DIR
from rag import answer_question, format_citation

app = FastAPI(title="Internal Documents Assistant API")

REPORTS_DIR = Path(__file__).parent / "reports"
QUERY_LOG_PATH = REPORTS_DIR / "query_log.jsonl"


# --------------------------------------------------------------------------
# Request/response models
# --------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list[str]  # pre-formatted via rag.format_citation, same strings app.py already rendered
    num_chunks: int
    latency_ms: float


class IngestResponse(BaseModel):
    ingested: list[str]
    chunk_count: int


# --------------------------------------------------------------------------
# Query log -- best-effort, seeds a future monitoring dashboard
# --------------------------------------------------------------------------


def _unwrap_temporal_error(e: Exception) -> str:
    """Temporal wraps an activity's exception in its own error types
    (WorkflowFailureError -> ActivityError -> ApplicationError, ...) --
    unwrap down to the innermost message so a clear error (e.g. a missing
    OPENAI_API_KEY) still surfaces as a clean, readable string, the same as
    it did before ingestion ran inside a workflow, not as an opaque
    Temporal wrapper type."""
    cause = e
    seen = set()
    while getattr(cause, "cause", None) is not None and id(cause) not in seen:
        seen.add(id(cause))
        cause = cause.cause
    return str(cause) or str(e)


def _log_query(question: str, num_chunks: int, latency_ms: float, cited_sources: list[str]) -> None:
    """Append one JSON line per /ask call. Never let a logging failure break
    the actual request -- this is purely for future monitoring, not correctness."""
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "num_chunks": num_chunks,
            "latency_ms": round(latency_ms, 2),
            "cited_sources": cited_sources,
        }
        with open(QUERY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty.")

    start = time.perf_counter()
    try:
        # Reused as-is: same retrieval, grounding prompt, citation assembly
        # as the CLI (rag.py's __main__) and the previous direct-import UI.
        result = answer_question(question)
    except RuntimeError as e:
        # e.g. OPENAI_API_KEY missing -- rag.py already raises a clear
        # message here; surface it as a clean 500, not a stack trace.
        raise HTTPException(status_code=500, detail=str(e)) from e
    latency_ms = (time.perf_counter() - start) * 1000

    formatted_sources = [format_citation(s) for s in result.sources]
    raw_source_filenames = [s["source"] for s in result.sources]

    _log_query(question, result.num_chunks_retrieved, latency_ms, raw_source_filenames)

    return AskResponse(
        answer=result.answer,
        sources=formatted_sources,
        num_chunks=result.num_chunks_retrieved,
        latency_ms=latency_ms,
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(files: list[UploadFile] = File(...)) -> IngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    filenames = []
    for uploaded in files:
        if not (uploaded.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{uploaded.filename!r} is not a PDF.")
        dest = DATA_DIR / uploaded.filename
        dest.write_bytes(await uploaded.read())
        saved_paths.append(dest)
        filenames.append(uploaded.filename)

    try:
        # Runs as a Temporal workflow (one activity per file, each
        # independently retried) instead of calling ingest_files() directly
        # -- same underlying pipeline, now durable against a transient
        # OpenAI rate-limit or a worker crash mid-batch. See
        # assistant/orchestration/ for the workflow/activity definitions.
        # The request/response contract here is unchanged: this still
        # returns {ingested, chunk_count} synchronously.
        client = await get_temporal_client()
        chunk_count = await client.execute_workflow(
            IngestDocumentsWorkflow.run,
            [str(p) for p in saved_paths],
            id=f"ingest-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_unwrap_temporal_error(e)) from e

    return IngestResponse(ingested=filenames, chunk_count=chunk_count)
