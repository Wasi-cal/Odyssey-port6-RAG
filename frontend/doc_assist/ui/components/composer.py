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
        if attached:
            self.ingest(attached, store)

        question = (store.pending_question or typed_question or "").strip()
        store.pending_question = None
        return question

    def ingest(self, files, store: SessionStore) -> None:
        """Upload PDFs to the backend and record them in the library."""
        new_files = [f for f in files if not store.is_ingested(f.name)]
        if not new_files:
            return
        with st.spinner(f"Ingesting {len(new_files)} document(s)…"):
            result = self.api.ingest(new_files)
        if result["ok"]:
            for f in new_files:
                store.mark_ingested(f.name)
            for name in result["ingested"]:
                store.add_library_entry(name, result["chunk_count"])
        else:
            st.error(result["error"])

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
                self.ingest(legacy, store)
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
