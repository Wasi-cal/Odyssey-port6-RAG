"""
embeddings.py — single source of truth for the embedding model configuration.

Architecture: all-hosted. Both embeddings (this module, text-embedding-3-small)
and generation (rag.py, gpt-4o-mini) are OpenAI-hosted -- every document chunk
(at ingestion) and every user query (at retrieval and generation) is sent to
OpenAI's API.

Both ingest.py and rag.py MUST call get_embeddings() rather than constructing
OpenAIEmbeddings themselves. Documents and queries have to be embedded by the
identical model for vector similarity between them to mean anything -- routing
both call sites through one function is what guarantees that never drifts.
"""

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()

EMBED_MODEL_NAME = "text-embedding-3-small"  # hosted; whole corpus + queries go to OpenAI
EMBED_MAX_TOKENS = 8191  # this model's hard input limit


def get_embeddings() -> OpenAIEmbeddings:
    # The API key is read from the OPENAI_API_KEY env var by the underlying
    # openai client -- never hardcode it here.
    return OpenAIEmbeddings(model=EMBED_MODEL_NAME)
