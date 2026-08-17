"""
app.py — Streamlit UI: upload PDFs, ask questions, see cited answers.

This module is a pure API CLIENT. It never imports rag.py or ingest.py, and
never talks to Chroma or OpenAI directly -- all of that lives behind the
FastAPI service in api.py. This file only makes HTTP calls to that API and
renders the response. Run both processes together (see README.md):
  1) uvicorn api:app --reload
  2) streamlit run app.py

Visual/UX design follows design_handoff_documents_assistant/README.md. The
composer is a custom st.form (text_input + submit button), not st.chat_input
-- the handoff places the composer in-flow directly below the hero, above
the message list, not pinned to the viewport bottom, and st.chat_input can
only ever render pinned to the bottom. One handoff interaction still can't
map onto plain Streamlit: the sidebar can't be animated to an exact
0px/264px width or driven by a custom collapse button, so Streamlit's own
native sidebar collapse control is used instead.
"""

import html as html_lib
import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Doc Assist", layout="wide")

BRAND_ICON_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none">'
    '<path d="M6 2h9l5 5v15a1 1 0 01-1 1H6a1 1 0 01-1-1V3a1 1 0 011-1z" '
    'stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>'
)
DOC_ICON_SVG = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" style="flex-shrink:0;">'
    '<path d="M6 2h9l5 5v15a1 1 0 01-1 1H6a1 1 0 01-1-1V3a1 1 0 011-1z" '
    'stroke="#B4B8C4" stroke-width="2"/></svg>'
)

SUGGESTIONS = [
    "Summarize the onboarding guide",
    "What's the PTO policy?",
    "List required SOP approvals",
]

# --------------------------------------------------------------------------
# Design tokens (design_handoff_documents_assistant) + minimal polish CSS
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

    .stApp { font-family: 'IBM Plex Sans', sans-serif; }
    [data-testid="stIconMaterial"] { font-family: 'Material Symbols Rounded', 'Material Icons' !important; }

    .block-container { max-width: 640px; padding: 1.5rem 28px 1rem; }

    /* ---- Sidebar ---- */
    [data-testid="stSidebar"] { background: #FBFBFC; border-right: 1px solid #EEEFF3; }
    [data-testid="stSidebar"] > div:first-child { padding-top: 0.25rem; }
    .brand-row { display: flex; align-items: center; gap: 9px; margin: 0 0 1rem; }
    .brand-icon {
        width: 26px; height: 26px; border-radius: 7px; background: #171B2E;
        display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }
    .brand-word { font-family: 'Manrope', sans-serif; font-weight: 700; font-size: 14px; letter-spacing: -0.01em; color: #171B2E; }

    [data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] {
        justify-content: flex-start;
        color: #3C4258;
        font-size: 13px;
        padding: 6px 8px;
        border-radius: 8px;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] > div { justify-content: flex-start; width: 100%; }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"]:hover { background: #F0F1F5; }

    [data-testid="stSidebar"] [data-testid="stExpander"] { border: none; background: transparent; box-shadow: none; }
    [data-testid="stSidebar"] [data-testid="stExpander"] details { border: none; border-radius: 0; }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary { padding: 8px 4px; }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p {
        font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #B4B8C4;
    }
    [data-testid="stSidebar"] [data-testid="stExpanderDetails"] { padding-bottom: 6px; }
    .doc-row { display: flex; align-items: center; gap: 9px; padding: 7px 8px; }
    .doc-row span { font-size: 12.5px; font-weight: 500; color: #3C4258; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .empty-row { font-size: 12px; color: #B4B8C4; padding: 4px 8px; line-height: 1.6; }

    /* ---- Empty-state hero ---- */
    @keyframes fadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
    .hero { text-align: center; padding-top: 10vh; margin-bottom: 1.5rem; animation: fadeUp 0.4s ease both; }
    .hero h1 { font-family: 'Manrope', sans-serif; font-size: 26px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 8px; color: #171B2E; }
    .hero p { font-size: 13.5px; color: #9297A6; margin: 0; line-height: 1.6; }

    /* ---- Composer (in-flow st.form, not pinned to the viewport bottom) ---- */
    div[data-testid="stForm"] { border: none; padding: 0; }
    [data-testid="stTextInput"] { margin-top: 0; }
    [data-testid="stTextInputRootElement"] {
        background: #F5F6FA; border: none; border-radius: 14px; box-shadow: none;
        height: 44px; transition: box-shadow 0.15s ease;
    }
    [data-testid="stTextInputRootElement"]:focus-within { box-shadow: 0 0 0 2px #E4E7FF; }
    [data-testid="stTextInput"] input { font-size: 14px; color: #1A2036; }
    [data-testid="stTextInput"] input::placeholder { color: #A6ABBA; }

    /* Composer row + attach column: vertically centered, attach flush to the
       right edge (matches the composer/chip/message column's right bound). */
    [class*="st-key-composer-row"] [data-testid="stHorizontalBlock"] { align-items: center; gap: 8px; }
    [class*="st-key-composer-attach"] { display: flex; justify-content: flex-end; }

    button[data-testid="stBaseButton-secondaryFormSubmit"] {
        width: 40px; height: 40px; min-width: 40px; padding: 0;
        border: none; border-radius: 50%; background: #171B2E; color: #fff;
    }
    button[data-testid="stBaseButton-secondaryFormSubmit"] p { color: #fff; font-size: 15px; margin: 0; }

    [class*="st-key-composer-attach"] [data-testid="stPopoverButton"] {
        width: 40px; height: 40px; min-width: 40px; padding: 0; border-radius: 50%;
        background: #F5F6FA; border: 1px solid #EEEFF3; color: #6B7280;
    }
    [class*="st-key-composer-attach"] [data-testid="stPopoverButton"]:hover { background: #EFF0F5; }
    [class*="st-key-composer-attach"] [data-testid="stPopoverButton"] [aria-hidden="true"] { display: none; }

    /* Composer relocated below the message list once a conversation exists,
       fading in gracefully on arrival. (Streamlit's scroll container is
       nested deep enough that position:sticky doesn't reliably hold here --
       it's a normal-flow element at the end of the conversation, not a
       pinned bar.) */
    [class*="st-key-composer-anchored"] {
        background: #FFFFFF; padding: 0.6rem 0 0.4rem; margin-top: 0.25rem;
        animation: fadeUp 0.35s ease both;
    }

    [class*="st-key-suggestion-row"] button {
        border-radius: 999px !important; border: 1px solid #EEEFF3 !important;
        background: #fff !important; color: #6B7280 !important; font-size: 11.5px !important;
        min-height: 42px !important; height: 42px !important; padding: 4px 10px !important;
        display: flex !important; align-items: center !important;
        justify-content: center !important; text-align: center !important; white-space: normal !important;
        line-height: 1.25 !important;
    }

    /* ---- Chat bubbles ---- */
    [data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] { display: none; }
    [data-testid="stChatMessage"] { animation: fadeUp 0.3s ease both; padding: 0.55rem 0; background: transparent !important; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { justify-content: flex-end; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) { justify-content: flex-start; }
    [data-testid="stChatMessageContent"] { width: fit-content; max-width: 84%; }
    [class*="st-key-bubble-user-"] {
        flex: none; width: fit-content; max-width: 84%; margin-left: auto;
        background: #171B2E; border-radius: 14px; padding: 11px 15px;
    }
    [class*="st-key-bubble-user-"] [data-testid="stMarkdownContainer"] p { color: #fff; margin: 0; font-size: 14px; line-height: 1.6; }
    [class*="st-key-bubble-assistant-"] {
        flex: none; width: fit-content; max-width: 84%;
        background: #F5F6FA; border-radius: 14px; padding: 11px 15px;
    }
    [class*="st-key-bubble-assistant-"] [data-testid="stMarkdownContainer"] p,
    [class*="st-key-bubble-assistant-"] [data-testid="stMarkdownContainer"] li { color: #1A2036; margin: 0; font-size: 14px; line-height: 1.6; }
    .citation-line { font-size: 11px; color: #B4B8C4; padding: 4px 4px 0; line-height: 1.6; }
    .footer-note { color: #B4B8C4; font-size: 11px; padding: 0 4px; margin-top: 2px; }
    /* Answers/errors may contain a bare URL or markdown link -- never let it
       render as a clickable, differently-colored hyperlink inside a bubble. */
    [class*="st-key-bubble-user-"] a,
    [class*="st-key-bubble-assistant-"] a,
    .citation-line a {
        color: inherit !important;
        text-decoration: none !important;
        pointer-events: none;
        cursor: default;
    }
    [data-testid="stSpinner"] > div { color: #B4B8C4; font-size: 12.5px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
# sessions: {id: {"title": str | None, "messages": [{role, content, meta}]}}
#   title is None until the session's first message is sent (mirrors the
#   handoff design: a chat only appears in "Chat History" once it has one).
# session_order: session ids, most-recently-created first.
# ingested_files / library: shared across all chat sessions -- the document
#   library is one workspace, chats are just different conversations over it.
if "sessions" not in st.session_state:
    st.session_state.sessions = {}
    st.session_state.session_order = []
    st.session_state.session_counter = 0
    st.session_state.current_session_id = None
if "ingested_files" not in st.session_state:
    st.session_state.ingested_files = set()
if "library" not in st.session_state:
    st.session_state.library = []


def _new_session() -> None:
    st.session_state.session_counter += 1
    sid = f"s{st.session_state.session_counter}"
    st.session_state.sessions[sid] = {"title": None, "messages": []}
    st.session_state.session_order.insert(0, sid)
    st.session_state.current_session_id = sid


if st.session_state.current_session_id is None:
    _new_session()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _extract_error(resp: requests.Response) -> str:
    """Best-effort readable message from a non-2xx response. Never raises."""
    try:
        return str(resp.json().get("detail", resp.text))
    except ValueError:
        return resp.text or f"API returned status {resp.status_code}."


def _parse_citation(citation) -> tuple[str, str]:
    """Split a pre-formatted citation string into (doc, detail) for display.

    sources[] items come from rag.format_citation as "Doc → Section, p.N" or
    "Doc, p.N". Parse those shapes when possible; otherwise fall back to
    showing the raw value as the label. Never raises on unexpected input.
    """
    if not isinstance(citation, str) or not citation.strip():
        return "Unknown source", ""
    text = citation.strip()
    if " → " in text:
        doc, detail = text.split(" → ", 1)
        return doc.strip(), detail.strip()
    if ", p." in text:
        doc, page = text.rsplit(", p.", 1)
        return doc.strip(), f"p. {page.strip()}"
    return text, ""


def render_citations(sources) -> None:
    if not sources:
        return
    lines = []
    for src in sources:
        try:
            doc, detail = _parse_citation(src)
        except Exception:
            doc, detail = str(src), ""
        line = f"{doc} · {detail}" if detail else doc
        lines.append(html_lib.escape(line))
    st.markdown(f'<div class="citation-line">{"<br>".join(lines)}</div>', unsafe_allow_html=True)


def render_footer(meta: dict) -> None:
    if not meta:
        return
    parts = []
    latency_ms = meta.get("latency_ms")
    num_chunks = meta.get("num_chunks")
    if isinstance(latency_ms, (int, float)):
        parts.append(f"{latency_ms / 1000:.1f}s")
    if isinstance(num_chunks, int):
        parts.append(f"{num_chunks} chunk{'s' if num_chunks != 1 else ''}")
    if parts:
        st.markdown(f'<div class="footer-note">{" · ".join(parts)}</div>', unsafe_allow_html=True)


def ask_backend(question: str) -> tuple[str, dict | None]:
    """POST /ask and return (answer_text, meta). Never raises or shows a traceback."""
    try:
        resp = requests.post(f"{API_BASE_URL}/ask", json={"question": question}, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            meta = {
                "sources": data.get("sources", []),
                "num_chunks": data.get("num_chunks"),
                "latency_ms": data.get("latency_ms"),
            }
            return data["answer"], meta
        if resp.status_code == 400:
            return f"Warning: {_extract_error(resp)}", None
        return f"Error: {_extract_error(resp)}", None
    except requests.exceptions.Timeout:
        return "Error: The request timed out. The backend may be slow or unresponsive — please try again.", None
    except requests.exceptions.RequestException:
        return f"Error: Could not reach the API at {API_BASE_URL}.", None


def render_message(role: str, content: str, meta: dict | None, key: str) -> None:
    with st.chat_message(role):
        bubble_class = "bubble-user" if role == "user" else "bubble-assistant"
        with st.container(key=f"{bubble_class}-{key}"):
            st.markdown(content)
        if role == "assistant" and meta:
            render_citations(meta.get("sources", []))
            render_footer(meta)


# --------------------------------------------------------------------------
# Sidebar — brand, new chat, library, chat history
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        f'<div class="brand-row"><div class="brand-icon">{BRAND_ICON_SVG}</div>'
        f'<span class="brand-word">Doc Assist</span></div>',
        unsafe_allow_html=True,
    )

    if st.button("+ New chat", type="tertiary", use_container_width=True):
        _new_session()

    with st.expander("LIBRARY", expanded=True):
        if st.session_state.library:
            for entry in st.session_state.library:
                st.markdown(
                    f'<div class="doc-row">{DOC_ICON_SVG}<span>{html_lib.escape(entry["name"])}</span></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="empty-row">No documents yet.</div>', unsafe_allow_html=True)

    with st.expander("CHAT HISTORY", expanded=True):
        history_ids = [sid for sid in st.session_state.session_order if st.session_state.sessions[sid]["title"]]
        if history_ids:
            for sid in history_ids:
                sess = st.session_state.sessions[sid]
                is_active = sid == st.session_state.current_session_id
                label = f"**{sess['title']}**" if is_active else sess["title"]
                if st.button(label, key=f"hist-{sid}", type="tertiary", use_container_width=True):
                    st.session_state.current_session_id = sid
        else:
            st.markdown('<div class="empty-row">No past chats yet.</div>', unsafe_allow_html=True)

def render_composer(session_id: str) -> tuple[str, bool]:
    """The in-flow composer: attach popover + text input + send, all as one
    row. Send + upload render as matching round icons next to each other at
    the tail of the input. They can't share one literal DOM element (a
    form_submit_button must live inside st.form, and st.popover can't), so
    they're two adjacent, identically-sized circles instead of one fused
    control -- visually next to each other, which is as close as plain
    Streamlit gets. Returns (typed_question, submitted).
    """
    with st.container(key="composer-row"):
        form_col, attach_col = st.columns([13, 1.4], gap="small")
        with form_col:
            with st.form(key=f"composer-{session_id}", clear_on_submit=True, border=False):
                input_col, send_col = st.columns([11, 1.4], gap="small")
                with input_col:
                    typed = st.text_input(
                        "Message",
                        placeholder="Message Doc Assist…",
                        label_visibility="collapsed",
                        key=f"composer-input-{session_id}",
                    )
                with send_col:
                    sent = st.form_submit_button("↑", use_container_width=True)
        with attach_col:
            with st.container(key="composer-attach"):
                with st.popover("+"):
                    uploaded_files = st.file_uploader(
                        "Upload PDFs",
                        type=["pdf"],
                        accept_multiple_files=True,
                        label_visibility="collapsed",
                        help="HR policies, SOPs, manuals, onboarding docs.",
                    )
                    if uploaded_files:
                        new_files = [f for f in uploaded_files if f.name not in st.session_state.ingested_files]
                        if new_files:
                            with st.spinner(f"Ingesting {len(new_files)} document(s)…"):
                                try:
                                    multipart = [
                                        ("files", (f.name, f.getvalue(), "application/pdf")) for f in new_files
                                    ]
                                    resp = requests.post(f"{API_BASE_URL}/ingest", files=multipart, timeout=300)
                                    if resp.status_code == 200:
                                        data = resp.json()
                                        for f in new_files:
                                            st.session_state.ingested_files.add(f.name)
                                        # TODO: back Library with a GET /documents endpoint
                                        # for cross-session persistence. For now it only
                                        # reflects this session's successful /ingest calls.
                                        for name in data.get("ingested", []):
                                            st.session_state.library.append(
                                                {"name": name, "chunk_count": data.get("chunk_count", 0)}
                                            )
                                        st.rerun()  # refresh the sidebar Library list immediately
                                    else:
                                        st.error(_extract_error(resp))
                                except requests.exceptions.Timeout:
                                    st.error("Ingestion timed out. Try again with fewer files, or check the backend.")
                                except requests.exceptions.RequestException:
                                    st.error(f"Could not reach the API at {API_BASE_URL}.")
    return typed, sent


def ask_and_append(session: dict, session_id: str, question: str) -> None:
    """Render the user turn, call the backend, render + persist the reply."""
    idx = len(session["messages"])
    session["messages"].append({"role": "user", "content": question, "meta": None})
    if session["title"] is None:
        session["title"] = question[:40] + ("…" if len(question) > 40 else "")
    render_message("user", question, None, key=f"{session_id}-{idx}")

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            answer_text, meta = ask_backend(question)
        with st.container(key=f"bubble-assistant-{session_id}-{idx + 1}"):
            st.markdown(answer_text)
        if meta:
            render_citations(meta.get("sources", []))
            render_footer(meta)
    session["messages"].append({"role": "assistant", "content": answer_text, "meta": meta})
    st.rerun()  # refresh the sidebar so a new/updated session title appears in Chat History


# --------------------------------------------------------------------------
# Main pane — hero + composer + chips (empty state), or message history with
# the composer relocated below it (populated state), per the handoff. The
# composer only ever renders once per run -- which branch runs is decided by
# whether THIS session had any messages at the start of the run, so the
# transition to "composer below the messages" happens on the natural rerun
# right after the first exchange, not mid-run.
# --------------------------------------------------------------------------
session = st.session_state.sessions[st.session_state.current_session_id]
session_id = st.session_state.current_session_id

if not session["messages"]:
    st.markdown(
        """
        <div class="hero">
            <h1>Ask about your documents</h1>
            <p>Upload a PDF, then ask a question to get a grounded, cited answer.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    typed_question, submitted = render_composer(session_id)

    pending_question = None
    with st.container(key="suggestion-row"):
        cols = st.columns(len(SUGGESTIONS))
        for col, suggestion in zip(cols, SUGGESTIONS):
            with col:
                if st.button(suggestion, key=f"suggestion-{suggestion}", use_container_width=True):
                    pending_question = suggestion

    question = (pending_question or (typed_question if submitted else "") or "").strip()
    if question:
        ask_and_append(session, session_id, question)

else:
    for i, msg in enumerate(session["messages"]):
        render_message(msg["role"], msg["content"], msg.get("meta"), key=f"{session_id}-{i}")

    with st.container(key="composer-anchored"):
        typed_question, submitted = render_composer(session_id)

    question = (typed_question if submitted else "").strip()
    if question:
        ask_and_append(session, session_id, question)
