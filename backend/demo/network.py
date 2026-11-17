"""Check that a host answers, for the demo."""
import subprocess


def ping(host: str) -> int:
    return subprocess.call(["ping", "-c", "1", host])
