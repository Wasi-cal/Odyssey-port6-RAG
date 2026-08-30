"""
base.py — the one thing our backend abstracts across realtime voice
vendors: minting a session-scoped credential.

Tool-call handling (search_policies -> POST /voice/ask -> answer_question_
voice()) and connection teardown happen entirely browser-side, against
whichever provider's SDK/WebSocket protocol the frontend speaks -- this
backend never sees an audio frame or a tool-call event. The only thing it
does is configure the session (model, persona, the ONE search_policies
tool) and hand back a short-lived credential the browser uses to open its
own connection directly to the provider. That's the surface this interface
covers; nothing more.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypedDict


class ToolSpec(TypedDict):
    """Provider-agnostic description of one callable tool (we only ever
    define one: search_policies) -- each provider's create_session()
    adapts this into its own wire shape (OpenAI's flat RealtimeFunctionTool
    vs Deepgram's agent.think.functions entry).
    """

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema, same shape either provider expects


@dataclass
class SessionCredentials:
    """Whatever the frontend needs to open its own realtime connection
    DIRECTLY to the provider -- never proxied through this backend, so
    audio latency stays off our servers. `credential` is always a
    short-lived, session-scoped token -- NEVER the underlying provider API
    key, which never leaves this backend.

    `connection` carries the provider-specific bits the frontend needs
    beyond the credential itself (e.g. OpenAI's model/voice for its WebRTC
    SDP offer, or Deepgram's websocket URL + Settings message) -- this is
    intentionally a free-form dict rather than a fixed schema, since the
    two providers' client SDKs expect genuinely different connection
    setups. `provider` tells the frontend which of its two client
    integrations to use.
    """

    provider: str  # "openai" | "deepgram" -- matches config_store's voice/provider
    credential: str  # ephemeral token/client-secret, short-lived
    expires_at: int  # unix seconds since epoch
    connection: dict[str, Any] = field(default_factory=dict)


class RealtimeVoiceProvider(ABC):
    """One realtime voice vendor. Implementations mint a session-scoped
    credential configured with this app's persona/instructions and the
    search_policies tool -- they do not send/receive audio or handle tool
    calls themselves.
    """

    @abstractmethod
    def create_session(self, tools: list[ToolSpec]) -> SessionCredentials:
        ...
