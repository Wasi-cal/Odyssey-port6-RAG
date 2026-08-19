"""Login/register screen shown before any authenticated content -- nothing
else in the app ever renders until this resolves to a valid session.
"""

import streamlit as st

from ...api.client import ApiClient
from ...domain import auth


class AuthView:
    def __init__(self, api: ApiClient):
        self.api = api

    def render(self) -> None:
        st.markdown(
            '<div class="hero"><h1>Doc Assist</h1>'
            "<p>Sign in to ask questions about your documents.</p></div>",
            unsafe_allow_html=True,
        )

        tab_login, tab_register = st.tabs(["Log in", "Create account"])
        with tab_login:
            self._render_login()
            st.caption("Forgot your password? Ask an admin to reset it.")
        with tab_register:
            self._render_register()

    def _render_login(self) -> None:
        with st.form("login-form"):
            username = st.text_input("Username", key="login-username")
            password = st.text_input("Password", type="password", key="login-password")
            submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)

        if not submitted:
            return
        if not username or not password:
            st.error("Enter a username and password.")
            return

        result = self.api.login(username, password)
        if not result["ok"]:
            st.error(result["error"])
            return
        auth.store_session(result["token"], result["username"])
        st.rerun()

    def _render_register(self) -> None:
        with st.form("register-form"):
            username = st.text_input("Choose a username", key="register-username")
            password = st.text_input(
                "Choose a password", type="password", key="register-password"
            )
            submitted = st.form_submit_button(
                "Create account", type="primary", use_container_width=True
            )

        if not submitted:
            return
        if not username or not password:
            st.error("Enter a username and password.")
            return
        if len(username) < 3:
            st.error("Username must be at least 3 characters.")
            return
        if len(password) < 8:
            st.error("Password must be at least 8 characters.")
            return

        result = self.api.register(username, password)
        if not result["ok"]:
            st.error(result["error"])
            return
        auth.store_session(result["token"], result["username"])
        st.rerun()
