"""
defaults.py — single source of truth for config_store's voice/* seed
values.

Imported by both config_store.seed_defaults() (the initial seed row) and
assistant/voice/__init__.py's resolve_*() functions (the fallback value
passed to config_store.get() if the config subsystem is fully down) --
routing both through this one module is what keeps them from drifting,
same reason assistant/embeddings.py's EMBED_MODEL_NAME plays that role for
embeddings.
"""

VOICE_PROVIDER = "deepgram"

OPENAI_REALTIME_MODEL = "gpt-realtime-mini"
OPENAI_REALTIME_VOICE = "marin"

DEEPGRAM_THINK_MODEL = "gpt-4o-mini"
DEEPGRAM_LISTEN_MODEL = "flux-general-en"
DEEPGRAM_SPEAK_MODEL = "aura-2-thalia-en"

# Bug fix (#8 -- "personality is inconsistent, every restart is a new
# personality"): NOT actually a config-persistence bug -- config_settings
# lives in app-db's named Postgres volume (survives a container restart
# unless the volume itself is removed), and every voice/* value above is
# read fresh through config_store's normal cache-aside on every session, so
# a restart alone was never capable of changing VOICE_SESSION_INSTRUCTIONS/
# VOICE_GREETING. The actual cause: unlike the text /ask path (qa.py pins
# ChatOpenAI(temperature=..., seed=42)), nothing here ever pinned a
# temperature for the voice model, so the SAME fixed persona instructions
# were being sampled at each provider's default temperature (OpenAI's
# Realtime default is 0.8; a Deepgram Settings message's think.provider
# temperature field is a documented no-op in BYO-LLM mode -- confirmed live
# that Deepgram's outbound think request to our endpoint is only
# {model, stream, messages, tools}, so the real OpenAI chat-completions
# call routers/voice.py's llm_proxy forwards had NO temperature set at all,
# defaulting to OpenAI's own 1.0). At that much sampling variance, the same
# instructions can read as a noticeably different tone/style call to call
# -- that's genuine LLM sampling behavior, not a bug in how instructions
# are stored or loaded. Mitigation: pin both paths as low as each API
# allows -- routers/voice.py's llm_proxy now overrides (not just sets) the
# `temperature` field on every request it forwards to OpenAI for the
# Deepgram path (the only place that request body is actually
# constructed/controlled by us), and OpenAIVoiceProvider now sets
# `temperature` in the Realtime session object it creates. Neither is
# perfect determinism: OpenAI's Realtime API has no `seed` parameter at
# all (voice is a live audio stream, not a single reproducible completion),
# and even the Deepgram/chat-completions path's `seed` param is
# "best-effort" per OpenAI's own docs, not a hard guarantee -- expect
# noticeably MORE consistent tone/phrasing than before, not byte-identical
# responses turn to turn.
DEEPGRAM_THINK_TEMPERATURE = 0.3
# 0.6 is OpenAI's documented Realtime API minimum (default is 0.8) -- as
# low as this knob goes for that path.
OPENAI_REALTIME_TEMPERATURE = 0.6

# Spoken first, before the employee says anything -- see
# assistant/voice/__init__.py's get_voice_provider() for how this reaches
# each provider differently (Deepgram's dedicated agent.greeting field vs.
# OpenAI's instructions + a frontend-triggered response.create).
VOICE_GREETING = (
    "Hi, I'm your Doc Assist HR assistant. I can help you look up policies "
    "or plan out your leave -- what can I help you with today?"
)

# Persona + the filler-phrase instruction -- tool calls (search_policies ->
# our own /voice/ask -> a real retrieval+generation round trip) take a real
# amount of time, and a voice assistant that goes silent for a second or
# two while that happens reads as broken, not thoughtful. Varying the
# phrase (rather than one fixed line) keeps it from sounding canned on
# repeat questions in the same session. Deliberately does NOT mention the
# greeting -- get_voice_provider() splices VOICE_GREETING in separately
# (as a dedicated field for Deepgram, folded into instructions only for
# OpenAI), so editing one doesn't require also editing the other.
VOICE_SESSION_INSTRUCTIONS = (
    "You are a warm, helpful HR assistant speaking with an employee. "
    "Always use the search_policies tool for any factual or policy claim -- "
    "never answer from your own knowledge. When you need to call "
    "search_policies and it will take a moment, say a brief, natural filler "
    'phrase first ("let me check that," "one sec, pulling that up," "give '
    'me a moment") before the tool result arrives -- never leave silence '
    "while a tool call is in flight. Vary the phrase naturally rather than "
    "repeating the same one every time. Once the tool result returns, "
    "speak the answer directly and naturally -- don't re-summarize what "
    "the filler phrase already implied, and don't read citation labels or "
    "bracket numbers aloud. If search_policies returns an error, or "
    "returns no relevant answer to the employee's question, say so plainly "
    "-- something like \"I wasn't able to find anything on that\" -- then "
    "ask if there's something else you can help with. Never go silent "
    "after a failed or empty lookup; a spoken apology is always better "
    "than no response at all."
)
