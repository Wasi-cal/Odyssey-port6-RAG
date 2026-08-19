"""Live, hot-reloadable app configuration -- system prompts, retrieval
tuning, and anything else that shouldn't need a code change and a redeploy
to adjust.

Postgres (assistant.db's config_settings table) is the source of truth --
edit a row there directly (e.g. via psql) and it takes effect on its own.
Reads never hit Postgres directly though: they go through a single Redis key
holding the whole config as one JSON object, refreshed from Postgres on a
short TTL (cache-aside) -- so a direct edit becomes visible everywhere
within _CACHE_TTL_SECONDS, and Postgres being briefly slow/unavailable
doesn't add latency (or a hard failure) to every request that reads config.
"""

import json
import os

import redis

from . import db

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_CACHE_KEY = "docassist:config"
_CACHE_TTL_SECONDS = 30

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _load_from_postgres() -> dict:
    config: dict = {}
    for row in db.list_config_settings():
        config.setdefault(row["category"], {})[row["key"]] = row["value"]
    return config


def get_all() -> dict:
    """The full config, as a {category: {key: value}} dict. Prefer get() for
    a single value -- this is mainly for the /config debug endpoint.
    """
    try:
        cached = _redis.get(_CACHE_KEY)
        if cached is not None:
            return json.loads(cached)
    except redis.exceptions.RedisError:
        pass  # Redis down -- fall through to Postgres directly.

    config = _load_from_postgres()
    try:
        _redis.set(_CACHE_KEY, json.dumps(config), ex=_CACHE_TTL_SECONDS)
    except redis.exceptions.RedisError:
        pass  # Still serve the freshly-loaded config even if caching it failed.
    return config


def get(category: str, key: str, default=None):
    """A single setting. Callers always pass the current hardcoded value as
    `default`, so a total config-subsystem outage (Redis AND Postgres both
    unreachable) degrades to today's fixed behavior instead of an error.
    """
    try:
        return get_all().get(category, {}).get(key, default)
    except Exception:
        return default


def set(category: str, key: str, value) -> None:
    """Writes one setting straight to Postgres (upsert, unlike
    seed_defaults' ON CONFLICT DO NOTHING) and invalidates the cache so the
    change is visible immediately -- not just after the next
    _CACHE_TTL_SECONDS refresh. Used by in-app editors (e.g. the admin app's
    change-password form) as the alternative to editing config_settings by
    hand in psql.
    """
    db.set_config_value(category, key, value)
    try:
        _redis.delete(_CACHE_KEY)
    except redis.exceptions.RedisError:
        pass  # Next get_all() falls back to Postgres directly either way.


def seed_defaults() -> None:
    """Seeds config_settings with today's hardcoded values on first ever
    startup. ON CONFLICT DO NOTHING (see db.seed_config_defaults) means this
    never overwrites a value an admin has since edited directly in Postgres,
    so it's safe to call unconditionally on every app startup.
    """
    from .retrieval.config import K, SEARCH_TYPE
    from .retrieval.prompt import (
        CONDENSE_QUESTION_SYSTEM_PROMPT,
        FALLBACK_ABUSE,
        FALLBACK_DANGEROUS,
        FALLBACK_GIBBERISH,
        FALLBACK_GREETING,
        FALLBACK_HANDOFF,
        FALLBACK_UNANSWERED,
        FALLBACK_UNCLEAR,
        FALLBACK_UNRELATED,
        GENERATION_MODEL,
        GENERATION_TEMPERATURE,
        SYSTEM_PROMPT,
    )

    db.seed_config_defaults(
        [
            {
                "category": "generation",
                "key": "system_prompt",
                "value": SYSTEM_PROMPT,
                "description": "Grounding system prompt sent to the LLM for every /ask call.",
            },
            {
                "category": "generation",
                "key": "fallback_greeting",
                "value": FALLBACK_GREETING,
                "description": "Returned for a greeting/thanks/small talk with no real question in it.",
            },
            {
                "category": "generation",
                "key": "fallback_handoff",
                "value": FALLBACK_HANDOFF,
                "description": "Returned when the user asks to talk to a human/agent instead of this assistant.",
            },
            {
                "category": "generation",
                "key": "fallback_unclear",
                "value": FALLBACK_UNCLEAR,
                "description": "Returned when the question itself is too unclear/ambiguous to answer.",
            },
            {
                "category": "generation",
                "key": "fallback_gibberish",
                "value": FALLBACK_GIBBERISH,
                "description": "Returned when the input has no discernible words or intent at all.",
            },
            {
                "category": "generation",
                "key": "fallback_abuse",
                "value": FALLBACK_ABUSE,
                "description": (
                    "Returned when OpenAI's Moderation API flags the input -- this one never "
                    "reaches the LLM at all, so editing it takes effect without any generation call."
                ),
            },
            {
                "category": "generation",
                "key": "fallback_unrelated",
                "value": FALLBACK_UNRELATED,
                "description": "Returned when the question is clearly outside the document set's scope.",
            },
            {
                "category": "generation",
                "key": "fallback_unanswered",
                "value": FALLBACK_UNANSWERED,
                "description": (
                    "Returned when the question is in scope but not covered by the "
                    "documents -- includes the HR escalation email, edit it here to change that address."
                ),
            },
            {
                "category": "generation",
                "key": "fallback_dangerous",
                "value": FALLBACK_DANGEROUS,
                "description": (
                    "Returned when the model itself judges the request could help cause "
                    "real-world harm (rule 2(g) in the system prompt) -- checked before every "
                    "other rule, including 'it's in the context.' Distinct from fallback_abuse, "
                    "which is the pre-LLM Moderation API's judgment on the input text itself."
                ),
            },
            {
                "category": "generation",
                "key": "model",
                "value": GENERATION_MODEL,
                "description": "OpenAI chat model used for answer generation.",
            },
            {
                "category": "generation",
                "key": "temperature",
                "value": GENERATION_TEMPERATURE,
                "description": "Generation temperature (0 = deterministic).",
            },
            {
                "category": "generation",
                "key": "history_messages",
                "value": 12,
                "description": (
                    "How many of the most recent chat messages (user + assistant, not just "
                    "turns) are given to the model as prior context on every /ask call -- lets "
                    "it resolve follow-up questions ('what about part-time employees?') against "
                    "what was already discussed. 0 disables chat history entirely."
                ),
            },
            {
                "category": "generation",
                "key": "condense_question_prompt",
                "value": CONDENSE_QUESTION_SYSTEM_PROMPT,
                "description": (
                    "System prompt used to rewrite a follow-up question into a standalone "
                    "retrieval query before the vector search runs (see retrieval/qa.py's "
                    "_condense_question) -- only affects what's searched for, not the wording "
                    "the generation model sees or answers against."
                ),
            },
            {
                "category": "retrieval",
                "key": "k",
                "value": K,
                "description": "Number of chunks retrieved per question.",
            },
            {
                "category": "retrieval",
                "key": "search_type",
                "value": SEARCH_TYPE,
                "description": "Chroma retriever search_type, e.g. 'mmr' or 'similarity'.",
            },
            {
                "category": "auth",
                "key": "admin_password",
                "value": os.environ.get("ADMIN_PASSWORD", ""),
                "description": (
                    "Shared password for the separate admin app's login (assistant/auth.py's "
                    "verify_admin_password). Seeded once from env ADMIN_PASSWORD; edit this row "
                    "directly to change it afterwards -- never returned by GET /config."
                ),
            },
            {
                "category": "auth",
                "key": "jwt_expiry_days",
                "value": int(os.environ.get("JWT_EXPIRY_DAYS", "7")),
                "description": "How long a chatbot login stays valid before re-login is required.",
            },
            {
                "category": "auth",
                "key": "admin_jwt_expiry_hours",
                "value": int(os.environ.get("ADMIN_JWT_EXPIRY_HOURS", "12")),
                "description": "How long an admin app login stays valid before re-login is required.",
            },
            {
                "category": "rate_limit",
                "key": "max_attempts",
                "value": 5,
                "description": "Failed logins (per username or per IP) before a 5-minute lockout.",
            },
            {
                "category": "rate_limit",
                "key": "lockout_seconds",
                "value": 5 * 60,
                "description": "Lockout duration, in seconds, once max_attempts is hit.",
            },
            {
                "category": "pricing",
                "key": "chat_input_price_per_token",
                "value": 0.15 / 1_000_000,
                "description": "USD per prompt token, for the admin monitoring dashboard's cost estimate.",
            },
            {
                "category": "pricing",
                "key": "chat_output_price_per_token",
                "value": 0.60 / 1_000_000,
                "description": "USD per completion token, for the admin monitoring dashboard's cost estimate.",
            },
            {
                "category": "pricing",
                "key": "embedding_price_per_token",
                "value": 0.02 / 1_000_000,
                "description": "USD per embedded token, for the admin monitoring dashboard's cost estimate.",
            },
            {
                "category": "embeddings",
                "key": "embed_model_name",
                "value": "text-embedding-3-small",
                "description": (
                    "OpenAI embedding model (assistant/embeddings.py). Changing this only affects "
                    "newly-ingested documents -- existing Chroma vectors need a full re-ingest to match."
                ),
            },
        ]
    )
