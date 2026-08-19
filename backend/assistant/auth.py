"""Password hashing + JWT issuance/verification, and the separate admin
password gate for document upload/delete.

Two distinct, deliberately unconnected secrets:
- Per-account password (bcrypt-hashed, stored in users.password_hash) --
  proves who you are, issues a JWT that authenticates every request.
- ADMIN_PASSWORD (a single shared secret, env-configured) -- proves you're
  allowed to change the shared document library, checked fresh on every
  single upload/delete call, never carried in the JWT or "unlocked" for a
  session. Anyone logged in can ask questions; only whoever also knows this
  can add or remove documents everyone else's questions draw from.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = int(os.environ.get("JWT_EXPIRY_DAYS", "7"))

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def require_auth_secrets() -> None:
    """Both secrets MUST be set explicitly -- unlike OPENAI_API_KEY (whose
    absence just breaks answering questions), a missing/default JWT_SECRET or
    ADMIN_PASSWORD would silently make auth forgeable or the admin gate
    guessable, so this fails loudly at startup instead of quietly at the
    first request that needed it.
    """
    missing = [
        name
        for name, value in (("JWT_SECRET", JWT_SECRET), ("ADMIN_PASSWORD", ADMIN_PASSWORD))
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"{', '.join(missing)} not set. Copy .env.example to .env and set "
            "real values -- these are required, there is no safe default."
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
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
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
    # compare_digest, not `==` -- a plain string comparison short-circuits on
    # the first mismatched byte, which leaks how many leading characters were
    # guessed correctly to anyone timing the response.
    return secrets.compare_digest(password or "", ADMIN_PASSWORD)
