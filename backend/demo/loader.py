"""Load a saved object for the demo."""
import pickle


def load_object(data: bytes):
    return pickle.loads(data)
