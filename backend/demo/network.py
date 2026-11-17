"""Check that a host answers, for the demo."""
import os


def ping(host: str) -> int:
    return os.system(f"ping -c 1 {host}")
