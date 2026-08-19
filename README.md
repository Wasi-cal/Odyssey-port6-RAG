# Doc Assist

**The internal knowledge assistant that answers policy questions instantly — and never makes one up.**

Doc Assist turns your HR policies, SOPs, and onboarding materials into a chatbot every employee can just *ask*. Every answer is grounded in an actual document and cited down to the page, every upload is reviewed by an admin before it's live, and every dollar spent on it is visible on a dashboard — not buried in an API bill you find out about at the end of the month.

---

## Why teams use this

**HR and IT stop answering the same five questions a hundred times a week.** "How many PTO days do I get?" "What's the remote work policy?" "How do I submit an expense report?" — the answers already exist, scattered across a dozen PDFs nobody reads end to end. Doc Assist reads all of them and answers in seconds, in plain language, with a citation pointing straight to the source paragraph.

**It won't guess, and it won't be tricked into guessing.** Most "AI chatbot" pilots die the first time someone screenshots it confidently inventing a policy that doesn't exist. This one is built to refuse instead: if the documents don't cover it, it says so and points to a human. If someone tries to jailbreak it — "ignore your instructions," a prompt buried inside an uploaded PDF, a request for something genuinely harmful — it's explicitly hardened to recognize that and decline, not comply.

**Nothing goes live without a human saying so.** Anyone can upload a document, but it sits in a review queue until an admin approves it — no accidental leaks of a draft policy, no employee quietly slipping in their own "reference material" that the whole company starts getting answers from.

**You can see exactly what it's costing you, in real time.** A dedicated admin dashboard — separate login, nothing an ordinary user ever sees — shows pending approvals, how many document chunks are actually indexed, tokens consumed, and an estimated dollar cost, live. No surprises, no digging through an OpenAI billing page to reverse-engineer what happened.

**It's yours to tune, not a black box.** The system prompt, the model, retrieval behavior, pricing assumptions, session lengths, rate limits — all editable live from the database, no redeploy, no waiting on an engineering ticket to change how the assistant talks.

### At a glance

| | |
|---|---|
| 💬 **Ask, don't search** | Plain-English questions, grounded answers, exact document + page citations |
| 🧠 **Remembers the conversation** | Follow-up questions ("what about part-time employees?") resolve against what was already discussed |
| 🛡️ **Refuses what it should** | Won't hallucinate, won't be prompt-injected, won't answer a dangerous request even if a document technically covers it |
| ✅ **Human-in-the-loop uploads** | Every new document is queued for admin approval before it's searchable |
| 📊 **Live cost & usage dashboard** | Pending approvals, index size, tokens consumed, estimated spend — one page, no billing archaeology |
| 🔐 **Separate admin surface** | A distinct login, distinct credentials, distinct app — regular users never see admin controls, let alone use them |
| ⚙️ **Configurable without a redeploy** | Prompts, pricing, session/lockout windows all live in the database, editable on the fly |
| 🔁 **Durable ingestion** | Large uploads and transient API hiccups are retried automatically, per-file, without redoing a whole batch |



## How it's built

The rest of this document is for the people who'll run, extend, or audit it.

### Architecture

Doc Assist is a small set of cooperating services, not one monolith:

```
                    ┌─────────────┐
   Browser ───TLS──►│    Caddy    │  (reverse proxy, self-signed local cert)
                    └──────┬──────┘
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
        ┌────────┐   ┌──────────┐   ┌───────────┐
        │   ui    │   │   api    │   │ admin-ui  │
        │(Streamlit) │ (FastAPI) │  │(Streamlit) │
        └────────┘   └────┬─────┘   └───────────┘
                           │
        ┌──────────────────┼──────────────────┬─────────────┐
        ▼                  ▼                  ▼             ▼
   ┌──────────┐      ┌──────────┐      ┌───────────┐  ┌───────────┐
   │  app-db   │      │  redis   │      │  Chroma    │  │ Temporal  │
   │(Postgres) │      │ (config  │      │ (vectors,  │  │ (durable  │
   │ accounts, │      │  cache + │      │  on disk)  │  │ ingestion │
   │ chats,    │      │  login   │      └───────────┘  │ workflow) │
   │ documents,│      │ lockout) │                      └─────┬─────┘
   │ usage log │      └──────────┘                            │
   └──────────┘                                          ┌────┴────┐
                                                          │ worker  │
                                                          │(extract/│
                                                          │ chunk/  │
                                                          │ embed)  │
                                                          └─────────┘
```

- **`ui`** — the chatbot (Streamlit). Login/register, chat, upload, library, chat history. Talks to `api` over HTTP only; owns no business logic.
- **`admin-ui`** — a second, independent Streamlit app (`frontend/admin_app.py`). Its own login (a shared admin password, never the same credential space as regular users), one page: approve/reject pending uploads, usage/cost dashboard, audit log, reset a user's password, change the admin password.
- **`api`** (FastAPI) — the only thing that touches the database, the vector store, or OpenAI. Issues and verifies two structurally distinct JWT types (user vs. admin) so one can never be replayed as the other.
- **`worker`** — a Temporal worker that does the actual extraction/chunking/embedding for an approved upload, one activity per file, retried independently on transient failure.
- **Postgres** — accounts, chat sessions/messages, the document library, the upload-approval queue, the admin audit log, token/cost usage log, and all hot-reloadable app configuration.
- **Redis** — a cache-aside layer in front of that configuration (so reading it on every request doesn't hit Postgres), plus login-attempt counters for rate limiting.
- **Chroma** — the vector store, persisted to disk, holding document chunk embeddings.
- **Caddy** — TLS termination for the three browser-facing services (chat, API, admin), each on the same port they'd otherwise expose directly, just over HTTPS.

### Tech stack

- **Backend**: FastAPI, Python
- **Frontend**: Streamlit (two separate apps: chatbot + admin)
- **LLM**: OpenAI `gpt-4o-mini` (generation), `text-embedding-3-small` (embeddings) — both swappable via live config
- **RAG orchestration**: LangChain (`langchain-openai`, `langchain-chroma`)
- **Vector store**: ChromaDB, persisted to disk
- **Relational store**: PostgreSQL (accounts, chat history, document library, config, usage/cost logs)
- **Cache / rate limiting**: Redis
- **Durable ingestion**: Temporal (workflow + per-file activities, automatic retry)
- **Auth**: JWT (`PyJWT`), bcrypt password hashing, two independent token types (user / admin)
- **TLS**: Caddy, self-signed local CA for local/dev deployment
- **PDF parsing**: `pymupdf4llm` (Markdown-aware extraction) with an OCR fallback (`pytesseract`) for scanned pages
- **Tokenization / cost estimation**: `tiktoken`

### Project structure

```
.
├── backend/
│   ├── api.py                       # FastAPI app -- the only process touching DB/vectors/OpenAI
│   ├── ingest.py, rag.py            # thin CLI/re-export entrypoints
│   ├── worker.py                    # Temporal worker entrypoint
│   ├── assistant/
│   │   ├── auth.py                  # password hashing, user + admin JWTs
│   │   ├── db.py                    # all Postgres reads/writes
│   │   ├── config_store.py          # Redis-cached, Postgres-backed live config
│   │   ├── rate_limit.py            # login lockout counters
│   │   ├── pricing.py               # token cost estimation
│   │   ├── embeddings.py            # embedding model config + token counting
│   │   ├── ingestion/               # extraction, chunking, boilerplate stripping, Chroma writes
│   │   ├── retrieval/               # retriever, grounding prompt, citations, Q&A orchestration
│   │   └── orchestration/           # Temporal workflow + activities + client
│   └── eval/                        # golden-question regression suite (imports rag.py directly)
├── frontend/
│   ├── app.py                       # chatbot entrypoint
│   ├── admin_app.py                 # admin login + monitoring, one page
│   └── doc_assist/                  # chatbot UI components, API client, session/auth state
├── docker-compose.yml                # api, worker, ui, admin-ui, Postgres, Redis, Temporal, Caddy
├── Caddyfile                          # TLS termination config
└── README.md
```

### Setup & run (Docker Compose)

This is the supported path — it wires up Postgres, Redis, Temporal, the worker, both frontends, and TLS together.

```bash
cp backend/.env.example backend/.env
# edit backend/.env: set OPENAI_API_KEY, JWT_SECRET, ADMIN_PASSWORD
# (JWT_SECRET: python -c "import secrets; print(secrets.token_hex(32))")

docker compose up --build
```

Then, over HTTPS (Caddy issues a self-signed cert for local dev — accept the browser warning once, or trust its local CA, see the Caddyfile):

- Chatbot: `https://localhost:8501`
- API: `https://localhost:8000` (`curl -k https://localhost:8000/health`)
- Admin app: `https://localhost:8502`

`ADMIN_PASSWORD`, `JWT_EXPIRY_DAYS`, and a handful of other values in `backend/.env` are **seed values only** — they set the initial row in Postgres on first boot and are ignored after that. From then on, change them live via the admin app (password) or by editing the `config_settings` table directly (everything else) — see below.

### Configuration, live, no redeploy

Almost everything operationally interesting lives in Postgres' `config_settings` table, cached through Redis with a short TTL, edited either directly in the database or (for the admin password) from the admin app itself:

- **`generation`** — system prompt, per-fallback response text, model, temperature, how many prior chat messages are replayed as context
- **`retrieval`** — chunk count (`k`), search strategy
- **`embeddings`** — embedding model name
- **`pricing`** — per-token cost estimates feeding the admin dashboard
- **`auth`** — admin password, JWT session lengths
- **`rate_limit`** — failed-login lockout thresholds

Edit a row, and it takes effect app-wide within seconds — no code change, no restart.

### Security notes

- User and admin authentication are fully separate: distinct JWT claims, distinct login endpoints, distinct frontends — a user token is structurally rejected by every admin-only endpoint and vice versa.
- Login is rate-limited by both username and source IP (Redis-backed, fails open if Redis itself is down, since refusing every login over a rate-limiter hiccup is worse for an internal tool than the rare abuse window).
- The generation prompt carries a code-level (non-admin-editable) instruction that retrieved document content and prior chat turns are untrusted data, not commands — defense against a malicious PDF or message trying to override the assistant's behavior.
- The model is explicitly instructed to refuse a request that could help cause real-world harm, independent of and in addition to an OpenAI Moderation API pass on the raw input.
- Uploads are content-hashed (SHA-256) for duplicate detection, not compared by filename, which is unreliable.
- Browser-facing traffic is HTTPS via Caddy. Container-to-container traffic on the private Compose network is plain HTTP by design — see the Caddyfile's comments for the reasoning and what that would mean in a multi-host deployment.

### Local (non-Docker) development

Each of `backend/` and `frontend/` has its own `requirements.txt` and virtualenv — the frontend never imports `langchain`/`chromadb`/etc. directly, it's a pure HTTP client of the API.

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OPENAI_API_KEY, JWT_SECRET, ADMIN_PASSWORD
uvicorn api:app --reload

# Temporal + worker (ingestion won't run without these)
temporal server start-dev
python worker.py

# Frontend (chatbot)
cd frontend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py

# Frontend (admin app)
streamlit run admin_app.py --server.port 8502
```

Postgres and Redis are still required even outside Docker — point `DATABASE_URL` / `REDIS_URL` in `backend/.env` at wherever you're running them.

### Eval suite

`backend/eval/` runs a golden-question regression set directly against `rag.py` (not through the API), scoring recall, citation precision/recall, and refusal accuracy — useful for confirming a prompt or retrieval tuning change didn't regress answer quality.

```bash
cd backend
python eval/run_eval.py
```
