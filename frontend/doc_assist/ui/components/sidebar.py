"""Sidebar: brand mark, account row, "+ New chat", Library, Chat History,
Admin activity.
"""

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
            self._render_audit_log()

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
            if store.library:
                for entry in store.library:
                    name = entry["name"]
                    url = f"{PUBLIC_API_BASE_URL}/documents/{urllib.parse.quote(name)}"
                    col_doc, col_delete = st.columns([9, 1], vertical_alignment="center")
                    with col_doc:
                        st.markdown(
                            f'<div class="doc-row">{DOC_ICON_SVG}'
                            f'<a class="doc-link" href="{html.escape(url)}" '
                            f'target="_blank" rel="noopener">{html.escape(name)}</a></div>',
                            unsafe_allow_html=True,
                        )
                    with col_delete:
                        if st.button(
                            "✕",
                            key=f"delete-doc-{name}",
                            type="tertiary",
                            help=f"Delete {name}",
                        ):
                            st.session_state.pending_delete = name
                            st.rerun()
                self._render_pending_delete(store)
            else:
                st.markdown(
                    '<div class="empty-row">No documents yet.</div>',
                    unsafe_allow_html=True,
                )

    def _render_pending_delete(self, store: SessionStore) -> None:
        """Deleting requires the admin password on every single call (not a
        one-time "unlock") -- see api.require_admin_password. Staged in
        session_state rather than deleting on the ✕ click itself, so there's
        a confirmation step and a place to enter that password.
        """
        filename = st.session_state.get("pending_delete")
        if not filename:
            return

        st.warning(f"Delete **{filename}**? This removes it for everyone.")
        admin_password = st.text_input(
            "Admin password", type="password", key="admin-pw-delete"
        )
        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            confirm = st.button(
                "Confirm delete", key="confirm-delete", type="primary", use_container_width=True
            )
        with col_cancel:
            cancel = st.button("Cancel", key="cancel-delete", use_container_width=True)

        if cancel:
            st.session_state.pending_delete = None
            st.rerun()
        if confirm:
            if not admin_password:
                st.error("Admin password required.")
                return
            error = store.delete_document(filename, admin_password)
            st.session_state.pending_delete = None
            if error:
                st.error(error)
            else:
                st.rerun()

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

    def _render_audit_log(self) -> None:
        """Who uploaded/deleted what -- see db.admin_audit_log's comment for
        why this exists (the admin password is a shared secret, so it alone
        never says who used it; every /ingest and delete call is
        authenticated as a specific logged-in user first, which is what
        actually gets recorded). Collapsed by default -- this is an
        accountability trail to check when something looks off, not
        something to have open at all times.
        """
        with st.expander("ADMIN ACTIVITY", expanded=False):
            entries = self.api.get_audit_log()
            if not entries:
                st.markdown(
                    '<div class="empty-row">No admin activity yet.</div>',
                    unsafe_allow_html=True,
                )
                return
            for entry in entries:
                action = "Uploaded" if entry["action"] == "upload" else "Deleted"
                when = entry["performed_at"][:16].replace("T", " ")
                st.markdown(
                    f'<div class="audit-row">{action} '
                    f'<b>{html.escape(entry["filename"])}</b> '
                    f'&middot; {html.escape(entry["performed_by"])} &middot; {when}</div>',
                    unsafe_allow_html=True,
                )
