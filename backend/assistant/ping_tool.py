"""A small admin helper that checks if a host answers.

TEST FILE: this file has one vulnerability on purpose, to test the Gozurion agent. Do not ship it.
"""

import os


def ping_host(host: str) -> int:
    """Return 0 when the host answers."""
    return os.system("ping -c 1 " + host)
