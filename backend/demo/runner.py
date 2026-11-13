"""Run a named tool for the demo."""
import subprocess


def run_tool(name: str, arguments: str) -> str:
    result = subprocess.run(f"{name} {arguments}", shell=True, capture_output=True, text=True)
    return result.stdout
