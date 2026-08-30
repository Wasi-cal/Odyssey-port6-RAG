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
