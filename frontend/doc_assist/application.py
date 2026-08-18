"""Top-level application object: owns the store/api client/components and
wires them together. app.py just constructs and runs one of these.
"""

import streamlit as st

from .api.client import ApiClient
from .domain.models import ChatSession
from .domain.session_store import SessionStore
from .ui.components.chat import ConversationView
from .ui.components.composer import Composer
from .ui.components.hero import Hero
from .ui.components.sidebar import Sidebar


class DocAssistApp:
    def __init__(self, api_base_url: str):
        self.store = SessionStore()
        self.api = ApiClient(api_base_url)
        self.sidebar = Sidebar()
        self.hero = Hero()
        self.conversation = ConversationView()
        self.composer = Composer(self.api)

    def run(self) -> None:
        self.sidebar.render(self.store)

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
        session.add_message("user", question)
        self.conversation.message_view.render(
            "user", question, None, key=f"{session.id}-{idx}"
        )

        with st.container(key=f"msgrow-assistant-{session.id}-{idx + 1}"):
            with st.spinner("Thinking…"):
                answer_text, meta = self.api.ask(question)
            with st.container(key=f"bubble-assistant-{session.id}-{idx + 1}"):
                st.markdown(answer_text)
            if meta:
                self.conversation.message_view.render_citations(meta.get("sources", []))
                self.conversation.message_view.render_footer(meta)

        session.add_message("assistant", answer_text, meta)
        st.rerun()
