"""
rag.py — CLI entrypoint + backward-compatible re-exports for the retrieval /
generation pipeline. The actual logic lives in assistant/retrieval/ (see that
package's docstring for the module breakdown); this file is deliberately
thin, mirroring api.py's role as a thin transport layer.

This module only READS the persisted Chroma store built by ingest.py. It
never writes to it. api.py imports `answer_question()` for the FastAPI
serving layer; eval/run_eval.py imports several of these names directly to
test the pipeline itself rather than the API. It can also be run standalone
for a quick command-line sanity check.

Architecture: all-hosted. Query embedding uses the SAME get_embeddings() that
ingestion used for the documents (a query embedded by a different model than
the corpus would compare vectors from two incompatible spaces -- similarity
search would silently return garbage). Generation uses OpenAI gpt-4o-mini
directly.
"""

import sys

from assistant.openai_key import require_openai_api_key
from assistant.retrieval.citations import format_citation
from assistant.retrieval.config import K, SEARCH_TYPE
from assistant.retrieval.prompt import (
    FALLBACK_UNANSWERED,
    FALLBACK_UNCLEAR,
    FALLBACK_UNRELATED,
    GENERATION_MODEL,
    GENERATION_TEMPERATURE,
    SYSTEM_PROMPT,
)
from assistant.retrieval.qa import RagResult, answer_question
from assistant.retrieval.store import get_retriever, store_is_empty

__all__ = [
    "K",
    "SEARCH_TYPE",
    "GENERATION_MODEL",
    "GENERATION_TEMPERATURE",
    "FALLBACK_UNCLEAR",
    "FALLBACK_UNRELATED",
    "FALLBACK_UNANSWERED",
    "SYSTEM_PROMPT",
    "RagResult",
    "get_retriever",
    "store_is_empty",
    "format_citation",
    "answer_question",
]

if __name__ == "__main__":
    try:
        require_openai_api_key()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if store_is_empty():
        print("The vector store is empty. Run `python ingest.py` first.")
        sys.exit(0)

    q = " ".join(sys.argv[1:]) or input("Question: ")
    result = answer_question(q)
    print("\nAnswer:\n" + result.answer)
    if result.sources:
        print("\nSources:")
        for s in result.sources:
            print(f"  - {format_citation(s)}")
    print(f"\n[{result.num_chunks_retrieved} chunk(s) retrieved]")
