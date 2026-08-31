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

    # voice_provider_credentials / deployment_settings are their own
    # normalized tables (assistant/db.py), not config_settings rows -- but
    # they ride this exact same Redis cache-aside path, under synthetic
    # categories, so every reader still goes through one get()/get_all()
    # regardless of which table a value actually lives in. NOTE: unlike
    # config_settings' prompts/model names, these ARE secrets -- caching
    # them here means they sit in Redis as plaintext for up to
    # _CACHE_TTL_SECONDS, same exposure profile as everything else this
    # cache holds. Deliberate tradeoff for this deployment; don't assume it
    # generalizes to a stricter security posture without reconsidering it.
    for row in db.list_voice_provider_credentials():
        secrets = config.setdefault("voice_secrets", {})
        secrets[f"{row['provider']}_api_key"] = row["api_key"]
        if row["llm_proxy_secret"] is not None:
            secrets[f"{row['provider']}_llm_proxy_secret"] = row["llm_proxy_secret"]
    deployment = db.get_deployment_settings()
    if deployment["public_base_url"] is not None:
        config.setdefault("voice_infra", {})["public_base_url"] = deployment["public_base_url"]

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


def get_voice_secret(provider: str, field: str, default=None):
    """`field` is 'api_key' or 'llm_proxy_secret' -- see
    voice_provider_credentials. Same cache-aside/fallback-default contract
    as get().
    """
    return get(category="voice_secrets", key=f"{provider}_{field}", default=default)


def get_public_base_url(default=None):
    return get(category="voice_infra", key="public_base_url", default=default)


def _invalidate() -> None:
    try:
        _redis.delete(_CACHE_KEY)
    except redis.exceptions.RedisError:
        pass  # Next get_all() falls back to Postgres directly either way.


def set(category: str, key: str, value) -> None:
    """Writes one setting straight to Postgres (upsert, unlike
    seed_defaults' ON CONFLICT DO NOTHING) and invalidates the cache so the
    change is visible immediately -- not just after the next
    _CACHE_TTL_SECONDS refresh. Used by in-app editors (e.g. the admin app's
    change-password form) as the alternative to editing config_settings by
    hand in psql. NOT for voice_secrets/voice_infra -- those live in their
    own normalized tables (assistant/db.py), not config_settings; use
    set_voice_secret()/set_public_base_url() for them instead.
    """
    db.set_config_value(category, key, value)
    _invalidate()


def set_voice_secret(provider: str, *, api_key: str, llm_proxy_secret: str | None = None) -> None:
    """Upserts a realtime voice provider's credential row
    (voice_provider_credentials, not config_settings) and invalidates the
    shared cache. `llm_proxy_secret` only matters for 'deepgram' -- see
    db.set_voice_provider_credential.
    """
    db.set_voice_provider_credential(provider, api_key=api_key, llm_proxy_secret=llm_proxy_secret)
    _invalidate()


def set_public_base_url(public_base_url: str) -> None:
    """Upserts the singleton deployment_settings row and invalidates the
    shared cache.
    """
    db.set_deployment_setting(public_base_url=public_base_url)
    _invalidate()


def seed_defaults() -> None:
    """Seeds config_settings with today's hardcoded values on first ever
    startup. ON CONFLICT DO NOTHING (see db.seed_config_defaults) means this
    never overwrites a value an admin has since edited directly in Postgres,
    so it's safe to call unconditionally on every app startup.
    """
    from .retrieval.config import SEARCH_TYPE
    from .voice import defaults as voice_defaults
    from .retrieval.prompt import (
        FALLBACK_ABUSE,
        FALLBACK_ACKNOWLEDGEMENT,
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
                "key": "fallback_acknowledgement",
                "value": FALLBACK_ACKNOWLEDGEMENT,
                "description": (
                    "Returned for a greeting/thanks/small talk with no real question in it, "
                    "same routing category as fallback_greeting, but used instead of it once a "
                    "conversation is already underway -- prevents a short reply like 'great' or "
                    "'thanks' mid-conversation from coming back as the cold-start self-introduction."
                ),
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
                "category": "retrieval",
                "key": "k",
                # 15, not the module constant K (still 10 -- see
                # retrieval/config.py, kept as the fallback used only if the
                # config subsystem itself is unreachable). Bumped from 10
                # when switching embed_provider to "local" below: the local
                # (bge-large) embedding space ranks some correct-but-
                # narrowly-worded chunks just outside a k=10 MMR window
                # (confirmed via direct rank inspection -- see git history/
                # PR description) where OpenAI's embeddings keep them
                # inside it. k=15 recovered full parity with the OpenAI
                # baseline on the 44-question eval (answer correctness
                # 0.82 both ways) with no measurable retrieval-latency cost
                # and no new regressions across the other 41 questions.
                "value": 15,
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
            {
                "category": "embeddings",
                "key": "embed_provider",
                # Switched to "local" (bge-large-en-v1.5, see embeddings.py)
                # after a 44-question --judge A/B eval showed full parity
                # with the OpenAI provider at k=15 (retrieval.k above),
                # plus a ~20-55x lower retrieval latency (no per-query
                # OpenAI API round trip). "openai" and its collection
                # (paths.COLLECTION_NAME) are left fully in place and
                # selectable -- reverting is this one value going back to
                # "openai", not a re-ingest or a code change.
                "value": "local",
                "description": (
                    "Which embedding backend assistant/embeddings.py's get_embeddings() uses: "
                    "'openai' (default, text-embedding-3-small, hosted) or 'local' (e.g. "
                    "BAAI/bge-large-en-v1.5, runs on this machine via sentence-transformers, no "
                    "external API call). Each provider reads/writes its own separate Chroma "
                    "collection (see resolve_collection_name) -- switching this requires a full "
                    "re-ingest into that provider's collection before it has anything to serve."
                ),
            },
            {
                "category": "embeddings",
                "key": "local_embed_model_name",
                "value": "BAAI/bge-large-en-v1.5",
                "description": (
                    "Hugging Face model id used when embed_provider is 'local' "
                    "(assistant/embeddings.py). Changing this only affects newly-ingested "
                    "documents, same as embed_model_name for the OpenAI provider."
                ),
            },
            {
                "category": "voice",
                "key": "provider",
                # Deepgram is the vendor actually in use now -- OpenAI's
                # Realtime provider (Phase 1) is left fully in place and
                # selectable behind the same RealtimeVoiceProvider
                # interface (assistant/voice/), same "revert is a config
                # value, not a re-deploy" pattern as embed_provider above.
                "value": voice_defaults.VOICE_PROVIDER,
                "description": (
                    "Which realtime voice backend api.py's POST /voice/session uses "
                    "(assistant/voice/__init__.py's get_voice_provider()): 'openai' "
                    "(Realtime API, WebRTC, Phase 1) or 'deepgram' (Voice Agent API, "
                    "bring-your-own-LLM mode)."
                ),
            },
            {
                "category": "voice",
                "key": "session_instructions",
                "value": voice_defaults.VOICE_SESSION_INSTRUCTIONS,
                "description": (
                    "Persona + tool-use system prompt sent to the active voice provider "
                    "(OpenAI's session `instructions`, Deepgram's `think.prompt`). Deliberately "
                    "excludes the opening greeting -- see the separate 'greeting' key below; "
                    "get_voice_provider() splices the two together at request time so editing "
                    "one doesn't require also editing the other."
                ),
            },
            {
                "category": "voice",
                "key": "greeting",
                "value": voice_defaults.VOICE_GREETING,
                "description": (
                    "What the voice agent says first, before the employee speaks. Deepgram "
                    "speaks this directly via its own agent.greeting field (no LLM round trip); "
                    "OpenAI has no equivalent field, so it's folded into session_instructions "
                    "instead, paired with the frontend triggering an initial response.create."
                ),
            },
            {
                "category": "voice",
                "key": "openai_model",
                "value": voice_defaults.OPENAI_REALTIME_MODEL,
                "description": "OpenAI Realtime API model id, used only when voice/provider is 'openai'.",
            },
            {
                "category": "voice",
                "key": "openai_voice",
                "value": voice_defaults.OPENAI_REALTIME_VOICE,
                "description": (
                    "OpenAI Realtime TTS voice name (see openai.types.realtime's "
                    "RealtimeAudioConfigOutputParam.voice), used only when voice/provider is 'openai'."
                ),
            },
            {
                "category": "voice",
                "key": "deepgram_think_model",
                "value": voice_defaults.DEEPGRAM_THINK_MODEL,
                "description": (
                    "Chat-completions model Deepgram's agent.think stage calls through "
                    "api.py's /voice/llm-proxy (assistant/voice/deepgram_provider.py). Used "
                    "only when voice/provider is 'deepgram'."
                ),
            },
            {
                "category": "voice",
                "key": "deepgram_listen_model",
                "value": voice_defaults.DEEPGRAM_LISTEN_MODEL,
                "description": (
                    "Deepgram speech-to-text model for agent.listen (e.g. flux-general-en, "
                    "a v2/Flux model -- assistant/voice/deepgram_provider.py always pairs this "
                    "with version: 'v2'). Used only when voice/provider is 'deepgram'."
                ),
            },
            {
                "category": "voice",
                "key": "deepgram_speak_model",
                "value": voice_defaults.DEEPGRAM_SPEAK_MODEL,
                "description": (
                    "Deepgram text-to-speech model for agent.speak (an aura-*-en or "
                    "flux-*-en voice). Used only when voice/provider is 'deepgram'."
                ),
            },
            {
                "category": "voice",
                "key": "deepgram_think_temperature",
                "value": voice_defaults.DEEPGRAM_THINK_TEMPERATURE,
                "description": (
                    "Sampling temperature routers/voice.py's llm_proxy pins on every OpenAI "
                    "chat-completions request it forwards for the Deepgram BYO-LLM think stage "
                    "-- see assistant/voice/defaults.py's bug-fix note (#8, 'personality "
                    "inconsistent every restart') for why this exists: Deepgram's own think "
                    "request never carried a temperature at all, so the same persona "
                    "instructions were being sampled at OpenAI's default (1.0). Used only when "
                    "voice/provider is 'deepgram'."
                ),
            },
            {
                "category": "voice",
                "key": "openai_temperature",
                "value": voice_defaults.OPENAI_REALTIME_TEMPERATURE,
                "description": (
                    "NOT currently forwarded to the API -- the GA Realtime API's "
                    "RealtimeSessionCreateRequest has no session-level temperature field at "
                    "all (confirmed live: sending one 400s the request). Kept only so "
                    "config/call sites don't need to change if OpenAI ever adds an equivalent "
                    "knob. Used only when voice/provider is 'openai'."
                ),
            },
            {
                "category": "voice",
                "key": "openai_speed",
                "value": voice_defaults.OPENAI_REALTIME_SPEED,
                "description": (
                    "Post-processing playback-speed multiplier on the OpenAI Realtime "
                    "session's spoken output (RealtimeAudioConfigOutput.speed; 0.25-1.5, "
                    "1.0 = OpenAI's default). 'marin' reads noticeably fast at 1.0 -- 0.9 "
                    "was still reported too fast live, settled on 0.8. Used only when "
                    "voice/provider is 'openai'."
                ),
            },
        ]
    )
