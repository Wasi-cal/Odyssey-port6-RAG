"""
assistant/voice — realtime voice provider selection.

Same config-driven pattern as assistant/embeddings.py: everything about the
voice session that isn't a secret or a network address -- which vendor
(config_store's voice/provider), persona instructions, the opening
greeting, and each vendor's model/voice choices -- lives in config_store
(Postgres, hot-reloadable, no redeploy) rather than as Python constants.
Only genuine secrets and infra addresses (DEEPGRAM_API_KEY, OPENAI_API_KEY,
DEEPGRAM_LLM_PROXY_SECRET, PUBLIC_BASE_URL) stay in the environment -- same
line config_store already draws for JWT_SECRET/DATABASE_URL/REDIS_URL.

api.py calls get_voice_provider() with no arguments; this module resolves
everything else itself and hands back a fully-configured provider, ready
for .create_session(tools).
"""

from .. import config_store
from . import defaults
from .base import RealtimeVoiceProvider, SessionCredentials, ToolSpec
from .deepgram_provider import DeepgramVoiceProvider
from .openai_provider import OpenAIVoiceProvider

__all__ = [
    "RealtimeVoiceProvider",
    "SessionCredentials",
    "ToolSpec",
    "resolve_voice_provider_name",
    "resolve_session_instructions",
    "resolve_greeting",
    "resolve_openai_model",
    "resolve_openai_voice",
    "resolve_deepgram_think_model",
    "resolve_deepgram_listen_model",
    "resolve_deepgram_speak_model",
    "resolve_deepgram_think_temperature",
    "resolve_openai_temperature",
    "get_voice_provider",
]


def resolve_voice_provider_name() -> str:
    """'openai' or 'deepgram' ("deepgram" is the current default -- see
    config_store.seed_defaults) -- which vendor get_voice_provider()
    constructs. Config-driven so switching doesn't need a redeploy.
    """
    return config_store.get("voice", "provider", defaults.VOICE_PROVIDER)


def resolve_session_instructions() -> str:
    """Persona + tool-use guidance sent to whichever provider as its
    system prompt (OpenAI's `instructions`, Deepgram's `think.prompt`).
    Deliberately excludes the greeting -- see resolve_greeting().
    """
    return config_store.get("voice", "session_instructions", defaults.VOICE_SESSION_INSTRUCTIONS)


def resolve_greeting() -> str:
    """What the agent says first, before the employee speaks."""
    return config_store.get("voice", "greeting", defaults.VOICE_GREETING)


def resolve_openai_model() -> str:
    return config_store.get("voice", "openai_model", defaults.OPENAI_REALTIME_MODEL)


def resolve_openai_voice() -> str:
    return config_store.get("voice", "openai_voice", defaults.OPENAI_REALTIME_VOICE)


def resolve_deepgram_think_model() -> str:
    return config_store.get("voice", "deepgram_think_model", defaults.DEEPGRAM_THINK_MODEL)


def resolve_deepgram_listen_model() -> str:
    return config_store.get("voice", "deepgram_listen_model", defaults.DEEPGRAM_LISTEN_MODEL)


def resolve_deepgram_speak_model() -> str:
    return config_store.get("voice", "deepgram_speak_model", defaults.DEEPGRAM_SPEAK_MODEL)


def resolve_deepgram_think_temperature() -> float:
    """Sampling temperature routers/voice.py's llm_proxy pins on every
    OpenAI chat-completions request it forwards for the Deepgram BYO-LLM
    path -- see defaults.py's bug-fix note (#8) for why this exists: the
    same fixed persona instructions were previously sampled at whatever
    temperature Deepgram's own think request happened to carry (observed:
    none at all, i.e. OpenAI's own default of 1.0), which read as an
    inconsistent "personality" call to call.
    """
    return config_store.get("voice", "deepgram_think_temperature", defaults.DEEPGRAM_THINK_TEMPERATURE)


def resolve_openai_temperature() -> float:
    """Read from config_store for backward compatibility but NOT actually
    forwarded to the API by OpenAIVoiceProvider -- see defaults.py's
    OPENAI_REALTIME_TEMPERATURE comment: the current Realtime API has no
    session-level temperature field at all.
    """
    return config_store.get("voice", "openai_temperature", defaults.OPENAI_REALTIME_TEMPERATURE)


def resolve_openai_speed() -> float:
    """Playback-speed multiplier for the OpenAI Realtime session's spoken
    output -- see defaults.py's OPENAI_REALTIME_SPEED.
    """
    return config_store.get("voice", "openai_speed", defaults.OPENAI_REALTIME_SPEED)


def get_voice_provider() -> RealtimeVoiceProvider:
    """The active realtime voice provider, fully configured from
    config_store. Every value this reads is hot-reloadable (config_store's
    usual ~30s cache TTL, see config_store.get) -- editing a prompt, the
    greeting, or a model choice in Postgres takes effect on the next voice
    session with no redeploy, same as SYSTEM_PROMPT for /ask.
    """
    provider = resolve_voice_provider_name()
    instructions = resolve_session_instructions()
    greeting = resolve_greeting()

    if provider == "deepgram":
        return DeepgramVoiceProvider(
            instructions=instructions,
            think_model=resolve_deepgram_think_model(),
            listen_model=resolve_deepgram_listen_model(),
            speak_model=resolve_deepgram_speak_model(),
            greeting=greeting,
        )

    # OpenAI has no dedicated greeting field (unlike Deepgram's
    # agent.greeting) -- fold the greeting-trigger sentence into
    # instructions instead; the frontend's response.create sent on
    # session.created (hooks/voice/openaiConnection.ts) is what actually
    # makes the model say it.
    openai_instructions = (
        f"{instructions} As soon as the session starts, before the employee "
        f'says anything, greet them by saying exactly: "{greeting}" -- then '
        "wait for their reply."
    )
    return OpenAIVoiceProvider(
        model=resolve_openai_model(),
        voice=resolve_openai_voice(),
        instructions=openai_instructions,
        temperature=resolve_openai_temperature(),
        speed=resolve_openai_speed(),
    )
