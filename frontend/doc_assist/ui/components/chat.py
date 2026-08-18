"""Rendering for a single message bubble and the full conversation list."""

import html

import streamlit as st

from ...domain.models import ChatSession, parse_citation


class MessageView:
    """Renders one message row (bubble + optional citations/footer). No
    st.chat_message -- alignment is pure CSS on the bubble container.
    """

    @staticmethod
    def render_citations(sources) -> None:
        if not sources:
            return
        lines = []
        for src in sources:
            try:
                doc, heading, page_label = parse_citation(src)
            except Exception:
                doc, heading, page_label = str(src), "", ""
            # Document, then the page it's on, then the heading it came from.
            line = " · ".join(part for part in (doc, page_label, heading) if part)
            lines.append(html.escape(line))
        st.markdown(
            f'<div class="citation-line">{"<br>".join(lines)}</div>',
            unsafe_allow_html=True,
        )

    def render(self, role: str, content: str, meta: dict | None, key: str) -> None:
        with st.container(key=f"msgrow-{role}-{key}"):
            bubble_class = "bubble-user" if role == "user" else "bubble-assistant"
            with st.container(key=f"{bubble_class}-{key}"):
                st.markdown(content)
            if role == "assistant" and meta:
                self.render_citations(meta.get("sources", []))


class ConversationView:
    """Renders the full message list for a session, plus the top spacer."""

    def __init__(self, message_view: MessageView | None = None):
        self.message_view = message_view or MessageView()

    def render(self, session: ChatSession) -> None:
        st.markdown('<div class="top-spacer"></div>', unsafe_allow_html=True)
        for i, message in enumerate(session.messages):
            self.message_view.render(
                message.role, message.content, message.meta, key=f"{session.id}-{i}"
            )
