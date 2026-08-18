"""Wraps st.session_state so the rest of the app never touches the raw
session dict directly.

Sessions, messages, and the document library are fetched from the backend
(Postgres-backed, see backend/assistant/db.py) on first load of each
Streamlit connection and cached here for the rest of it -- this class is
never their source of truth, just a per-connection cache, so a page refresh
or container restart never loses them.

Each past chat is also addressable by its id via the "chat" URL query param
(?chat=<uuid>, the same uuid backend/assistant/db.py already mints for
chat_sessions.id) -- see _resolve_initial_session and switch_session. A
brand-new chat has no URL yet: it only becomes addressable once it gets its
first reply (application.py calls publish_current_session_url() at that
point), matching a fresh, empty chat being unnamed/untitled until then too.
"""

import streamlit as st

from ..api.client import ApiClient
from .models import ChatMessage, ChatSession

_QUERY_PARAM = "chat"


class SessionStore:
    def __init__(self, api: ApiClient, user_id: str):
        self.api = api
        self.user_id = user_id

        if "sessions" not in st.session_state:
            st.session_state.sessions = {}
            st.session_state.session_order = []
            st.session_state.current_session_id = None
            st.session_state.sessions_loaded = False

        if not st.session_state.sessions_loaded:
            self._load_sessions_from_backend()

        if st.session_state.get("library") is None:
            fetched = self.api.get_library(user_id)
            if fetched is not None:
                st.session_state.library = fetched

        if "pending_question" not in st.session_state:
            st.session_state.pending_question = None

        if st.session_state.current_session_id is None:
            self._resolve_initial_session()

    # -- sessions --------------------------------------------------------
    def _load_sessions_from_backend(self) -> None:
        """Most-recently-created first, matching GET /sessions' ordering.

        A None result (request failed -- e.g. the API restarting) leaves
        sessions_loaded False so the next rerun retries, instead of a
        transient failure getting cached as "you have no past chats" for
        the rest of the browser session.
        """
        rows = self.api.get_sessions(self.user_id)
        if rows is None:
            return
        for row in rows:
            st.session_state.sessions[row["id"]] = ChatSession(id=row["id"], title=row["title"])
            st.session_state.session_order.append(row["id"])
        st.session_state.sessions_loaded = True

    def _resolve_initial_session(self) -> None:
        """A URL of ?chat=<id> reopens that specific past chat; anything else
        -- a bare app load, or a stale/foreign id -- starts a brand-new,
        still-unaddressable chat instead of silently resuming whatever was
        open last -- a bare app load is always meant to land on a fresh chat.
        """
        requested = st.query_params.get(_QUERY_PARAM)
        if requested and requested in st.session_state.sessions:
            self.switch_session(requested)
            return
        if requested:
            del st.query_params[_QUERY_PARAM]
        self.new_session()

    def _ensure_messages_loaded(self, session_id: str) -> None:
        session = st.session_state.sessions[session_id]
        if session.messages:
            return
        for row in self.api.get_messages(session_id):
            session.messages.append(
                ChatMessage(role=row["role"], content=row["content"], meta=row.get("meta"))
            )

    def new_session(self) -> str:
        created = self.api.create_session(self.user_id)
        # Falls back to a local-only id if the backend is briefly unreachable
        # -- chat still works this run, it just won't survive a refresh.
        sid = created["id"] if created else f"local-{len(st.session_state.session_order) + 1}"
        st.session_state.sessions[sid] = ChatSession(id=sid)
        st.session_state.session_order.insert(0, sid)
        st.session_state.current_session_id = sid
        if _QUERY_PARAM in st.query_params:
            del st.query_params[_QUERY_PARAM]
        return sid

    def switch_session(self, session_id: str) -> None:
        self._ensure_messages_loaded(session_id)
        st.session_state.current_session_id = session_id
        st.query_params[_QUERY_PARAM] = session_id

    def publish_current_session_url(self) -> None:
        """Promotes the current (until-now-unaddressable) chat to its own
        ?chat=<id> URL. Called once, right after its first reply lands."""
        st.query_params[_QUERY_PARAM] = self.current_session_id

    @property
    def current_session_id(self) -> str:
        return st.session_state.current_session_id

    @current_session_id.setter
    def current_session_id(self, session_id: str) -> None:
        self.switch_session(session_id)

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
        return st.session_state.get("library") or []

    def is_ingested(self, filename: str) -> bool:
        return any(entry["name"] == filename for entry in self.library)

    def refresh_library(self) -> None:
        """A None result (request failed) leaves the existing library alone
        -- a transient failure should never wipe out a library that was
        already showing something real.
        """
        fetched = self.api.get_library(self.user_id)
        if fetched is not None:
            st.session_state.library = fetched

    # -- pending question (set by a suggestion-chip click) ------------------
    @property
    def pending_question(self) -> str | None:
        return st.session_state.pending_question

    @pending_question.setter
    def pending_question(self, value: str | None) -> None:
        st.session_state.pending_question = value
