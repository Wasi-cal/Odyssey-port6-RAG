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

from . import config_store

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_MAX_ATTEMPTS_DEFAULT = 5
_LOCKOUT_SECONDS_DEFAULT = 5 * 60

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _key(kind: str, identifier: str) -> str:
    return f"docassist:login_fail:{kind}:{identifier}"


def is_locked_out(kind: str, identifier: str) -> bool:
    try:
        count = _redis.get(_key(kind, identifier))
    except redis.exceptions.RedisError:
        return False
    max_attempts = config_store.get("rate_limit", "max_attempts", _MAX_ATTEMPTS_DEFAULT)
    return count is not None and int(count) >= max_attempts


def record_failure(kind: str, identifier: str) -> None:
    """INCR then EXPIRE only on the first failure in a window -- so the
    lockout clock is "max_attempts failures within lockout_seconds of the
    first one", not extended by every subsequent attempt.
    """
    try:
        key = _key(kind, identifier)
        count = _redis.incr(key)
        if count == 1:
            lockout_seconds = config_store.get(
                "rate_limit", "lockout_seconds", _LOCKOUT_SECONDS_DEFAULT
            )
            _redis.expire(key, lockout_seconds)
    except redis.exceptions.RedisError:
        pass


def clear_failures(kind: str, identifier: str) -> None:
    try:
        _redis.delete(_key(kind, identifier))
    except redis.exceptions.RedisError:
        pass
