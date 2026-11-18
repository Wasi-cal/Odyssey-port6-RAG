"""
deepgram_provider.py — Deepgram Voice Agent API implementation of
RealtimeVoiceProvider, running in "bring-your-own-LLM" mode (agent.think
calls back into OUR OWN backend, which then calls OpenAI server-side --
see IMPORTANT below for why it isn't pointed at OpenAI directly).

Session shape confirmed against Deepgram's current docs (developers.
deepgram.com), not guessed:

- Agent WebSocket: wss://agent.deepgram.com/v1/agent/converse. The
  frontend opens this directly and sends a `Settings` message first --
  same "backend configures, browser connects" split as the OpenAI
  provider.
- Ephemeral credential: Deepgram's token-based auth grant endpoint,
  POST https://api.deepgram.com/v1/auth/grant, called here with the real
  DEEPGRAM_API_KEY (Authorization: Token <key>) to mint a short-lived JWT
  (`access_token`, capped at 3600s TTL) safe to hand to the browser. The
  browser uses it as `Authorization: Bearer <access_token>` on the agent
  WebSocket -- the real API key never reaches it, same guarantee as
  OpenAI's client_secret.

IMPORTANT -- why agent.think.endpoint points at OUR backend, not OpenAI:
unlike OpenAI's client_secrets.create (which binds instructions/tools into
the ephemeral token server-side), Deepgram has no equivalent -- the
Settings message (including agent.think.endpoint.headers) is transmitted
by whoever holds the WebSocket, which is the BROWSER. Putting the real
OPENAI_API_KEY in those headers would expose it to browser devtools/
network tab, exactly the leak this interface exists to prevent. So
endpoint.url instead targets api.py's POST /voice/llm-proxy (this
backend, at PUBLIC_BASE_URL), authenticated with a separate
DEEPGRAM_LLM_PROXY_SECRET that's safe to expose -- it only authorizes
calling our own proxy, which holds OPENAI_API_KEY server-side and is the
only thing that ever calls OpenAI. See api.py's llm_proxy for the other
half of this.

CONFIRMED LIVE (raw websocket + InjectUserMessage test against Deepgram's
real agent endpoint): the think request Deepgram sends to endpoint.url is
OpenAI chat-completions-compatible AND sets `"stream": true` -- api.py's
llm_proxy must stream the response through byte-for-byte rather than
buffering and JSON-decoding it (an earlier non-streaming version 500'd on
every real request for exactly this reason).
"""

import time
import uuid
from typing import Any

import requests

from .. import config_store
from .base import RealtimeVoiceProvider, SessionCredentials, ToolSpec
from .defaults import DEEPGRAM_LISTEN_MODEL, DEEPGRAM_SPEAK_MODEL, DEEPGRAM_THINK_MODEL

_GRANT_URL = "https://api.deepgram.com/v1/auth/grant"
_AGENT_WEBSOCKET_URL = "wss://agent.deepgram.com/v1/agent/converse"

# Deepgram's max supported grant lifetime (see docs) -- long enough that a
# slow browser handshake never races the token expiring mid-connect, short
# enough to bound exposure if a minted token were ever intercepted.
_GRANT_TTL_SECONDS = 3600


def _to_deepgram_function(tool: ToolSpec) -> dict[str, Any]:
    """agent.think.functions entries -- deliberately no `endpoint` key, so
    Deepgram surfaces the call to the frontend as a client-side function
    call (same as OpenAI's tool_choice flow) rather than invoking an HTTP
    endpoint itself. The browser's Deepgram SDK handler is what actually
    calls POST /voice/ask, mirroring the OpenAI provider's tool-call path.
    """
    return {
        "name": tool["name"],
        "description": tool["description"],
        "parameters": tool["parameters"],
    }


class DeepgramVoiceProvider(RealtimeVoiceProvider):
    def __init__(
        self,
        instructions: str,
        think_model: str = DEEPGRAM_THINK_MODEL,
        listen_model: str = DEEPGRAM_LISTEN_MODEL,
        speak_model: str = DEEPGRAM_SPEAK_MODEL,
        greeting: str | None = None,
    ):
        self._instructions = instructions
        self._think_model = think_model
        self._listen_model = listen_model
        self._speak_model = speak_model
        self._greeting = greeting

    def create_session(self, tools: list[ToolSpec]) -> SessionCredentials:
        # Read fresh on every call (config_store's usual cache-aside, ~30s
        # TTL) rather than at construction -- rotating a key in
        # voice_provider_credentials or deployment_settings takes effect on
        # the next voice session with no redeploy, same as every other
        # config_store-backed value.
        api_key = config_store.get_voice_secret("deepgram", "api_key")
        if not api_key:
            raise RuntimeError(
                "No Deepgram api_key set in voice_provider_credentials -- "
                "call config_store.set_voice_secret('deepgram', api_key=...)."
            )
        public_base_url = config_store.get_public_base_url()
        proxy_secret = config_store.get_voice_secret("deepgram", "llm_proxy_secret")
        if not public_base_url or not proxy_secret:
            raise RuntimeError(
                "deployment_settings.public_base_url and voice_provider_credentials's "
                "deepgram llm_proxy_secret must both be set for the deepgram voice "
                "provider -- Deepgram's servers call agent.think.endpoint directly, "
                "so it must be a publicly reachable URL (see api.py's llm_proxy)."
            )

        try:
            resp = requests.post(
                _GRANT_URL,
                headers={"Authorization": f"Token {api_key}"},
                json={"ttl_seconds": _GRANT_TTL_SECONDS},
                timeout=10,
            )
            resp.raise_for_status()
            grant = resp.json()
        except Exception as e:
            raise RuntimeError(f"Failed to create Deepgram voice session: {e}") from e

        access_token = grant["access_token"]
        expires_in = grant.get("expires_in", _GRANT_TTL_SECONDS)

        settings = {
            "type": "Settings",
            # Explicit, unconditional opt-out of Deepgram's Model Improvement
            # Partnership Program -- confirmed against Deepgram's docs
            # (developers.deepgram.com/docs/the-deepgram-model-improvement-
            # partnership-program) that customers are NOT auto-enrolled in
            # that program (it requires a separate contractual opt-IN), so
            # this deployment's voice audio was never used for model
            # training even before this flag was added. Set anyway as a
            # defense-in-depth guarantee, same reasoning as this file's
            # other hardening: don't rely solely on "we were never enrolled
            # in the first place" when a one-line, always-on flag makes it
            # contractually explicit on every single session instead. Per
            # Deepgram's docs this also shortens retention for this data to
            # only as long as needed to process the request (no
            # "fractional increments... for continued improvement" bucket).
            "mip_opt_out": True,
            "audio": {
                "input": {"encoding": "linear16", "sample_rate": 24000},
                # sample_rate spelled out explicitly (rather than relying
                # on a default) so the frontend's playback code knows
                # exactly what rate to schedule decoded PCM frames at.
                "output": {"encoding": "linear16", "sample_rate": 24000},
            },
            "agent": {
                # version "v2" required for flux-* models (confirmed against
                # the deepgram-js-sdk's DeepgramListenProviderV2 type) --
                # v1 (Nova) models omit this field entirely.
                "listen": {"provider": {"type": "deepgram", "version": "v2", "model": self._listen_model}},
                "think": {
                    # BYO LLM -- endpoint.url points at OUR OWN backend
                    # (api.py's POST /voice/llm-proxy), NOT OpenAI directly.
                    # This Settings message is transmitted by the browser
                    # (see module docstring's IMPORTANT section), so
                    # endpoint.headers must never carry the real
                    # OPENAI_API_KEY -- proxy_secret is a separate,
                    # proxy-scoped credential that's safe for the browser
                    # to see; only api.py's llm_proxy holds the real key.
                    "provider": {"type": "open_ai", "model": self._think_model},
                    "endpoint": {
                        # voice_session_id: Deepgram's think request carries
                        # NO session/conversation identifier of its own
                        # (confirmed by inspecting a live request payload --
                        # it's just {model, stream, messages, tools}) -- this
                        # query param is the only channel available to
                        # correlate every /voice/llm-proxy call for this
                        # realtime session back to one conversation in the
                        # log (see routers/voice.py's llm_proxy).
                        "url": f"{public_base_url.rstrip('/')}/voice/llm-proxy?voice_session_id={uuid.uuid4()}",
                        "headers": {"Authorization": f"Bearer {proxy_secret}"},
                    },
                    "functions": [_to_deepgram_function(t) for t in tools],
                    "prompt": self._instructions,
                },
                # version "v2" required for flux-* speak models, same as
                # listen above (confirmed against @deepgram/sdk's shipped
                # Deepgram (TTS provider) type: "Defaults to v1 [Aura] when
                # omitted... use v2 with a flux-* model") -- aura-* models
                # omit this field entirely, matching their v1 default.
                "speak": {
                    "provider": {
                        "type": "deepgram",
                        **({"version": "v2"} if self._speak_model.startswith("flux-") else {}),
                        "model": self._speak_model,
                    }
                },
                # Spoken by the agent immediately once the session opens,
                # before the employee says anything -- confirmed field
                # (AgentV1Settings.Agent.greeting) from @deepgram/sdk's
                # shipped types. Delivered directly through the speak
                # provider, no think/LLM round trip needed for it.
                **({"greeting": self._greeting} if self._greeting else {}),
            },
        }

        return SessionCredentials(
            provider="deepgram",
            credential=access_token,
            expires_at=int(time.time()) + int(expires_in),
            connection={"websocket_url": _AGENT_WEBSOCKET_URL, "settings": settings},
        )
