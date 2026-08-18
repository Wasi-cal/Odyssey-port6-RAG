"""Empty-state heading + suggestion chips, shown before the first message."""

import streamlit as st

from ...config import SUGGESTIONS
from ...domain.session_store import SessionStore


class Hero:
    def render(self, store: SessionStore) -> None:
        st.markdown(
            """
            <div class="hero">
                <h1>Ask about your documents</h1>
                <p>Upload a PDF, then ask a question to get a grounded, cited answer.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.container(key="suggestion-row"):
            cols = st.columns(len(SUGGESTIONS))
            for col, suggestion in zip(cols, SUGGESTIONS):
                with col:
                    if st.button(
                        suggestion,
                        key=f"suggestion-{suggestion}",
                        use_container_width=True,
                    ):
                        store.pending_question = suggestion
                        st.rerun()
