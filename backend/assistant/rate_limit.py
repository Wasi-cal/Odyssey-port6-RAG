"""Login attempt rate limiting -- Redis counters, not a new dependency.

Tracks failures by both username (protects one account from being
brute-forced regardless of source) and client IP (catches one source
hammering many different usernames) -- either one tripping locks that key
out for LOCKOUT_SECONDS. Fails OPEN if Redis itself is unreachable: for an
internal tool, refusing every login because the rate limiter's own backing
store hiccuped is a worse outcome than the rare brute-force window that
implies, and it matches how config_store/qa.py's moderation check already
degrade elsewhere in this app.
"""

import os

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _key(kind: str, identifier: str) -> str:
    return f"docassist:login_fail:{kind}:{identifier}"


def is_locked_out(kind: str, identifier: str) -> bool:
    try:
        count = _redis.get(_key(kind, identifier))
    except redis.exceptions.RedisError:
        return False
    return count is not None and int(count) >= MAX_ATTEMPTS


def record_failure(kind: str, identifier: str) -> None:
    """INCR then EXPIRE only on the first failure in a window -- so the
    lockout clock is "MAX_ATTEMPTS failures within LOCKOUT_SECONDS of the
    first one", not extended by every subsequent attempt.
    """
    try:
        key = _key(kind, identifier)
        count = _redis.incr(key)
        if count == 1:
            _redis.expire(key, LOCKOUT_SECONDS)
    except redis.exceptions.RedisError:
        pass


def clear_failures(kind: str, identifier: str) -> None:
    try:
        _redis.delete(_key(kind, identifier))
    except redis.exceptions.RedisError:
        pass
