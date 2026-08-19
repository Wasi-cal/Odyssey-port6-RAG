"""Pure HTTP client for the FastAPI backend. No RAG logic and no Streamlit
calls live here -- this class only shapes requests/responses for the UI.
"""

import requests


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.token: str | None = None
        # Set by application.py -- called whenever any request comes back
        # 401 (an expired or otherwise invalid JWT), so the app can drop
        # back to the login screen from wherever the call happened to be,
        # instead of every call site separately checking for it.
        self.on_unauthorized = None

    def set_token(self, token: str | None) -> None:
        self.token = token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _extract_error(self, resp: requests.Response) -> str:
        try:
            return str(resp.json().get("detail", resp.text))
        except ValueError:
            return resp.text or f"API returned status {resp.status_code}."

    def _check_unauthorized(self, resp: requests.Response) -> bool:
        if resp.status_code == 401 and self.on_unauthorized:
            self.on_unauthorized()
        return resp.status_code == 401

    # -- auth ----------------------------------------------------------------

    def register(self, username: str, password: str) -> dict:
        """POST /auth/register. Returns {"ok": True, "token", "username"} or
        {"ok": False, "error"}. Never raises."""
        return self._auth_request("register", username, password)

    def login(self, username: str, password: str) -> dict:
        """POST /auth/login. Same return shape as register(). Never raises."""
        return self._auth_request("login", username, password)

    def _auth_request(self, path: str, username: str, password: str) -> dict:
        try:
            resp = requests.post(
                f"{self.base_url}/auth/{path}",
                json={"username": username, "password": password},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "token": data["access_token"], "username": data["username"]}
            return {"ok": False, "error": self._extract_error(resp)}
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Request timed out."}
        except requests.exceptions.RequestException:
            return {"ok": False, "error": f"Could not reach the API at {self.base_url}."}

    def whoami(self, token: str) -> str | None:
        """GET /auth/me with an explicit token (called before self.token is
        necessarily set yet, e.g. right after reading a stored cookie).
        Returns the username, or None if the token is missing/invalid/expired.
        """
        try:
            resp = requests.get(
                f"{self.base_url}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["username"]
        except requests.exceptions.RequestException:
            pass
        return None

    def change_password(self, current_password: str, new_password: str) -> dict:
        """POST /auth/change-password. Returns {"ok": True} or
        {"ok": False, "error": "..."}. Never raises."""
        try:
            resp = requests.post(
                f"{self.base_url}/auth/change-password",
                json={"current_password": current_password, "new_password": new_password},
                headers=self._auth_headers(),
                timeout=30,
            )
            if self._check_unauthorized(resp):
                return {"ok": False, "error": "Your session expired. Please log in again."}
            if resp.status_code == 200:
                return {"ok": True}
            return {"ok": False, "error": self._extract_error(resp)}
        except requests.exceptions.RequestException:
            return {"ok": False, "error": f"Could not reach the API at {self.base_url}."}

    # -- chat ------------------------------------------------------------

    def ask(self, question: str, session_id: str) -> tuple[str, dict | None]:
        """POST /ask. Returns (answer_text, meta). Never raises."""
        try:
            resp = requests.post(
                f"{self.base_url}/ask",
                json={"question": question, "session_id": session_id},
                headers=self._auth_headers(),
                timeout=120,
            )
            if self._check_unauthorized(resp):
                return "Error: Your session expired. Please log in again.", None
            if resp.status_code == 200:
                data = resp.json()
                meta = {
                    # Each item is {"label": str, "filename": str, "page": int|None}
                    # (see api.SourceInfo) -- chat.py's render_citations turns
                    # these into links to GET /documents/{filename}#page=N.
                    "sources": data.get("sources", []),
                    "num_chunks": data.get("num_chunks"),
                    "latency_ms": data.get("latency_ms"),
                    # The session's current title, evolving turn by turn as
                    # the conversation goes (see api.AskResponse.title) --
                    # None only if nothing changed and there wasn't one yet.
                    "title": data.get("title"),
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
        """POST /ingest (multipart PDFs). No admin password any more --
        this only queues each file for admin review, it doesn't ingest it.
        `files` is a list of {"name": str, "bytes": bytes} -- plain dicts,
        not UploadedFile objects, so they survive being held in
        session_state across reruns (see composer.py). Returns either
        {"ok": True, "queued": [...], "skipped": [...], "renamed": {...}} or
        {"ok": False, "error": "..."}. Never raises. "renamed" maps an
        original filename to what it was actually stored as, whenever it
        collided with a DIFFERENT existing file's name -- collisions are
        resolved by renaming, not by rejecting the upload (see api.py's
        _dedupe_filename).
        """
        try:
            multipart = [("files", (f["name"], f["bytes"], "application/pdf")) for f in files]
            resp = requests.post(
                f"{self.base_url}/ingest",
                files=multipart,
                headers=self._auth_headers(),
                timeout=300,
            )
            if self._check_unauthorized(resp):
                return {"ok": False, "error": "Your session expired. Please log in again."}
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "ok": True,
                    "queued": data.get("queued", []),
                    "skipped": data.get("skipped", []),
                    "renamed": data.get("renamed", {}),
                }
            return {"ok": False, "error": self._extract_error(resp)}
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "Upload timed out. Try again with fewer files."}
        except requests.exceptions.RequestException:
            return {"ok": False, "error": f"Could not reach the API at {self.base_url}."}

    def get_pending_documents(self) -> list[dict] | None:
        """GET /documents/pending -- this user's own uploads still awaiting
        admin approval. Returns None on failure (distinct from genuinely
        none pending)."""
        try:
            resp = requests.get(
                f"{self.base_url}/documents/pending", headers=self._auth_headers(), timeout=30
            )
            if self._check_unauthorized(resp):
                return None
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def get_library(self) -> list[dict] | None:
        """GET /library -- global, not scoped to a user (see api.get_library).
        Returns None on any failure -- distinct from a genuinely empty [] --
        so SessionStore knows to retry later instead of caching a transient
        failure (e.g. the API restarting) as if it were a real "no documents
        yet" for the rest of the browser session.
        """
        try:
            resp = requests.get(f"{self.base_url}/library", headers=self._auth_headers(), timeout=30)
            if self._check_unauthorized(resp):
                return None
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def get_sessions(self) -> list[dict] | None:
        """GET /sessions. Returns None on any failure, same rationale as
        get_library."""
        try:
            resp = requests.get(f"{self.base_url}/sessions", headers=self._auth_headers(), timeout=30)
            if self._check_unauthorized(resp):
                return None
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def create_session(self) -> dict | None:
        """POST /sessions. Returns None on failure -- caller falls back to a
        local-only session id so the app stays usable even if the backend is
        briefly unreachable."""
        try:
            resp = requests.post(f"{self.base_url}/sessions", headers=self._auth_headers(), timeout=30)
            if self._check_unauthorized(resp):
                return None
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def get_messages(self, session_id: str) -> list[dict]:
        """GET /sessions/{id}/messages. Returns [] on any failure."""
        try:
            resp = requests.get(
                f"{self.base_url}/sessions/{session_id}/messages",
                headers=self._auth_headers(),
                timeout=30,
            )
            if self._check_unauthorized(resp):
                return []
            if resp.status_code == 200:
                return resp.json()
        except requests.exceptions.RequestException:
            pass
        return []
