"""Wraps st.session_state so the rest of the app never touches the raw
session dict directly.
"""

import streamlit as st

from .models import ChatSession


class SessionStore:
    def __init__(self):
        if "sessions" not in st.session_state:
            st.session_state.sessions = {}
            st.session_state.session_order = []
            st.session_state.session_counter = 0
            st.session_state.current_session_id = None
        if "ingested_files" not in st.session_state:
            st.session_state.ingested_files = set()
        if "library" not in st.session_state:
            st.session_state.library = []
        if "pending_question" not in st.session_state:
            st.session_state.pending_question = None

        if st.session_state.current_session_id is None:
            self.new_session()

    # -- sessions --------------------------------------------------------
    def new_session(self) -> str:
        st.session_state.session_counter += 1
        sid = f"s{st.session_state.session_counter}"
        st.session_state.sessions[sid] = ChatSession(id=sid)
        st.session_state.session_order.insert(0, sid)
        st.session_state.current_session_id = sid
        return sid

    @property
    def current_session_id(self) -> str:
        return st.session_state.current_session_id

    @current_session_id.setter
    def current_session_id(self, session_id: str) -> None:
        st.session_state.current_session_id = session_id

    @property
    def current_session(self) -> ChatSession:
        return st.session_state.sessions[self.current_session_id]

    def history_sessions(self) -> list[ChatSession]:
        """Past sessions that have a title -- i.e. at least one message sent.
        Most-recently-created first.
        """
        return [
            st.session_state.sessions[sid]
            for sid in st.session_state.session_order
            if st.session_state.sessions[sid].title
        ]

    # -- library -----------------------------------------------------------
    @property
    def library(self) -> list[dict]:
        return st.session_state.library

    def is_ingested(self, filename: str) -> bool:
        return filename in st.session_state.ingested_files

    def mark_ingested(self, filename: str) -> None:
        st.session_state.ingested_files.add(filename)

    def add_library_entry(self, name: str, chunk_count: int) -> None:
        st.session_state.library.append({"name": name, "chunk_count": chunk_count})

    # -- pending question (set by a suggestion-chip click) ------------------
    @property
    def pending_question(self) -> str | None:
        return st.session_state.pending_question

    @pending_question.setter
    def pending_question(self, value: str | None) -> None:
        st.session_state.pending_question = value
