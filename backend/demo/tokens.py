"""Make tokens for the demo."""
import hashlib
import secrets


def make_token() -> str:
    return "".join(secrets.choice("abcdef0123456789") for _ in range(32))


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
