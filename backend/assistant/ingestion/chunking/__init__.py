"""
Token-aware chunking, split by concern:

    tokens.py    tiktoken encoder + the token-budget constants everything
                 else here is sized against
    masking.py   the "{filename} — {section}" chunk header, and masking table
                 regions so the prose splitter never cuts into one
    tables.py    tables are emitted as standalone chunks, never split unless
                 oversized (then split BY ROW, never by raw characters)
    prose.py     the remaining prose, split with a token-aware
                 RecursiveCharacterTextSplitter

Both tables.py and prose.py map their chunks back to the page they start on
and the nearest preceding heading (via ingestion/structure.py).
"""
