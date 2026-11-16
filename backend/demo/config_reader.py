"""Read a config text for the demo."""
import yaml


def read_config(text: str):
    return yaml.load(text)
