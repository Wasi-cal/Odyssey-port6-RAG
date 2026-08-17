"""
app.py — Streamlit UI: upload PDFs, ask questions, see cited answers.

This module is a pure API CLIENT. It never imports rag.py or ingest.py, and
never talks to Chroma or OpenAI directly -- all of that lives behind the
FastAPI service in api.py. This file only makes HTTP calls to that API and
renders the response. Run both processes together (see README.md):
  1) uvicorn api:app --reload
  2) streamlit run app.py
"""

import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# Not an import of ingest.py -- just the same relative path, duplicated as a
# plain literal, purely so the UI can list what's on disk. No RAG logic
# depends on this; it's display-only, kept in sync by convention (both
# api.py and app.py run from the project root).
DATA_DIR = Path(__file__).parent / "data" / "pdfs"

st.set_page_config(page_title="Internal Docs Assistant", page_icon="📄", layout="centered")

# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
# history: list of past Q&A turns so they stay visible across reruns
# ingested_files: names already uploaded this session, so a duplicate
#   upload doesn't re-POST the same file twice per rerun.
if "history" not in st.session_state:
    st.session_state.history = []
if "ingested_files" not in st.session_state:
    st.session_state.ingested_files = set()

st.title("📄 Internal Documents Assistant")
st.caption(
    "Ask plain-English questions about HR policies, SOPs, manuals, and onboarding "
    "docs. Answers are grounded only in the PDFs you upload — nothing else."
)

# --------------------------------------------------------------------------
# API reachability check
# --------------------------------------------------------------------------
try:
    api_up = requests.get(f"{API_BASE_URL}/health", timeout=3).status_code == 200
except requests.exceptions.RequestException:
    api_up = False

if not api_up:
    st.error(
        f"Can't reach the API at `{API_BASE_URL}`. Start it with "
        f"`uvicorn api:app --reload` (see README.md), then reload this page."
    )
    st.stop()

# --------------------------------------------------------------------------
# Upload + ingest
# --------------------------------------------------------------------------
st.subheader("1. Upload documents")

uploaded_files = st.file_uploader(
    "Upload one or more PDFs (HR policies, SOPs, manuals, onboarding docs)",
    type=["pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    new_files = [f for f in uploaded_files if f.name not in st.session_state.ingested_files]

    if new_files:
        with st.spinner(f"Embedding {len(new_files)} new document(s)..."):
            try:
                multipart = [("files", (f.name, f.getvalue(), "application/pdf")) for f in new_files]
                resp = requests.post(f"{API_BASE_URL}/ingest", files=multipart, timeout=300)
                if resp.status_code == 200:
                    data = resp.json()
                    for f in new_files:
                        st.session_state.ingested_files.add(f.name)
                    st.success(
                        f"Ingested {len(data['ingested'])} file(s) "
                        f"({data['ingested']}) — {data['chunk_count']} chunks added."
                    )
                else:
                    st.error(f"Ingestion failed: {resp.json().get('detail', resp.text)}")
            except requests.exceptions.RequestException as e:
                st.error(f"Could not reach the API: {e}")

existing_pdfs = sorted(p.name for p in DATA_DIR.glob("*.pdf")) if DATA_DIR.exists() else []
if existing_pdfs:
    with st.expander(f"📚 {len(existing_pdfs)} document(s) currently in the library"):
        for name in existing_pdfs:
            st.write(f"- {name}")
else:
    st.info("No PDFs in the library yet. Upload one above to get started.")

st.divider()

# --------------------------------------------------------------------------
# Ask
# --------------------------------------------------------------------------
st.subheader("2. Ask a question")

question = st.text_input("Your question", placeholder="e.g. How many days of PTO do new hires get?")
ask_clicked = st.button("Ask", type="primary")

if ask_clicked:
    if not question.strip():
        st.warning("Please enter a question before clicking Ask.")
    else:
        with st.spinner("Retrieving relevant passages and generating an answer..."):
            try:
                resp = requests.post(f"{API_BASE_URL}/ask", json={"question": question}, timeout=120)
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state.history.insert(
                        0,
                        {
                            "question": question,
                            "answer": data["answer"],
                            "sources": data["sources"],  # already-formatted citation strings
                            "num_chunks": data["num_chunks"],
                        },
                    )
                elif resp.status_code == 400:
                    st.warning(resp.json().get("detail", "Invalid request."))
                else:
                    st.error(f"API error: {resp.json().get('detail', resp.text)}")
            except requests.exceptions.RequestException as e:
                st.error(f"Could not reach the API: {e}")

# --------------------------------------------------------------------------
# Answer + history
# --------------------------------------------------------------------------
if st.session_state.history:
    st.divider()
    st.subheader("Answer")

    for i, turn in enumerate(st.session_state.history):
        with st.container(border=True):
            st.markdown(f"**Q: {turn['question']}**")
            st.markdown(turn["answer"])

            st.markdown("**Sources**")
            if turn["sources"]:
                for s in turn["sources"]:
                    st.markdown(f"- 📄 {s}")
            else:
                st.caption("No sources — this question was out of scope for the library.")

            st.caption(f"{turn['num_chunks']} chunk(s) retrieved for this answer.")

        if i == 0:
            st.divider()
            st.caption("Previous questions this session:")
