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
            self._stage_upload(attached, store)

        self._render_pending_upload(store)

        return question

    def _stage_upload(self, files, store: SessionStore) -> None:
        """Uploading requires the admin password on every single call (not a
        one-time "unlock") -- see api.require_admin_password. Files are
        staged in session_state as plain {"name", "bytes"} dicts (not the
        UploadedFile objects themselves) so they survive the reruns between
        attaching them and confirming the password below.
        """
        already_mine = sorted({f.name for f in files if store.is_ingested(f.name)})
        if already_mine:
            st.warning(
                "Already in your library, skipped: "
                + ", ".join(already_mine)
                + ". Delete it from the Library first if you want to replace it."
            )

        new_files = [f for f in files if not store.is_ingested(f.name)]
        if new_files:
            st.session_state.pending_upload = [
                {"name": f.name, "bytes": f.getvalue()} for f in new_files
            ]

    def _render_pending_upload(self, store: SessionStore) -> None:
        pending = st.session_state.get("pending_upload")
        if not pending:
            return

        names = ", ".join(p["name"] for p in pending)
        st.info(f"Ready to upload: {names}")
        admin_password = st.text_input(
            "Admin password", type="password", key="admin-pw-upload"
        )
        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            confirm = st.button(
                "Confirm upload", key="confirm-upload", type="primary", use_container_width=True
            )
        with col_cancel:
            cancel = st.button("Cancel", key="cancel-upload", use_container_width=True)

        if cancel:
            st.session_state.pending_upload = None
            st.rerun()
            return
        if not confirm:
            return
        if not admin_password:
            st.error("Admin password required.")
            return

        with st.spinner(f"Ingesting {len(pending)} document(s)…"):
            result = self.api.ingest(pending, admin_password)

        if not result["ok"]:
            st.error(result["error"])
            return

        store.refresh_library()
        st.session_state.pending_upload = None
        skipped = result.get("skipped") or []
        if skipped:
            st.warning(
                "Already exists, skipped: "
                + ", ".join(skipped)
                + ". Delete the existing file first, then re-upload."
            )
        st.rerun()

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
                self._stage_upload(legacy, store)
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
