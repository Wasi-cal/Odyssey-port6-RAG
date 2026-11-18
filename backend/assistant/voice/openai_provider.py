"""
openai_provider.py — OpenAI Realtime API implementation of
RealtimeVoiceProvider.

This is the Phase 1 ephemeral-token logic (POST /v1/realtime/client_secrets
via the openai SDK), unchanged in behavior, just moved behind the
RealtimeVoiceProvider interface so it's switchable with DeepgramVoiceProvider
via config_store's voice/provider. Deepgram is what's actually configured
now (see config_store.seed_defaults), but this stays in place and fully
working -- reverting is voice/provider going back to "openai", not a code
change.
"""

from typing import Any

from openai import OpenAI

from .base import RealtimeVoiceProvider, SessionCredentials, ToolSpec


def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    """Flat shape (type/name/description/parameters at the top level, NOT
    nested under a "function" key) -- confirmed against the installed
    openai SDK's RealtimeFunctionToolParam type, not the older Chat
    Completions tool-call shape.
    """
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool["description"],
        "parameters": tool["parameters"],
    }


class OpenAIVoiceProvider(RealtimeVoiceProvider):
    def __init__(
        self,
        model: str,
        voice: str,
        instructions: str,
        temperature: float | None = None,
        speed: float | None = None,
    ):
        self._model = model
        self._voice = voice
        self._instructions = instructions
        # Post-processing playback-speed multiplier (0.25-1.5, 1.0 =
        # OpenAI's default) -- see defaults.py's OPENAI_REALTIME_SPEED.
        # Unlike `temperature` below, this IS a real, currently-supported
        # field (RealtimeAudioConfigOutput.speed).
        self._speed = speed
        # `temperature` USED to be accepted at the session level (see
        # defaults.py's bug-fix note #8, "personality inconsistent across
        # restarts") but the current GA Realtime API
        # (RealtimeSessionCreateRequest, openai-python 1.109.1) has no such
        # field at all -- sending it 400s with "Unknown parameter:
        # 'session.temperature'". Kept as a constructor param (still read
        # from config_store, still passed in by callers) so config/call
        # sites don't need to change, but intentionally never forwarded to
        # the API below. There is currently no supported way to pin
        # sampling temperature on this API; some residual persona/tone
        # variance across sessions is therefore inherent to this provider,
        # not fixable from our side.
        self._temperature = temperature

    def create_session(self, tools: list[ToolSpec]) -> SessionCredentials:
        """Mints a short-lived OpenAI Realtime client secret (~1 min) for
        the frontend to open a WebRTC connection DIRECTLY to OpenAI. The
        real OPENAI_API_KEY never reaches the browser; only this
        session-scoped credential does. The session (model, voice,
        persona instructions, and tools) is fully configured HERE, before
        minting the secret -- the browser can't change the model or add
        tools, only use the exact session this secret was scoped to.
        """
        try:
            client = OpenAI()
            secret = client.realtime.client_secrets.create(
                session={
                    "type": "realtime",
                    "model": self._model,
                    "instructions": self._instructions,
                    "audio": {
                        "input": {"transcription": {"model": "whisper-1"}},
                        "output": {
                            "voice": self._voice,
                            **({"speed": self._speed} if self._speed is not None else {}),
                        },
                    },
                    "tools": [_to_openai_tool(t) for t in tools],
                    "tool_choice": "auto",
                },
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create OpenAI voice session: {e}") from e

        return SessionCredentials(
            provider="openai",
            credential=secret.value,
            expires_at=secret.expires_at,
            connection={"model": self._model, "voice": self._voice},
        )
