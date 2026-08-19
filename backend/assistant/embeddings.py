"""
embeddings.py — single source of truth for the embedding model configuration.

Architecture: all-hosted. Both embeddings (this module, text-embedding-3-small)
and generation (retrieval/prompt.py, gpt-4o-mini) are OpenAI-hosted -- every
document chunk (at ingestion) and every user query (at retrieval and
generation) is sent to OpenAI's API.

Both ingestion/store.py and retrieval/store.py MUST call get_embeddings()
rather than constructing OpenAIEmbeddings themselves. Documents and queries
have to be embedded by the identical model for vector similarity between them
to mean anything -- routing both call sites through one function is what
guarantees that never drifts.
"""

import tiktoken
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

from . import config_store

load_dotenv()

# Fallback only -- the live value is config_settings' embeddings/embed_model_name
# (see config_store.seed_defaults and resolve_embed_model_name below), so an
# admin can change models via Postgres without a redeploy. Changing it only
# takes effect for NEWLY ingested documents; existing Chroma vectors stay in
# whatever space they were embedded in, so a real model swap still needs a
# full re-ingest, same as before this became config-driven.
EMBED_MODEL_NAME = "text-embedding-3-small"
EMBED_MAX_TOKENS = 8191  # this model's hard input limit

# cl100k_base is text-embedding-3-small's actual tokenizer -- same encoding
# assistant/ingestion/chunking/tokens.py already uses for chunk sizing.
# langchain_openai's OpenAIEmbeddings doesn't surface per-call usage the way
# ChatOpenAI does, so ingestion counts tokens itself (see count_tokens
# below) to estimate embedding cost for the admin monitoring dashboard.
_ENCODING = tiktoken.get_encoding("cl100k_base")


def resolve_embed_model_name() -> str:
    return config_store.get("embeddings", "embed_model_name", EMBED_MODEL_NAME)


def get_embeddings() -> OpenAIEmbeddings:
    # The API key is read from the OPENAI_API_KEY env var by the underlying
    # openai client -- never hardcode it here.
    return OpenAIEmbeddings(model=resolve_embed_model_name())


def count_tokens(texts: list[str]) -> int:
    """Total cl100k_base token count across all texts -- an estimate of
    what get_embeddings() actually billed for embedding them, since nothing
    in the OpenAIEmbeddings call path exposes real usage figures.
    """
    return sum(len(_ENCODING.encode(t)) for t in texts)
