# Internal Documents Assistant (RAG)

A Retrieval-Augmented Generation Q&A tool for internal PDF documents — HR
policies, SOPs, manuals, onboarding docs. Users ask plain-English questions
and get answers grounded ONLY in the uploaded PDFs, with exact
document + page citations.

## Tech stack

- **UI**: Streamlit
- **Orchestration**: LangChain (`langchain`, `langchain-openai`, `langchain-community`, `langchain-chroma`)
- **LLM**: OpenAI `gpt-4o-mini`
- **Embeddings**: OpenAI `text-embedding-3-small`
- **Vector store**: ChromaDB, persisted to disk at `./chroma_db`
- **PDF parsing**: `pypdf`
- **Package manager**: [`uv`](https://docs.astral.sh/uv/)

## Project structure

```
rag-doc-assistant/
├── data/pdfs/          # source PDFs live here
├── chroma_db/          # persisted Chroma store (auto-created, git-ignored)
├── ingest.py           # PDF -> chunk -> embed -> persist to Chroma
├── rag.py              # query -> retrieve -> grounded, cited answer
├── app.py              # Streamlit UI: upload, ask, show answer + sources
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Setup

Requires Python 3.10+ and [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed.

```bash
cd rag-doc-assistant

# Create a virtual environment and install dependencies with uv
uv venv
uv pip install -r requirements.txt

# Add your OpenAI API key
cp .env.example .env
# then edit .env and set OPENAI_API_KEY=sk-...
```

## Run

**1. (Optional) Pre-ingest documents from the command line.**
Drop PDFs into `data/pdfs/` and run:

```bash
uv run ingest.py
```

This builds/updates the persisted Chroma store at `./chroma_db`. You can skip
this step entirely and just upload PDFs through the UI instead — both paths
call the same ingestion code.

**2. Launch the app:**

```bash
uv run streamlit run app.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).

**3. (Optional) Command-line sanity check without the UI:**

```bash
uv run rag.py "How many days of PTO do new hires get?"
```

## How it works

1. **Ingestion** (`ingest.py`): each PDF is loaded page-by-page with
   `PyPDFLoader`, split into chunks with `RecursiveCharacterTextSplitter`,
   embedded with `text-embedding-3-small`, and written into a persisted
   Chroma collection at `./chroma_db`.
2. **Retrieval** (`rag.py`): a question is embedded and matched against the
   Chroma collection using MMR search (`k=4`) so the returned chunks are
   relevant *and* diverse rather than near-duplicates of the same passage.
3. **Generation** (`rag.py`): the retrieved chunks are inserted into a strict
   grounding prompt sent to `gpt-4o-mini`. The model is instructed to answer
   only from that context, and to reply with an exact fallback sentence if
   the answer isn't in the retrieved passages.
4. **Citations** (`rag.py` + `app.py`): every retrieved chunk's
   `{"source", "page"}` metadata is deduplicated and shown under a "Sources"
   section in the UI, so every answer is traceable back to an exact document
   and page.

## Design decisions & rationale

- **Chunk size 800 / overlap 150** (`ingest.py`, top of file): 800 characters
  holds roughly one coherent paragraph or policy clause — enough for the
  embedding to capture a complete idea without blending multiple unrelated
  ideas into one vector. 150 characters of overlap (~18%) protects rules or
  definitions that straddle a chunk boundary, so a fact split across two
  chunks by the splitter is still retrievable from either one.
- **MMR retrieval** (`rag.py`): plain top-k similarity search tends to return
  several near-duplicate chunks of the same passage. MMR re-ranks for
  relevance *and* diversity, so the k=4 chunks handed to the LLM cover more
  of the actual document content.
- **Strict grounding prompt** (`rag.py`): the system prompt forbids outside
  knowledge and mandates the exact string `"I don't know based on the
  provided documents."` when the context doesn't answer the question — this
  is checked verbatim in code so the UI never silently shows a hallucinated
  answer with fake sources.
- **Persisted Chroma, not an in-memory list**: `Chroma(persist_directory=...)`
  writes vectors and metadata to disk in `./chroma_db`, so the app doesn't
  need to re-embed documents on every restart, and multiple app runs share
  one durable knowledge base.

## Acceptance criteria

| ID | Requirement | How it's met |
|----|-------------|---------------|
| **M6S1** | Chunk size/overlap are intentional, documented constants with a written rationale. | `CHUNK_SIZE = 800` / `CHUNK_OVERLAP = 150` defined at the top of `ingest.py`, with the rationale in a comment directly above them and repeated above. |
| **M6S2** | Embeddings are persisted in Chroma on disk (`./chroma_db`), not a Python list. | `ingest.get_vector_store()` and `rag.get_retriever()` both construct `Chroma(persist_directory="./chroma_db", ...)`; nothing in the app holds embeddings in memory across runs. |
| **M6S3** | Retrieval returns the relevant chunks for real questions; citations match content. | `rag.py` uses MMR similarity search (`k=4`) against the persisted collection, and the returned `Document` objects (with original metadata) are what both the LLM context and the citation list are built from — the same chunk text drives both. |
| **M6S4** | Every answer shows the exact source document and page it came from. | Metadata `{"source": <filename>, "page": <page_number>}` is captured at ingestion (`ingest.load_and_split`) and rendered as a deduplicated "Sources" list in `app.py`. |
| **M6S5** | Out-of-scope questions return `"I don't know based on the provided documents."` — no hallucination. | The system prompt in `rag.py` mandates this exact sentence when context is insufficient, and the app checks for it verbatim to suppress a misleading "Sources" list on that path. |
| **M6S6** | A never-before-seen PDF works end-to-end just by uploading it — nothing hardcoded per document. | `app.py`'s file uploader saves any PDF to `data/pdfs/` and calls the generic `ingest.ingest_files()` — there is no document-specific logic anywhere in the pipeline. |

## Error handling

- **Missing API key**: both `rag.py`/`ingest.py` (CLI) and `app.py` (UI)
  check for `OPENAI_API_KEY` up front and show a clear message instead of a
  raw stack trace.
- **No PDFs yet**: the UI shows an info banner, and asking a question before
  any document is ingested returns the same "I don't know..." fallback
  instead of erroring.
- **Empty query**: the UI blocks submission with a warning; `rag.py`'s
  `answer_question("")` returns a friendly prompt instead of calling the LLM.
# Odyssey-port6-RAG
