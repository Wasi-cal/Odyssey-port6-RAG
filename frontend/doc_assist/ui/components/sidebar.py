"""Sidebar: brand mark, account row, "+ New chat", Library, Chat History."""

import html
import urllib.parse
from typing import Callable

import streamlit as st

from ...api.client import ApiClient
from ...config import BRAND_ICON_SVG, DOC_ICON_SVG, PUBLIC_API_BASE_URL
from ...domain.session_store import SessionStore


class Sidebar:
    def __init__(self, api: ApiClient):
        self.api = api

    def render(self, store: SessionStore, username: str, on_logout: Callable[[], None]) -> None:
        with st.sidebar:
            self._render_brand()
            self._render_account(username, on_logout)

            if st.button("+ New chat", type="tertiary", use_container_width=True):
                store.new_session()
                st.rerun()

            self._render_library(store)
            self._render_history(store)

    def _render_brand(self) -> None:
        st.markdown(
            f'<div class="brand-row"><div class="brand-icon">{BRAND_ICON_SVG}</div>'
            f'<span class="brand-word">Doc Assist</span></div>',
            unsafe_allow_html=True,
        )

    def _render_account(self, username: str, on_logout: Callable[[], None]) -> None:
        st.markdown(
            f'<div class="account-row">{html.escape(username)}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Log out", key="logout", type="tertiary", use_container_width=True):
            on_logout()
        self._render_change_password()

    def _render_change_password(self) -> None:
        with st.expander("Change password"):
            with st.form("change-password-form"):
                current = st.text_input(
                    "Current password", type="password", key="change-pw-current"
                )
                new = st.text_input("New password", type="password", key="change-pw-new")
                submitted = st.form_submit_button("Update password", use_container_width=True)

            if not submitted:
                return
            if not current or not new:
                st.error("Fill in both fields.")
                return
            if len(new) < 8:
                st.error("New password must be at least 8 characters.")
                return

            result = self.api.change_password(current, new)
            if result["ok"]:
                st.success("Password updated.")
            else:
                st.error(result["error"])

    def _render_library(self, store: SessionStore) -> None:
        with st.expander("LIBRARY", expanded=True):
            # No delete affordance here -- removing a document from the
            # shared library is an admin-only action now, done from the
            # separate admin app, not the chatbot.
            if store.library:
                for entry in store.library:
                    name = entry["name"]
                    url = f"{PUBLIC_API_BASE_URL}/documents/{urllib.parse.quote(name)}"
                    st.markdown(
                        f'<div class="doc-row">{DOC_ICON_SVG}'
                        f'<a class="doc-link" href="{html.escape(url)}" '
                        f'target="_blank" rel="noopener">{html.escape(name)}</a></div>',
                        unsafe_allow_html=True,
                    )
            elif not store.pending_uploads:
                st.markdown(
                    '<div class="empty-row">No documents yet.</div>',
                    unsafe_allow_html=True,
                )
            for pending in store.pending_uploads:
                st.markdown(
                    f'<div class="doc-row pending-row">{DOC_ICON_SVG}'
                    f'<span>{html.escape(pending["filename"])}</span>'
                    f'<span class="pending-badge">Pending approval</span></div>',
                    unsafe_allow_html=True,
                )

    def _render_history(self, store: SessionStore) -> None:
        with st.expander("CHAT HISTORY", expanded=True):
            sessions = store.history_sessions()
            if sessions:
                for session in sessions:
                    if st.button(
                        session.title,
                        key=f"hist-{session.id}",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        store.current_session_id = session.id
                        st.rerun()
            else:
                st.markdown(
                    '<div class="empty-row">No past chats yet.</div>',
                    unsafe_allow_html=True,
                )
