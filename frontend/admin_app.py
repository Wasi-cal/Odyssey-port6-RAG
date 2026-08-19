"""admin_app.py -- standalone admin app: login + monitoring on one page.

Separate process/entrypoint from app.py (the chatbot) on purpose -- run with
`streamlit run admin_app.py --server.port 8502`. Auth is completely
independent from the chatbot's regular user login.
"""

import html
import urllib.parse

import requests
import streamlit as st

from doc_assist.config import API_BASE_URL


st.set_page_config(
    page_title="Doc Assist — Admin",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

    :root {
        --ink: #171B2E;
        --text: #3C4258;
        --muted: #9297A6;
        --line: #E9EAF0;
        --surface: #FFFFFF;
        --soft: #F6F7FA;
    }

    .stApp {
        font-family: 'IBM Plex Sans', sans-serif;
        background: #FBFBFC;
    }

    .block-container {
        max-width: 1120px;
        padding: 40px 32px 60px;
    }

    /* Buttons */
    .stButton > button {
        min-height: 38px;
        border-radius: 9px;
        border-color: var(--line);
        font-size: 12.5px;
        font-weight: 600;
        box-shadow: none;
    }

    .stButton > button:hover {
        border-color: #D6D9E2;
    }

    button[kind="primary"] {
        background: var(--ink) !important;
        border-color: var(--ink) !important;
    }

    button[kind="primary"]:hover {
        background: #252A40 !important;
        border-color: #252A40 !important;
    }

    /* Inputs
       BaseWeb wraps the field in nested divs, each able to carry a border --
       that's the "box inside a box". Border only the outer wrapper, then
       flatten every inner layer (and the reveal-button container) so exactly
       one box remains. */
    [data-testid="stTextInput"] label {
        color: var(--text);
        font-size: 12px;
        font-weight: 600;
    }

    [data-testid="stTextInput"] div[data-baseweb="input"] {
        border-radius: 9px;
        border: 1px solid var(--line);
        background: var(--surface);
        transition: border-color .15s, box-shadow .15s;
    }

    [data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
        border-color: #C9CDFD;
        box-shadow: 0 0 0 2px #EEF0FF;
    }

    /* Flatten every inner layer: nested wrapper, the input, and the
       password reveal button. None of them should draw their own box. */
    [data-testid="stTextInput"] div[data-baseweb="input"] > div,
    [data-testid="stTextInput"] div[data-baseweb="input"] input,
    [data-testid="stTextInput"] div[data-baseweb="input"] button {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }

    [data-testid="stTextInput"] div[data-baseweb="input"] input {
        font-size: 13px;
    }

    [data-testid="stTextInput"] div[data-baseweb="input"] button {
        color: var(--muted);
    }

    [data-testid="stTextInput"] div[data-baseweb="input"] button:hover {
        color: var(--text);
    }

    /* Remove the "Press Enter to submit form" hint under inputs in forms */
    [data-testid="InputInstructions"] {
        display: none;
    }

    .brand {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 28px;
    }

    .brand-icon {
        width: 34px;
        height: 34px;
        border-radius: 10px;
        background: var(--ink);
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'Manrope', sans-serif;
        font-weight: 800;
    }

    .brand-name {
        color: var(--ink);
        font-family: 'Manrope', sans-serif;
        font-size: 15px;
        font-weight: 800;
    }

    .kicker {
        color: #A0A5B3;
        font-size: 10.5px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .login-title,
    .page-title {
        color: var(--ink);
        font-family: 'Manrope', sans-serif;
        font-weight: 700;
        letter-spacing: -0.035em;
    }

    .login-title {
        font-size: 28px;
        margin: 6px 0;
    }

    .login-subtitle,
    .page-subtitle {
        color: var(--muted);
        font-size: 13px;
        line-height: 1.6;
    }

    .login-subtitle {
        margin: 0 0 24px;
    }

    /* Dashboard */
    .page-title {
        font-size: 30px;
        margin-top: 5px;
    }

    .page-subtitle {
        margin-top: 4px;
    }

    .section-heading {
        color: var(--ink);
        font-family: 'Manrope', sans-serif;
        font-size: 17px;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin: 30px 0 5px;
    }

    .section-caption {
        color: var(--muted);
        font-size: 12px;
        margin-bottom: 13px;
    }

    /* Metrics */
    .metric-card {
        min-height: 94px;
        padding: 16px 17px;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 14px;
    }

    .metric-label {
        color: var(--muted);
        font-size: 10.5px;
        font-weight: 600;
        margin-bottom: 9px;
    }

    .metric-value {
        color: var(--ink);
        font-family: 'Manrope', sans-serif;
        font-size: 21px;
        font-weight: 700;
        letter-spacing: -0.025em;
    }

    /* Pending documents */
    .doc-row {
        padding: 12px 14px;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 12px;
        margin-bottom: 8px;
    }

    .doc-name {
        color: var(--ink);
        font-size: 13px;
        font-weight: 600;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .doc-meta {
        color: var(--muted);
        font-size: 11px;
        margin-top: 4px;
    }

    .empty-state {
        padding: 23px;
        text-align: center;
        border: 1px dashed #DDE0E8;
        border-radius: 13px;
        background: #FDFDFE;
        color: var(--muted);
        font-size: 12.5px;
    }

    /* Expanders + alerts */
    [data-testid="stExpander"] {
        border: 1px solid var(--line);
        border-radius: 13px;
        background: #fff;
        overflow: hidden;
    }

    [data-testid="stExpander"] summary {
        color: var(--text);
        font-size: 12.5px;
        font-weight: 600;
    }

    [data-testid="stAlert"] {
        border-radius: 10px;
        font-size: 12px;
    }

    .admin-footer {
        color: #B4B8C4;
        font-size: 10.5px;
        text-align: center;
        margin-top: 38px;
    }

    @media (max-width: 760px) {
        .block-container {
            padding: 28px 18px 48px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.admin_token}"}


def _error_detail(resp: requests.Response, fallback: str) -> str:
    try:
        return str(resp.json().get("detail", fallback))
    except ValueError:
        return resp.text or fallback


def _get(path: str):
    try:
        resp = requests.get(
            f"{API_BASE_URL}{path}",
            headers=_headers(),
            timeout=30,
        )
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return None

    if resp.status_code == 401:
        st.session_state.admin_token = None
        st.rerun()

    if resp.status_code != 200:
        st.error(_error_detail(resp, "Request failed."))
        return None

    return resp.json()


def _delete(path: str) -> bool:
    try:
        resp = requests.delete(
            f"{API_BASE_URL}{path}",
            headers=_headers(),
            timeout=30,
        )
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return False

    if resp.status_code == 401:
        st.session_state.admin_token = None
        st.rerun()

    if resp.status_code != 200:
        st.error(_error_detail(resp, "Request failed."))
        return False

    return True


def _upload_documents(files) -> dict | None:
    """POST /admin/documents (multipart) -- distinct from _post/_get/_delete
    since this is the only admin call that sends a body other than JSON.
    Returns the parsed response (queued/skipped/renamed) or None on failure.
    """
    try:
        resp = requests.post(
            f"{API_BASE_URL}/admin/documents",
            headers=_headers(),
            files=[("files", (f.name, f.getvalue(), "application/pdf")) for f in files],
            timeout=120,
        )
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return None

    if resp.status_code == 401:
        st.session_state.admin_token = None
        st.rerun()

    if resp.status_code != 200:
        st.error(_error_detail(resp, "Upload failed."))
        return None

    return resp.json()


def _post(path: str) -> bool:
    try:
        resp = requests.post(
            f"{API_BASE_URL}{path}",
            headers=_headers(),
            timeout=60,
        )
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return False

    if resp.status_code == 401:
        st.session_state.admin_token = None
        st.rerun()

    if resp.status_code != 200:
        st.error(_error_detail(resp, "Request failed."))
        return False

    return True


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def _render_login() -> None:
    # Card styling is injected here (not in the global block) so it applies
    # only on the login page. That lets it safely target the single form on
    # this page as the card, without affecting the dashboard's forms. Using a
    # real st.form container also holds the widgets *inside* the card and gives
    # Enter-to-submit for free.
    st.markdown(
        """
        <style>
        [data-testid="stForm"] {
            max-width: 410px;
            margin: 11vh auto 0;
            padding: 34px 34px 28px;
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 20px;
            box-shadow: 0 16px 45px rgba(23, 27, 46, 0.07);
        }
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
            margin-top: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.form("admin-login"):
        st.markdown(
            """
            <div class="brand">
                <div class="brand-icon">◈</div>
                <div class="brand-name">Doc Assist</div>
            </div>
            <div class="kicker">Administration</div>
            <div class="login-title">Welcome back.</div>
            <p class="login-subtitle">
                Monitor document ingestion, approvals, usage, and
                administrative activity from one place.
            </p>
            """,
            unsafe_allow_html=True,
        )

        password = st.text_input("Admin password", type="password")

        submitted = st.form_submit_button(
            "Log in",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return

    try:
        resp = requests.post(
            f"{API_BASE_URL}/admin/login",
            json={"admin_password": password},
            timeout=30,
        )
    except requests.exceptions.RequestException:
        st.error(f"Could not reach the API at {API_BASE_URL}.")
        return

    if resp.status_code != 200:
        st.error(_error_detail(resp, "Login failed."))
        return

    st.session_state.admin_token = resp.json()["access_token"]
    st.rerun()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _render_metric(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_monitoring() -> None:
    st.markdown(
        """
        <div class="kicker">Administration</div>
        <div class="page-title">System overview</div>
        <div class="page-subtitle">
            Monitor ingestion, usage, approvals, and admin activity.
        </div>
        """,
        unsafe_allow_html=True,
    )

    refresh_col, logout_col, _ = st.columns([1, 1, 8])

    with refresh_col:
        if st.button("↻  Refresh", use_container_width=True):
            st.rerun()

    with logout_col:
        if st.button("Log out", use_container_width=True):
            st.session_state.admin_token = None
            st.rerun()

    stats = _get("/admin/monitoring")

    if stats:
        st.markdown(
            '<div class="section-heading">Overview</div>',
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4, c5 = st.columns(5)

        with c1:
            _render_metric(
                "Pending approvals",
                f"{stats['pending_approvals']:,}",
            )

        with c2:
            _render_metric(
                "Embeddings present",
                f"{stats['embeddings_present']:,}",
            )

        with c3:
            _render_metric(
                "Tokens consumed",
                f"{stats['tokens_consumed']:,}",
            )

        with c4:
            _render_metric(
                "Estimated cost",
                f"${stats['cost_usd']:.4f}",
            )

        with c5:
            _render_metric(
                "Avg. tokens / question",
                f"{stats['average_token_usage']:.0f}",
            )

    st.markdown(
        """
        <div class="section-heading">Pending approvals</div>
        <div class="section-caption">
            Review documents before they become available to the assistant.
        </div>
        """,
        unsafe_allow_html=True,
    )

    pending = _get("/admin/pending-documents") or []

    if not pending:
        st.markdown(
            '<div class="empty-state">Nothing waiting for review.</div>',
            unsafe_allow_html=True,
        )

    for doc in pending:
        c_info, c_approve, c_reject = st.columns([7, 1.2, 1.2])

        with c_info:
            uploaded_at = doc["uploaded_at"][:16].replace("T", " ")

            # Escape every interpolated value: filename and uploaded_by are
            # user-controlled at upload time, and this block is rendered with
            # unsafe_allow_html=True. Without escaping, a document named e.g.
            # `<img src=x onerror=...>.pdf` would execute as stored XSS in the
            # admin's authenticated session.
            st.markdown(
                f"""
                <div class="doc-row">
                    <div class="doc-name">{html.escape(doc["filename"])}</div>
                    <div class="doc-meta">
                        Uploaded by {html.escape(doc["uploaded_by"])}
                        · {html.escape(uploaded_at)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with c_approve:
            if st.button(
                "Approve",
                key=f"approve-{doc['id']}",
                type="primary",
                use_container_width=True,
            ):
                with st.spinner("Ingesting…"):
                    if _post(
                        f"/admin/pending-documents/{doc['id']}/approve"
                    ):
                        st.rerun()

        with c_reject:
            if st.button(
                "Reject",
                key=f"reject-{doc['id']}",
                use_container_width=True,
            ):
                if _post(
                    f"/admin/pending-documents/{doc['id']}/reject"
                ):
                    st.rerun()

    st.markdown(
        """
        <div class="section-heading">Library</div>
        <div class="section-caption">
            Documents currently searchable by the assistant. An admin upload is ingested
            immediately, no approval step -- deleting one removes it from the vector
            index and the shared library immediately. Neither is reversible.
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("admin-upload-form", clear_on_submit=True):
        new_files = st.file_uploader(
            "Upload documents",
            type=["pdf"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Upload", type="primary")

    if submitted:
        if not new_files:
            st.warning("Choose at least one PDF first.")
        else:
            with st.spinner(f"Ingesting {len(new_files)} document(s)…"):
                result = _upload_documents(new_files)
            if result is not None:
                if result["ingested"]:
                    st.success(f"Ingested: {', '.join(result['ingested'])}")
                if result["renamed"]:
                    renames = ", ".join(f"{old} → {new}" for old, new in result["renamed"].items())
                    st.info(f"Renamed to avoid a filename collision: {renames}")
                if result["skipped"]:
                    st.warning(f"Already in the library (identical content), skipped: {', '.join(result['skipped'])}")
                st.rerun()

    library = _get("/admin/documents") or []

    if not library:
        st.markdown(
            '<div class="empty-state">No documents in the library yet.</div>',
            unsafe_allow_html=True,
        )

    # Two-step confirm (click Delete, then confirm) -- this permanently drops
    # a document's chunks from Chroma with no undo, so a single mis-click
    # shouldn't be able to do that.
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = None

    for doc in library:
        name = doc["name"]
        ingested_at = doc["ingested_at"][:16].replace("T", " ")

        c_info, c_action = st.columns([7, 1.2])

        with c_info:
            st.markdown(
                f"""
                <div class="doc-row">
                    <div class="doc-name">{html.escape(name)}</div>
                    <div class="doc-meta">
                        {doc["chunk_count"]:,} chunks · ingested {html.escape(ingested_at)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with c_action:
            if st.session_state.confirm_delete == name:
                if st.button(
                    "Confirm",
                    key=f"confirm-delete-{name}",
                    type="primary",
                    use_container_width=True,
                ):
                    with st.spinner("Deleting…"):
                        if _delete(f"/admin/documents/{urllib.parse.quote(name, safe='')}"):
                            st.session_state.confirm_delete = None
                            st.rerun()
            else:
                if st.button(
                    "Delete",
                    key=f"delete-{name}",
                    use_container_width=True,
                ):
                    st.session_state.confirm_delete = name
                    st.rerun()

    with st.expander("Admin activity"):
        entries = _get("/admin/audit-log") or []

        if not entries:
            st.caption("No admin activity yet.")

        for entry in entries:
            when = entry["performed_at"][:16].replace("T", " ")
            # st.caption renders markdown with HTML escaped by default, so
            # this is not an HTML-injection vector. Wrapping the filename in a
            # code span keeps stray markdown characters (e.g. * or _) from
            # mangling the line.
            st.caption(
                f"Uploaded `{entry['filename']}` · "
                f"{entry['performed_by']} · {when}"
            )

    with st.expander("Reset a user's password"):
        st.caption(
            "Use this only when an account needs an administrative password reset."
        )

        with st.form("reset-password-form"):
            username = st.text_input("Username")
            new_password = st.text_input(
                "New password",
                type="password",
            )
            submitted = st.form_submit_button(
                "Reset password",
                type="primary",
            )

        if submitted:
            if len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                try:
                    resp = requests.post(
                        f"{API_BASE_URL}/admin/reset-password",
                        json={
                            "username": username,
                            "new_password": new_password,
                        },
                        headers=_headers(),
                        timeout=30,
                    )

                    if resp.status_code == 200:
                        st.success(f"Password reset for {username}.")
                    else:
                        st.error(
                            _error_detail(resp, "Password reset failed.")
                        )

                except requests.exceptions.RequestException:
                    st.error(
                        f"Could not reach the API at {API_BASE_URL}."
                    )

    with st.expander("Change admin password"):
        st.caption("Changes the shared password used to log in to this admin app.")

        with st.form("change-admin-password-form"):
            new_admin_password = st.text_input("New admin password", type="password")
            submitted = st.form_submit_button("Change password", type="primary")

        if submitted:
            if len(new_admin_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                try:
                    resp = requests.post(
                        f"{API_BASE_URL}/admin/change-password",
                        json={"new_admin_password": new_admin_password},
                        headers=_headers(),
                        timeout=30,
                    )

                    if resp.status_code == 200:
                        st.success("Admin password changed. Use it next time you log in.")
                    else:
                        st.error(_error_detail(resp, "Password change failed."))

                except requests.exceptions.RequestException:
                    st.error(f"Could not reach the API at {API_BASE_URL}.")

    st.markdown(
        f"""
        <div class="admin-footer">
            Doc Assist Admin · API {html.escape(API_BASE_URL)}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


if "admin_token" not in st.session_state:
    st.session_state.admin_token = None

if st.session_state.admin_token is None:
    _render_login()
else:
    _render_monitoring()