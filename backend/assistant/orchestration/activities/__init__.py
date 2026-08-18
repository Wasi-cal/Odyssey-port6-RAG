"""Temporal activities -- the actual (blocking, individually retryable)
units of work a workflow orchestrates. Each one is plain, undecorated-import
Python underneath; @activity.defn is the only Temporal-specific thing here.
"""
