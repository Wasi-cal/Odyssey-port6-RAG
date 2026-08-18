"""assistant -- the actual RAG pipeline, split by responsibility:

    paths.py         shared filesystem locations (data dir, Chroma dir, collection name)
    openai_key.py    the one OPENAI_API_KEY presence check both pipelines use
    embeddings.py    single source of truth for the embedding model
    ingestion/       PDF -> chunk -> embed -> persist (owns writes to chroma_db)
    retrieval/       query -> retrieve -> grounded, cited answer (read-only)

backend/ingest.py and backend/rag.py are thin CLI entrypoints + backward
compatible re-exports over ingestion/ and retrieval/ respectively -- nothing
outside this package (api.py, eval/run_eval.py) had to change to keep working.
"""
