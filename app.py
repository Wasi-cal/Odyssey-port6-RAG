"""
app.py — Streamlit UI: upload PDFs, ask questions, see cited answers.

This module never talks to Chroma directly. It calls ingest.ingest_files() to
write new documents in and rag.answer_question() to read grounded answers
out — keeping the read/write split between the three files clean.
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from ingest import DATA_DIR, ingest_files
from rag import answer_question, store_is_empty

load_dotenv()

st.set_page_config(page_title="Internal Docs Assistant", page_icon="📄", layout="centered")

# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
# history: list of past Q&A turns so they stay visible across reruns
# ingested_files: names already saved to data/pdfs/ this session, so a
#   duplicate upload doesn't re-embed the same file twice per rerun.
if "history" not in st.session_state:
    st.session_state.history = []
if "ingested_files" not in st.session_state:
    st.session_state.ingested_files = set()

st.title("📄 Internal Documents Assistant")
st.caption(
    "Ask plain-English questions about HR policies, SOPs, manuals, and onboarding "
    "docs. Answers are grounded only in the PDFs you upload — nothing else."
)

if not os.environ.get("OPENAI_API_KEY"):
    st.error(
        "OPENAI_API_KEY is not set. Copy `.env.example` to `.env`, add your OpenAI "
        "API key, and restart the app."
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
    new_paths = []
    for uploaded in uploaded_files:
        if uploaded.name in st.session_state.ingested_files:
            continue
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = DATA_DIR / uploaded.name
        dest.write_bytes(uploaded.getvalue())
        new_paths.append(dest)
        st.session_state.ingested_files.add(uploaded.name)

    if new_paths:
        with st.spinner(f"Embedding {len(new_paths)} new document(s)..."):
            try:
                chunk_count = ingest_files(new_paths)
                st.success(
                    f"Ingested {len(new_paths)} file(s) "
                    f"({[p.name for p in new_paths]}) — {chunk_count} chunks added."
                )
            except RuntimeError as e:
                st.error(str(e))

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
    elif store_is_empty():
        st.warning("No documents have been ingested yet. Upload a PDF above first.")
    else:
        with st.spinner("Retrieving relevant passages and generating an answer..."):
            try:
                result = answer_question(question)
                st.session_state.history.insert(
                    0,
                    {
                        "question": question,
                        "answer": result.answer,
                        "sources": result.sources,
                        "num_chunks": result.num_chunks_retrieved,
                    },
                )
            except RuntimeError as e:
                st.error(str(e))

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
                    st.markdown(f"- 📄 `{s['source']}` — page {s['page']}")
            else:
                st.caption("No sources — this question was out of scope for the library.")

            st.caption(f"{turn['num_chunks']} chunk(s) retrieved for this answer.")

        if i == 0:
            st.divider()
            st.caption("Previous questions this session:")
