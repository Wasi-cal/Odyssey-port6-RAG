"""admin_app.py -- standalone admin app: login + monitoring on one page.

Separate process/entrypoint from app.py (the chatbot) on purpose -- run with
`streamlit run admin_app.py --server.port 8502`. Auth is completely
independent: POST /admin/login (ADMIN_PASSWORD, env-configured on the
backend) issues its own admin JWT, never a regular user token, and nothing
here ever touches the chatbot's login. Kept as one plain-procedural file,
not a package, since it's a small, single-page tool.
"""

import requests
import streamlit as st

from doc_assist.config import API_BASE_URL

st.set_page_config(page_title="Doc Assist -- Admin", layout="wide")


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.admin_token}"}


def _get(path: str):
    try:
        resp = requests.get(f"{API_BASE_URL}{path}", headers=_headers(), timeout=30)
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return None
    if resp.status_code == 401:
        st.session_state.admin_token = None
        st.rerun()
    if resp.status_code != 200:
        st.error(resp.json().get("detail", resp.text))
        return None
    return resp.json()


def _post(path: str) -> bool:
    try:
        resp = requests.post(f"{API_BASE_URL}{path}", headers=_headers(), timeout=60)
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return False
    if resp.status_code == 401:
        st.session_state.admin_token = None
        st.rerun()
    if resp.status_code != 200:
        st.error(resp.json().get("detail", resp.text))
        return False
    return True


def _render_login() -> None:
    # Centered, narrow column instead of full-width -- a login box has no
    # reason to stretch across the whole page. Plain text_input + button
    # (not st.form) on purpose: inside a form, Enter in the password field
    # submits it; outside one, Enter just commits the value like any other
    # widget, so the user must click Log in.
    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.title("Admin login")
        password = st.text_input("Admin password", type="password", key="admin-login-password")
        submitted = st.button("Log in", type="primary", use_container_width=True)
    if not submitted:
        return
    try:
        resp = requests.post(
            f"{API_BASE_URL}/admin/login", json={"admin_password": password}, timeout=30
        )
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return
    if resp.status_code != 200:
        st.error(resp.json().get("detail", "Login failed."))
        return
    st.session_state.admin_token = resp.json()["access_token"]
    st.rerun()


def _render_monitoring() -> None:
    st.title("Admin monitoring")
    col_refresh, col_logout = st.columns([1, 1])
    with col_refresh:
        if st.button("Refresh"):
            st.rerun()
    with col_logout:
        if st.button("Log out"):
            st.session_state.admin_token = None
            st.rerun()

    stats = _get("/admin/monitoring")
    if stats:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Pending approvals", stats["pending_approvals"])
        c2.metric("Embeddings present", stats["embeddings_present"])
        c3.metric("Tokens consumed", f"{stats['tokens_consumed']:,}")
        c4.metric("Cost (est.)", f"${stats['cost_usd']:.4f}")
        c5.metric("Avg tokens / question", f"{stats['average_token_usage']:.0f}")

    st.subheader("Pending approvals")
    pending = _get("/admin/pending-documents") or []
    if not pending:
        st.caption("Nothing waiting for review.")
    for doc in pending:
        c_name, c_meta, c_approve, c_reject = st.columns([3, 2, 1, 1])
        c_name.write(doc["filename"])
        c_meta.caption(f"{doc['uploaded_by']} · {doc['uploaded_at'][:16].replace('T', ' ')}")
        if c_approve.button("Approve", key=f"approve-{doc['id']}", type="primary"):
            with st.spinner("Ingesting…"):
                if _post(f"/admin/pending-documents/{doc['id']}/approve"):
                    st.rerun()
        if c_reject.button("Reject", key=f"reject-{doc['id']}"):
            if _post(f"/admin/pending-documents/{doc['id']}/reject"):
                st.rerun()

    with st.expander("Admin activity"):
        entries = _get("/admin/audit-log") or []
        if not entries:
            st.caption("No admin activity yet.")
        for entry in entries:
            when = entry["performed_at"][:16].replace("T", " ")
            st.caption(f"Uploaded **{entry['filename']}** · {entry['performed_by']} · {when}")

    with st.expander("Reset a user's password"):
        with st.form("reset-password-form"):
            username = st.text_input("Username")
            new_password = st.text_input("New password", type="password")
            submitted = st.form_submit_button("Reset")
        if submitted:
            if len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                try:
                    resp = requests.post(
                        f"{API_BASE_URL}/admin/reset-password",
                        json={"username": username, "new_password": new_password},
                        headers=_headers(),
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        st.success(f"Password reset for {username}.")
                    else:
                        st.error(resp.json().get("detail", resp.text))
                except requests.exceptions.RequestException:
                    st.error(f"Could not reach the API at {API_BASE_URL}.")


if "admin_token" not in st.session_state:
    st.session_state.admin_token = None

if st.session_state.admin_token is None:
    _render_login()
else:
    _render_monitoring()
