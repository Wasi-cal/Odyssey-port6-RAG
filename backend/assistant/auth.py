"""Password hashing + JWT issuance/verification, and the separate admin
login used by the standalone admin app.

Two distinct, deliberately unconnected secrets, each with its own token:
- Per-account password (bcrypt-hashed, stored in users.password_hash) --
  proves who a chatbot user is, issues a user JWT (create_access_token /
  decode_access_token) that authenticates every chatbot request.
- The admin password (config_settings: auth/admin_password -- see
  config_store.py, seeded from env ADMIN_PASSWORD on first boot only, live
  value editable in Postgres from then on) -- proves whoever is running the
  separate admin app (frontend/admin_app.py) is allowed to review uploads
  and see usage figures. Never entered anywhere in the chatbot itself;
  POST /admin/login is the only place it's checked, and it issues its own
  admin JWT (create_admin_token / decode_admin_token) -- structurally
  distinct from a user token (a different claim, no username), so one can
  never be replayed as the other.

JWT_SECRET itself stays a plain env var, not a config_settings row: it's
what makes every token (including the ones that authenticate config_store's
own cache) trustworthy in the first place, and rotating it needs to
invalidate every existing token immediately, not drift in on a cache TTL.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from . import config_store

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_DAYS_DEFAULT = 7
# Shorter-lived than a user session by default -- this token grants approval
# and monitoring access, not just chat, so it's worth making an admin log
# back in more often.
_ADMIN_JWT_EXPIRY_HOURS_DEFAULT = 12


def require_auth_secrets() -> None:
    """JWT_SECRET MUST be set explicitly -- unlike OPENAI_API_KEY (whose
    absence just breaks answering questions), a missing/default JWT_SECRET
    would silently make every token forgeable, so this fails loudly at
    startup instead of quietly at the first request that needed it. The
    admin password has no such check here -- it lives in config_settings
    (DB-backed, empty-safe: verify_admin_password below rejects everything
    until an admin password is actually set there).
    """
    if not JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET not set. Copy .env.example to .env and set a real value "
            "-- required, there is no safe default."
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # A malformed stored hash should read as "wrong password", not crash
        # the login attempt with a 500.
        return False


def create_access_token(username: str) -> str:
    days = config_store.get("auth", "jwt_expiry_days", _JWT_EXPIRY_DAYS_DEFAULT)
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=days),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Returns the username (the "sub" claim). Raises jwt.PyJWTError (or a
    subclass -- ExpiredSignatureError, InvalidTokenError, etc.) on anything
    invalid; api.py's dependency turns that into a 401.
    """
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    username = payload.get("sub")
    if not username:
        raise jwt.InvalidTokenError("Token has no subject.")
    return username


def verify_admin_password(password: str) -> bool:
    stored = config_store.get("auth", "admin_password", "")
    if not stored:
        # Never let an unset stored password ("") match an unset submitted
        # password -- compare_digest("", "") is True, which would otherwise
        # let an empty password through before an admin has ever set one.
        return False
    # compare_digest, not `==` -- a plain string comparison short-circuits on
    # the first mismatched byte, which leaks how many leading characters were
    # guessed correctly to anyone timing the response.
    return secrets.compare_digest(password or "", stored)


def create_admin_token() -> str:
    """No "sub" claim -- there's no per-admin username, just one shared
    password, so {"admin": True} is the whole payload. decode_admin_token
    checks that claim specifically so a regular user JWT (which has "sub"
    but no "admin" claim) can never be accepted here even though both are
    signed with the same JWT_SECRET.
    """
    hours = config_store.get("auth", "admin_jwt_expiry_hours", _ADMIN_JWT_EXPIRY_HOURS_DEFAULT)
    payload = {
        "admin": True,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_admin_token(token: str) -> None:
    """Raises jwt.PyJWTError (or a subclass) if the token is missing,
    expired, or isn't actually an admin token -- api.py's dependency turns
    that into a 401, same as decode_access_token.
    """
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    if payload.get("admin") is not True:
        raise jwt.InvalidTokenError("Not an admin token.")
