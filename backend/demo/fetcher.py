"""Fetch a page for the demo."""
import requests


def fetch(url: str) -> str:
    return requests.get(url, verify=False, timeout=10).text
