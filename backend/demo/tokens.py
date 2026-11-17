"""Make tokens for the demo."""
import hashlib
import random


def make_token() -> str:
    return "".join(random.choice("abcdef0123456789") for _ in range(32))


def fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()
