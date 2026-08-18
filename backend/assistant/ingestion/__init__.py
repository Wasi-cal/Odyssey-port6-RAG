"""
Ingestion pipeline: PDF -> chunk -> embed -> persist to Chroma. This package
OWNS writes to chroma_db/; retrieval/ only ever reads from it.

Pipeline (per PDF), each stage its own module:
  1. extraction.py    per-page Markdown text via pymupdf4llm, with an OCR
                       fallback for pages that yield little/no text (scans).
  2. boilerplate.py    strip repeated headers/footers, "Page X of Y", etc.
  3. structure.py      concatenate all pages into one text stream (so
                       chunking/overlap can span page boundaries), and detect
                       section headings + markdown table blocks across it.
  4. chunking.py       emit each table as its own dedicated chunk (never
                       split mid-table), and split the remaining prose with a
                       token-aware splitter. Maps every chunk back to the
                       page it STARTS on and the nearest preceding heading.
  5. store.py          the persisted Chroma collection (write handle).
  6. pipeline.py       orchestrates the above end to end.
"""
