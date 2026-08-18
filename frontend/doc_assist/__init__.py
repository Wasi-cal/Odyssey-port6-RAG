"""Doc Assist -- Streamlit UI, split by responsibility:

    config.py       static settings (API_BASE_URL, page title, icons, copy)
    application.py  DocAssistApp: wires everything below together
    api/            HTTP client for the FastAPI backend
    domain/         chat data model + the session-state wrapper
    ui/             CSS + every rendered page component

This package is a pure HTTP client of the FastAPI backend (see api/client.py):
no RAG logic, no direct database/LLM access lives here.
"""
