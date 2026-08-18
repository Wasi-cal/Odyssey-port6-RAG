"""
Retrieval + generation pipeline: query -> retrieve -> grounded, cited answer.
This package only READS the persisted Chroma store the ingestion pipeline
builds -- it never writes to it.

    config.py       retrieval tuning (k, search type)
    prompt.py       the grounding prompt + generation model settings
    store.py        the persisted Chroma collection (read handle)
    citations.py    context formatting for the LLM + citation extraction/formatting
    qa.py           RagResult + answer_question(): ties it all together
"""
