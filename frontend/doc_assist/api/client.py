"""Pure HTTP client for the FastAPI backend. No RAG logic and no Streamlit
calls live here -- this class only shapes requests/responses for the UI.
"""

import requests


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def _extract_error(self, resp: requests.Response) -> str:
        try:
            return str(resp.json().get("detail", resp.text))
        except ValueError:
            return resp.text or f"API returned status {resp.status_code}."

    def ask(self, question: str, session_id: str, user_id: str) -> tuple[str, dict | None]:
        """POST /ask. Returns (answer_text, meta). Never raises."""
        try:
            resp = requests.post(
                f"{self.base_url}/ask",
                json={"question": question, "session_id": session_id, "user_id": user_id},
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                meta = {
                    "sources": data.get("sources", []),
                    "num_chunks": data.get("num_chunks"),
                    "latency_ms": data.get("latency_ms"),
                }
                return data["answer"], meta
            if resp.status_code == 400:
                return f"Warning: {self._extract_error(resp)}", None
            return f"Error: {self._extract_error(resp)}", None
        except requests.exceptions.Timeout:
            return (
                "Error: The request timed out. The backend may be slow or "
                "unresponsive — please try again.",
                None,
            )
        except requests.exceptions.RequestException:
            return f"Error: Could not reach the API at {self.base_url}.", None

    def ingest(self, files, user_id: str) -> dict:
        """POST /ingest (multipart PDFs). Returns either
        {"ok": True, "ingested": [...], "chunk_count": N} or
        {"ok": False, "error": "..."}. Never raises.
        """
        try:
            multipart = [
                ("files", (f.name, f.getvalue(), "application/pdf")) for f in files
            ]
            resp = requests.post(
                f"{self.base_url}/ingest",
                files=multipart,
                data={"user_id": user_id},
                timeout=300,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "ok": True,
                    "ingested": data.get("ingested", []),
                    "chunk_count": data.get("chunk_count", 0),
                }
            return {"ok": False, "error": self._extract_error(resp)}
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Ingestion timed out. Try again with fewer files."}
        except requests.exceptions.RequestException:
            return {"ok": False, "error": f"Could not reach the API at {self.base_url}."}

    def get_library(self, user_id: str) -> list[dict]:
        """GET /library. Returns [] on any failure -- an empty library is a
        safe, silent fallback (the sidebar already handles it), unlike ask/
        ingest where an error needs to be shown to the user.
        """
        try:
            resp = requests.get(f"{self.base_url}/library", params={"user_id": user_id}, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return []

    def get_sessions(self, user_id: str) -> list[dict]:
        """GET /sessions. Returns [] on any failure, same rationale as
        get_library."""
        try:
            resp = requests.get(f"{self.base_url}/sessions", params={"user_id": user_id}, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return []

    def create_session(self, user_id: str) -> dict | None:
        """POST /sessions. Returns None on failure -- caller falls back to a
        local-only session id so the app stays usable even if the backend is
        briefly unreachable."""
        try:
            resp = requests.post(f"{self.base_url}/sessions", json={"user_id": user_id}, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def get_messages(self, session_id: str) -> list[dict]:
        """GET /sessions/{id}/messages. Returns [] on any failure."""
        try:
            resp = requests.get(f"{self.base_url}/sessions/{session_id}/messages", timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return []
