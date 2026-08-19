"""Estimated OpenAI per-token cost (USD) for the admin monitoring dashboard
-- NOT billing-accurate, just directional. Rates live in config_settings
(category "pricing", see config_store.seed_defaults) rather than hardcoded,
so an admin can update them in Postgres directly if OpenAI reprices, or if
config_store's generation.model / embeddings.embed_model_name changes to a
different model with a different rate -- no code change or redeploy needed.
"""

from . import config_store

_DEFAULT_CHAT_INPUT_PRICE = 0.15 / 1_000_000
_DEFAULT_CHAT_OUTPUT_PRICE = 0.60 / 1_000_000
_DEFAULT_EMBEDDING_PRICE = 0.02 / 1_000_000


def chat_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    input_price = config_store.get("pricing", "chat_input_price_per_token", _DEFAULT_CHAT_INPUT_PRICE)
    output_price = config_store.get("pricing", "chat_output_price_per_token", _DEFAULT_CHAT_OUTPUT_PRICE)
    return prompt_tokens * input_price + completion_tokens * output_price


def embedding_cost_usd(total_tokens: int) -> float:
    price = config_store.get("pricing", "embedding_price_per_token", _DEFAULT_EMBEDDING_PRICE)
    return total_tokens * price
