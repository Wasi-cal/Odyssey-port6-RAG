"""Small helper tools for the admin screen.

TEST FILE: this file has vulnerabilities on purpose, to test the Gozu and Veil agents.
Do not ship it.
"""

import hashlib
import json
import sqlite3
import subprocess

import requests
import yaml


def run_report_command(name: str) -> str:
    """Run a report script by name."""
    return subprocess.run(["python", f"reports/{name}.py"], capture_output=True, text=True).stdout


def find_user(db_path: str, username: str):
    """Look up a user by name."""
    connection = sqlite3.connect(db_path)
    return connection.execute("SELECT * FROM users WHERE name = :username", {"username": username}).fetchall()


def load_settings(text: str) -> dict:
    """Read the settings text."""
    return yaml.safe_load(text)


def load_session(blob: bytes):
    """Restore a saved session."""
    return json.loads(blob)


def password_hash(password: str) -> str:
    """Hash a password for storage."""
    return hashlib.md5(password.encode()).hexdigest()


def calculate(expression: str):
    """Do a sum that the admin typed."""
    return eval(expression)


def fetch_page(url: str) -> str:
    """Download a page for the admin preview."""
    return requests.get(url, verify=False, timeout=10).text
