"""Top-level application object: owns the store/api client/components and
wires them together. app.py just constructs and runs one of these.
"""

import streamlit as st

from .api.client import ApiClient
from .domain import auth
from .domain.models import ChatSession
from .domain.session_store import SessionStore
from .ui.components.auth_view import AuthView
from .ui.components.chat import ConversationView
from .ui.components.composer import Composer
from .ui.components.hero import Hero
from .ui.components.sidebar import Sidebar


class DocAssistApp:
    def __init__(self, api_base_url: str):
        self.api = ApiClient(api_base_url)

    def run(self) -> None:
        session = auth.resolve_session(self.api)
        if session is None:
            # Not logged in (or the stored token turned out to be invalid) --
            # the rest of the app never even constructs until this resolves,
            # so nothing below ever runs against an unauthenticated client.
            AuthView(self.api).render()
            return

        token, username = session
        self.api.set_token(token)
        # Whenever any request comes back 401 (the JWT expired mid-session),
        # drop straight back to the login screen from wherever that call
        # happened to be, instead of every call site checking for it itself.
        self.api.on_unauthorized = self._handle_unauthorized

        self.store = SessionStore(self.api, username)
        self.sidebar = Sidebar(self.api)
        self.hero = Hero()
        self.conversation = ConversationView()
        self.composer = Composer(self.api)

        self._render_main(username)

    def _handle_unauthorized(self) -> None:
        auth.clear_session()
        st.rerun()

    def _render_main(self, username: str) -> None:
        self.sidebar.render(self.store, username, on_logout=self._handle_unauthorized)

        session = self.store.current_session
        if session.is_empty:
            self.hero.render(self.store)
        else:
            self.conversation.render(session)

        # Spacer so the last bubble is never flush against the composer.
        st.markdown('<div class="bottom-spacer"></div>', unsafe_allow_html=True)

        question = self.composer.render(self.store)
        if question:
            self._ask_and_append(session, question)

    def _ask_and_append(self, session: ChatSession, question: str) -> None:
        idx = len(session.messages)
        is_first_exchange = idx == 0
        session.add_message("user", question)
        self.conversation.message_view.render(
            "user", question, None, key=f"{session.id}-{idx}"
        )

        with st.container(key=f"msgrow-assistant-{session.id}-{idx + 1}"):
            with st.spinner("Thinking…"):
                answer_text, meta = self.api.ask(question, session.id)
            with st.container(key=f"bubble-assistant-{session.id}-{idx + 1}"):
                st.markdown(answer_text)
            if meta:
                self.conversation.message_view.render_citations(meta.get("sources", []))

        session.add_message("assistant", answer_text, meta)
        if meta and meta.get("title"):
            # Keeps this in sync with the backend's title on every exchange,
            # not just the first -- it evolves as the conversation does (see
            # qa.answer_question's previous_title), all from the same /ask
            # call. The sidebar picks up the change on the st.rerun() below,
            # no page reload needed.
            session.title = meta["title"]
        if is_first_exchange:
            # This chat just got its title -- give it its own ?chat=<id> URL
            # now too, matching the sidebar's History list picking it up
            # for the first time on this same rerun.
            self.store.publish_current_session_url()
        st.rerun()
