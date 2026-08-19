"""JWT persistence in a browser cookie, so a login survives a page refresh.

Same read/write mechanics as the anonymous-identity cookie this replaces
(port6 used one before real accounts existed): st.context.cookies for a
race-free read (a real HTTP header, available immediately -- unlike a
bidirectional custom component, which only reports cookies after a JS round
trip, and would read "no cookie yet" on every fresh session regardless of
what's actually in the browser), and a fire-and-forget document.cookie
write via components.html() for persistence, since that only needs to be
visible on the *next* page load, not this one.

The cookie name and the fact that it's readable from plain JS (no
HttpOnly) matter: api.py's get_current_user() reads this exact same cookie
as a fallback for the Library/citation links, which are plain <a href>
browser navigations that can't carry a custom Authorization header.
"""

import streamlit as st
import streamlit.components.v1 as components

from ..api.client import ApiClient

_COOKIE_NAME = "doc_assist_jwt"
_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # matches the backend's default JWT_EXPIRY_DAYS


def _is_secure_context() -> bool:
    """Whether this page is being served over HTTPS (via Caddy in
    docker-compose) rather than plain HTTP (a local `streamlit run app.py`
    dev session, with no reverse proxy in front of it) -- a `Secure` cookie
    is silently refused by the browser over a plain-HTTP origin, so this
    can't just be hardcoded on without breaking that second workflow.
    """
    try:
        return str(st.context.url).startswith("https://")
    except Exception:
        return False


def _get_stored_token() -> str | None:
    if "auth_token" in st.session_state:
        return st.session_state.auth_token
    token = st.context.cookies.get(_COOKIE_NAME)
    st.session_state.auth_token = token
    return token


def store_session(token: str, username: str) -> None:
    """Called right after a successful login/register."""
    secure = "; Secure" if _is_secure_context() else ""
    components.html(
        f"<script>document.cookie = "
        f"'{_COOKIE_NAME}={token}; max-age={_MAX_AGE_SECONDS}; path=/; SameSite=Lax{secure}';"
        f"</script>",
        height=0,
        width=0,
    )
    st.session_state.auth_token = token
    st.session_state.username = username


def clear_session() -> None:
    components.html(
        f"<script>document.cookie = '{_COOKIE_NAME}=; max-age=0; path=/;';</script>",
        height=0,
        width=0,
    )
    st.session_state.auth_token = None
    st.session_state.username = None


def resolve_session(api: ApiClient) -> tuple[str, str] | None:
    """Returns (token, username) if the browser already has a valid login,
    else None. A stored token with no known username yet (a fresh
    session_state after a page reload) costs one GET /auth/me call to
    confirm the token's still valid server-side and recover the username --
    cheaper than making the user log in again just because the page
    reloaded, and it doubles as the check that catches an expired token
    immediately rather than on the first real action.
    """
    if st.session_state.get("username"):
        return st.session_state.auth_token, st.session_state.username

    token = _get_stored_token()
    if not token:
        return None

    username = api.whoami(token)
    if username is None:
        clear_session()
        return None

    st.session_state.auth_token = token
    st.session_state.username = username
    return token, username
