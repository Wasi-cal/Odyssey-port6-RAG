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
            # Skip the immediate rerun when a question was submitted
            # alongside the attachment -- it still needs to reach the
            # caller to be asked this run; _ask_and_append reruns once it's
            # done, which redraws the sidebar with the refreshed library too.
            self.ingest(attached, store, rerun_when_idle=not question)

        return question

    def ingest(self, files, store: SessionStore, rerun_when_idle: bool = True) -> None:
        """Upload PDFs to the backend and refresh the library from it.

        Reruns on success (unless rerun_when_idle=False) -- the sidebar
        (rendered earlier in this same script run, before the composer)
        would otherwise keep showing the stale library until some later,
        unrelated interaction triggers the next rerun, which reads as "my
        upload didn't show up until I refreshed."
        """
        new_files = [f for f in files if not store.is_ingested(f.name)]
        if not new_files:
            return
        with st.spinner(f"Ingesting {len(new_files)} document(s)…"):
            result = self.api.ingest(new_files, store.user_id)
        if result["ok"]:
            store.refresh_library()
            if rerun_when_idle:
                st.rerun()
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
