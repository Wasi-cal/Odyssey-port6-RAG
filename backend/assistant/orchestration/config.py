"""Temporal connection settings."""

import os

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")

# One task queue for all ingestion work. If independent workflow types are
# ever added, give each its own queue so they can be scaled/deployed
# separately -- there's no need for that yet with just one workflow.
TASK_QUEUE = "doc-assistant-ingestion"
