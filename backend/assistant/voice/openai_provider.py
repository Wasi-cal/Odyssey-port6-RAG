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
    def __init__(self, model: str, voice: str, instructions: str, temperature: float | None = None):
        self._model = model
        self._voice = voice
        self._instructions = instructions
        # See defaults.py's bug-fix note (#8, "personality inconsistent
        # across restarts") -- pins sampling temperature on the Realtime
        # session so the same persona instructions aren't sampled at
        # OpenAI's much higher default (0.8) every time. None (only if a
        # caller explicitly constructs this without one) leaves the field
        # out of the session dict below, falling back to OpenAI's own
        # default rather than sending an invalid value.
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
                        "output": {"voice": self._voice},
                    },
                    "tools": [_to_openai_tool(t) for t in tools],
                    "tool_choice": "auto",
                    **({"temperature": self._temperature} if self._temperature is not None else {}),
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
