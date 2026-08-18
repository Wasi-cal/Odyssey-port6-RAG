"""Temporal workflows -- orchestrate activities. A workflow's own code must
be deterministic (no I/O, no randomness, no direct calls to anything
side-effecting); all of that lives in activities/ instead.
"""
