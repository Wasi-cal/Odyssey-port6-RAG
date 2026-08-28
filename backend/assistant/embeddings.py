"""
embeddings.py — single source of truth for the embedding model configuration.

Architecture: hybrid. Generation (retrieval/prompt.py, gpt-4o-mini) is always
OpenAI-hosted. Embeddings have TWO available backends, selected by
config_store's embeddings/embed_provider (see resolve_embed_provider):
"openai" (text-embedding-3-small, the long-standing default -- every chunk
and query sent to OpenAI's API) or "local" (e.g. BAAI/bge-large-en-v1.5, run
on this machine via sentence-transformers, no external API call at all).
The local provider is additive -- kept alongside OpenAI's for A/B comparison
(see eval/run_eval.py runs against each), not a replacement.

Both ingestion/store.py and retrieval/store.py MUST call get_embeddings()
rather than constructing an embeddings client themselves. Documents and
queries have to be embedded by the identical model for vector similarity
between them to mean anything -- routing both call sites through one
function is what guarantees that never drifts. The two providers are also
NEVER mixed in one Chroma collection: resolve_collection_name() below keys
the collection name off the same provider, so an accidental provider
mismatch can't silently compare incompatible vector spaces.
"""

import tiktoken
from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from . import config_store
from .paths import COLLECTION_NAME, LOCAL_COLLECTION_NAME

load_dotenv()

# Fallback only -- the live value is config_settings' embeddings/embed_model_name
# (see config_store.seed_defaults and resolve_embed_model_name below), so an
# admin can change models via Postgres without a redeploy. Changing it only
# takes effect for NEWLY ingested documents; existing Chroma vectors stay in
# whatever space they were embedded in, so a real model swap still needs a
# full re-ingest, same as before this became config-driven.
EMBED_MODEL_NAME = "text-embedding-3-small"
EMBED_MAX_TOKENS = 8191  # this model's hard input limit

# Local alternative -- bge-large-en-v1.5 is trained/benchmarked for cosine
# similarity on NORMALIZED embeddings (see _get_local_embeddings), matching
# the "hnsw:space": "cosine" both Chroma stores already use.
LOCAL_EMBED_MODEL_NAME = "BAAI/bge-large-en-v1.5"

# cl100k_base is text-embedding-3-small's actual tokenizer -- same encoding
# assistant/ingestion/chunking/tokens.py already uses for chunk sizing. Only
# meaningful as a cost estimate for the OpenAI provider (the local provider
# has no per-token API cost) -- ingestion still calls this unconditionally
# for both, see pipeline.py's embed_tokens return value.
_ENCODING = tiktoken.get_encoding("cl100k_base")

# HuggingFaceEmbeddings loads the full model from disk/HF cache on
# construction -- expensive enough (seconds, real memory) that it's worth
# caching per model name rather than reconstructing on every
# get_embeddings(provider="local") call within one process (many calls
# during a single ingestion run, or every retrieval call in a long-lived
# server). OpenAIEmbeddings has no equivalent cost (just an HTTP client), so
# it isn't cached.
_local_embeddings_cache: dict[str, HuggingFaceEmbeddings] = {}


def resolve_embed_provider() -> str:
    """'openai' (default, unchanged behavior) or 'local' -- which backend
    get_embeddings() uses when no explicit provider is passed. Config-driven
    so switching doesn't need a redeploy -- see config_store.seed_defaults.
    """
    return config_store.get("embeddings", "embed_provider", "openai")


def resolve_embed_model_name() -> str:
    return config_store.get("embeddings", "embed_model_name", EMBED_MODEL_NAME)


def resolve_local_embed_model_name() -> str:
    return config_store.get("embeddings", "local_embed_model_name", LOCAL_EMBED_MODEL_NAME)


def resolve_collection_name(provider: str | None = None) -> str:
    """Which Chroma collection a given provider's vectors live in -- the two
    providers are never mixed in one collection (see module docstring), so
    this always travels together with get_embeddings(provider).
    """
    provider = provider or resolve_embed_provider()
    return LOCAL_COLLECTION_NAME if provider == "local" else COLLECTION_NAME


def _get_local_embeddings(model_name: str) -> HuggingFaceEmbeddings:
    if model_name not in _local_embeddings_cache:
        _local_embeddings_cache[model_name] = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},  # no GPU/CUDA assumption on the host
            # bge-large-en-v1.5 (and gte-large) are trained to be compared
            # via cosine similarity on normalized vectors -- must match
            # both Chroma stores' collection_metadata={"hnsw:space": "cosine"}.
            encode_kwargs={"normalize_embeddings": True},
        )
    return _local_embeddings_cache[model_name]


def get_embeddings(provider: str | None = None) -> Embeddings:
    """The active embedding backend. `provider` overrides config_store's
    embeddings/embed_provider when given -- used by the local-model A/B
    ingestion/eval runs so they can force "local" without touching the live
    config api.py's /ask path reads. Omit it for today's config-driven
    behavior, unchanged (defaults to "openai").
    """
    provider = provider or resolve_embed_provider()
    if provider == "local":
        return _get_local_embeddings(resolve_local_embed_model_name())
    # The API key is read from the OPENAI_API_KEY env var by the underlying
    # openai client -- never hardcode it here.
    return OpenAIEmbeddings(model=resolve_embed_model_name())


def count_tokens(texts: list[str]) -> int:
    """Total cl100k_base token count across all texts -- an estimate of
    what get_embeddings() actually billed for embedding them, since nothing
    in the OpenAIEmbeddings call path exposes real usage figures.
    """
    return sum(len(_ENCODING.encode(t)) for t in texts)
