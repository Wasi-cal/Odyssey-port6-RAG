"""app.py — Streamlit UI entrypoint: upload PDFs, ask questions, see cited
answers.

This module is a pure API CLIENT of the FastAPI backend (see ../backend) --
it never imports RAG logic directly. All the actual UI/state/HTTP logic
lives in the doc_assist/ package next to this file; this file just wires it
together and runs it.
"""

import streamlit as st
from dotenv import load_dotenv

from doc_assist.application import DocAssistApp
from doc_assist.config import API_BASE_URL, PAGE_TITLE
from doc_assist.ui.styles import inject as inject_styles

load_dotenv()

st.set_page_config(
    page_title=PAGE_TITLE,
    layout="centered",
    initial_sidebar_state="expanded",
)
inject_styles()

DocAssistApp(API_BASE_URL).run()
