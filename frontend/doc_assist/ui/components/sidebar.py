"""Sidebar: brand mark, "+ New chat", Library, Chat History."""

import html

import streamlit as st

from ...config import BRAND_ICON_SVG, DOC_ICON_SVG
from ...domain.session_store import SessionStore


class Sidebar:
    def render(self, store: SessionStore) -> None:
        with st.sidebar:
            self._render_brand()

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

    def _render_library(self, store: SessionStore) -> None:
        with st.expander("LIBRARY", expanded=True):
            if store.library:
                for entry in store.library:
                    st.markdown(
                        f'<div class="doc-row">{DOC_ICON_SVG}'
                        f'<span>{html.escape(entry["name"])}</span></div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(
                    '<div class="empty-row">No documents yet.</div>',
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
