"""Per-browser anonymous user id, ahead of real auth existing.

Persisted as a browser cookie (not just st.session_state, which resets on
every page refresh) so a browser's document library and chat history survive
a reload or a container restart. Everything downstream (SessionStore,
api.py, assistant/db.py) only ever sees a "user_id" string -- swapping this
for a real authenticated user id later is a one-line change here, not a
schema or API change.

Reads via st.context.cookies (Streamlit >= 1.35): populated straight from the
incoming request's real Cookie header, so it's available immediately with no
async round trip. A bidirectional custom component (e.g. the popular
extra-streamlit-components CookieManager) instead reports a browser's
cookies to Python only after a JS round trip completes, and on a session's
very first script run always reports "none yet" regardless of what's
actually in the browser -- acting on that races into silently minting a
fresh id (and clobbering the real one) on every single page load. Writing
only needs to be visible on the *next* page load, not this one, so a
fire-and-forget `document.cookie = ...` via components.v1.html sidesteps
that race entirely.
"""

import uuid

import streamlit as st
import streamlit.components.v1 as components

_COOKIE_NAME = "doc_assist_uid"
_MAX_AGE_SECONDS = 60 * 60 * 24 * 365


def get_user_id() -> str:
    if "user_id" in st.session_state:
        return st.session_state.user_id

    existing = st.context.cookies.get(_COOKIE_NAME)
    if existing:
        st.session_state.user_id = existing
        return existing

    new_id = str(uuid.uuid4())
    components.html(
        f"<script>document.cookie = "
        f"'{_COOKIE_NAME}={new_id}; max-age={_MAX_AGE_SECONDS}; path=/; SameSite=Lax';"
        f"</script>",
        height=0,
        width=0,
    )
    st.session_state.user_id = new_id
    return new_id
