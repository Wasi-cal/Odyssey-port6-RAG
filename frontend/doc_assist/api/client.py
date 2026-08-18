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

    def ask(self, question: str) -> tuple[str, dict | None]:
        """POST /ask. Returns (answer_text, meta). Never raises."""
        try:
            resp = requests.post(
                f"{self.base_url}/ask",
                json={"question": question},
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

    def ingest(self, files) -> dict:
        """POST /ingest (multipart PDFs). Returns either
        {"ok": True, "ingested": [...], "chunk_count": N} or
        {"ok": False, "error": "..."}. Never raises.
        """
        try:
            multipart = [
                ("files", (f.name, f.getvalue(), "application/pdf")) for f in files
            ]
            resp = requests.post(f"{self.base_url}/ingest", files=multipart, timeout=300)
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
