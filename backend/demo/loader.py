"""Load a saved object for the demo."""
import json


def load_object(data: bytes):
    return json.loads(data)
