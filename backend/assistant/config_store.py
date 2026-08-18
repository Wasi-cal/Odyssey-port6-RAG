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


def seed_defaults() -> None:
    """Seeds config_settings with today's hardcoded values on first ever
    startup. ON CONFLICT DO NOTHING (see db.seed_config_defaults) means this
    never overwrites a value an admin has since edited directly in Postgres,
    so it's safe to call unconditionally on every app startup.
    """
    from .retrieval.config import K, SEARCH_TYPE
    from .retrieval.prompt import (
        FALLBACK_ABUSE,
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
        ]
    )
