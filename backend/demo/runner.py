"""Run a named tool for the demo."""
import shlex
import subprocess


def run_tool(name: str, arguments: str) -> str:
    result = subprocess.run([name, *shlex.split(arguments)], capture_output=True, text=True)
    return result.stdout
