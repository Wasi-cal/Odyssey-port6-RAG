"""One shared Temporal Client per process, connected lazily on first use.

Lazy on purpose: api.py must keep serving /health and /ask even if the
Temporal server isn't up yet (or at all) -- only /ingest actually needs it,
and only when it's actually called, matching how OPENAI_API_KEY is checked
lazily inside answer_question()/ingest_files() rather than at process
startup.
"""

import asyncio

from temporalio.client import Client

from .config import TEMPORAL_ADDRESS

_client: Client | None = None
_connect_lock = asyncio.Lock()


async def get_temporal_client() -> Client:
    """Returns the shared client, connecting on first call. Safe to call
    concurrently -- only the first caller actually connects; the rest wait
    on the lock and then reuse the same client.
    """
    global _client
    if _client is not None:
        return _client
    async with _connect_lock:
        if _client is None:
            _client = await _connect_with_retry()
    return _client


async def _connect_with_retry(attempts: int = 5, delay_seconds: float = 2.0) -> Client:
    """A few retries with a short delay absorbs container-startup ordering
    (e.g. docker-compose's temporal service reporting "up" slightly before
    its gRPC port actually accepts connections) without needing a stricter
    cross-service startup dependency.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await Client.connect(TEMPORAL_ADDRESS)
        except Exception as e:  # noqa: BLE001 -- broad on purpose, see docstring
            last_error = e
            if attempt < attempts - 1:
                await asyncio.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to Temporal at {TEMPORAL_ADDRESS}: {last_error}") from last_error
