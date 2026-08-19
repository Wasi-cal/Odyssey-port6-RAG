"""The message composer: native st.chat_input, with a graceful fallback for
Streamlit versions that don't yet support the accept_file attachment button.
"""

import streamlit as st

from ...api.client import ApiClient
from ...domain.session_store import SessionStore


class Composer:
    def __init__(self, api: ApiClient):
        self.api = api

    def render(self, store: SessionStore) -> str:
        """Renders the composer, handles any attached files, and returns the
        question to ask this run (empty string if none was submitted).
        """
        session_id = store.current_session_id
        typed_question, attached = self._render_input(session_id, store)

        question = (store.pending_question or typed_question or "").strip()
        store.pending_question = None

        if attached:
            self._upload(attached, store)

        return question

    def _upload(self, files, store: SessionStore) -> None:
        """No admin password any more -- an upload just queues each file for
        admin review (see api.ingest). Nothing is searchable yet; the
        sidebar's pending-uploads section is what tells the user it's
        waiting for approval, and picks up the switch to the real library
        automatically once an admin approves it (session_store refreshes
        both every rerun).
        """
        already_mine = sorted({f.name for f in files if store.is_ingested(f.name)})
        if already_mine:
            st.warning(
                "Already in your library or pending approval, skipped: " + ", ".join(already_mine)
            )

        new_files = [f for f in files if not store.is_ingested(f.name)]
        if not new_files:
            return

        with st.spinner(f"Uploading {len(new_files)} document(s)…"):
            result = self.api.ingest([{"name": f.name, "bytes": f.getvalue()} for f in new_files])

        if not result["ok"]:
            st.error(result["error"])
            return

        store.refresh_pending_uploads()
        # No st.rerun() here -- these messages need to actually stay on
        # screen to be read; the sidebar's pending list catches up on the
        # next interaction (it re-fetches every rerun, see session_store.py).
        if result["queued"]:
            st.info("Waiting for admin approval: " + ", ".join(result["queued"]))
        if result["skipped"]:
            st.warning("Already exists, skipped: " + ", ".join(result["skipped"]))

    def _render_input(self, session_id: str, store: SessionStore) -> tuple[str, list]:
        """Returns (text, files). Uses the built-in attachment button when
        the installed Streamlit supports it (>= 1.43), otherwise falls back
        to a plain chat input plus a sidebar uploader.
        """
        try:
            payload = st.chat_input(
                "Ask about your documents…",
                accept_file="multiple",
                file_type=["pdf"],
                key=f"chat-input-{session_id}",
            )
        except TypeError:
            with st.sidebar:
                legacy = st.file_uploader(
                    "Upload PDFs",
                    type=["pdf"],
                    accept_multiple_files=True,
                    key=f"uploader-{session_id}",
                )
            if legacy:
                self._upload(legacy, store)
            text = st.chat_input(
                "Ask about your documents…", key=f"chat-input-{session_id}"
            )
            return (text or ""), []

        if payload is None:
            return "", []
        # With accept_file set, chat_input returns an object with .text / .files
        text = getattr(payload, "text", payload if isinstance(payload, str) else "") or ""
        files = list(getattr(payload, "files", []) or [])
        return text, files
