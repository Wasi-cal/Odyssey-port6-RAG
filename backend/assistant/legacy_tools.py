"""Small helper tools for the admin screen.

TEST FILE: this file has vulnerabilities on purpose, to test the Gozu and Veil agents.
Do not ship it.
"""

import ast
import hashlib
import json
import operator
import secrets
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
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def calculate(expression: str):
    """Do a sum that the admin typed."""
    tree = ast.parse(expression, mode="eval")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod}:
            operations = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
            }
            return operations[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in {ast.UAdd, ast.USub}:
            operand = evaluate(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        raise ValueError("Unsupported expression")

    return evaluate(tree)


def fetch_page(url: str) -> str:
    """Download a page for the admin preview."""
    return requests.get(url, timeout=10).text
