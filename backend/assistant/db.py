"""Postgres persistence for the document library and chat history.

Chat sessions/messages are per-user -- for now a per-browser anonymous ID
minted by the frontend (see frontend/doc_assist/domain/identity.py), swapped
for a real authenticated user id once auth exists with no schema changes
needed. Documents are global instead: there's one shared Chroma collection
for every user's questions to draw from, so the library listing matches that
-- uploaded_by is attribution only, never a filter.

Also owns config_settings -- live app configuration (system prompts,
retrieval tuning, etc.), source-of-truth here and read through a Redis cache
by assistant/config_store.py so an edit made directly in Postgres takes
effect without a code change or redeploy.

Owns all reads/writes to Postgres. Vector storage stays in Chroma (see
assistant/ingestion/store.py) -- this module never touches embeddings, only
the "what's been uploaded / asked" metadata that needs to survive a
container restart and browser refresh.
"""

import os
import uuid

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://docassist:docassist@localhost:5432/docassist"
)

# Configurable so pool size can be tuned per-deployment (e.g. bumped for a
# multi-worker uvicorn setup) without a code change. Defaults are plenty for
# this app's traffic today.
DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "10"))

# open=False: don't connect at import time (module is imported by things that
# don't need the DB yet, e.g. during test collection) -- init_db() opens it
# explicitly from api.py's startup hook, and close_db() closes it from the
# same hook's shutdown phase.
_pool = ConnectionPool(
    DATABASE_URL, min_size=DB_POOL_MIN_SIZE, max_size=DB_POOL_MAX_SIZE, open=False
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Global, not per-user: there is one shared Chroma collection for every
-- user's questions to draw from, so the library listing matches that --
-- filename is the primary key (one row per document, period), unlike
-- chat_sessions/chat_messages below which genuinely are per-user.
-- uploaded_by is attribution only, not a filter.
CREATE TABLE IF NOT EXISTS documents (
    filename TEXT PRIMARY KEY,
    uploaded_by TEXT NOT NULL REFERENCES users(id),
    chunk_count INTEGER NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    meta JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, id);

-- One row per setting (category, key) rather than one big JSON blob column
-- -- keeps each value individually editable/queryable in plain SQL. value
-- is JSONB so a setting can be a string (a system prompt), a number (k), or
-- a structured object, without needing a differently-typed column per kind
-- of setting.
CREATE TABLE IF NOT EXISTS config_settings (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category, key)
);
"""


# One-time migration for a database created before documents became global:
# the old schema had a surrogate id + a non-unique filename per user_id
# (one row per (user, filename) pair). Collapses to one row per filename
# (keeping the most recently ingested if the same name had several rows
# under different users), then makes filename the primary key. Guarded by
# the old 'id' column's presence, so this only ever runs once per database
# -- CREATE TABLE IF NOT EXISTS above never touches an existing table's
# columns, so without this the old per-user shape would stick around
# forever on an existing volume.
_MIGRATE_DOCUMENTS_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'id'
    ) THEN
        CREATE TABLE documents_migrated AS
        SELECT DISTINCT ON (filename) filename, user_id AS uploaded_by, chunk_count, ingested_at
        FROM documents
        ORDER BY filename, ingested_at DESC;

        DROP TABLE documents;
        ALTER TABLE documents_migrated RENAME TO documents;
        -- CREATE TABLE ... AS SELECT carries over column TYPES only, not
        -- defaults or NOT NULL -- restore them explicitly, or a fresh
        -- INSERT that omits ingested_at (relying on its old DEFAULT now())
        -- silently gets NULL instead.
        ALTER TABLE documents ALTER COLUMN ingested_at SET DEFAULT now();
        ALTER TABLE documents ALTER COLUMN ingested_at SET NOT NULL;
        ALTER TABLE documents ALTER COLUMN uploaded_by SET NOT NULL;
        ALTER TABLE documents ALTER COLUMN chunk_count SET NOT NULL;
        ALTER TABLE documents ADD PRIMARY KEY (filename);
        ALTER TABLE documents ADD CONSTRAINT documents_uploaded_by_fkey
            FOREIGN KEY (uploaded_by) REFERENCES users(id);
    END IF;
END $$;
"""


def init_db() -> None:
    """Open the pool and create tables if they don't exist yet.

    Called once from api.py's startup hook. Safe to call repeatedly --
    CREATE TABLE/INDEX IF NOT EXISTS -- so a container restart never fails on
    "already exists".
    """
    _pool.open(wait=True)
    with _pool.connection() as conn:
        conn.execute(_SCHEMA_SQL)
        conn.execute(_MIGRATE_DOCUMENTS_SQL)


def close_db() -> None:
    """Closes the pool -- call once from api.py's shutdown hook so
    connections are released cleanly instead of just dropped when the
    process exits.
    """
    _pool.close()


def ensure_user(user_id: str) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO users (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            (user_id,),
        )


def list_documents() -> list[dict]:
    """Every document, for every user -- the library is global (see the
    documents table comment), not filtered by whoever's asking.
    """
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT filename, chunk_count, ingested_at FROM documents ORDER BY ingested_at ASC"
        ).fetchall()
    return [{"name": r[0], "chunk_count": r[1], "ingested_at": r[2].isoformat()} for r in rows]


def add_document(user_id: str, filename: str, chunk_count: int) -> None:
    """Upserts on filename -- a defensive no-op-safe overwrite rather than a
    duplicate-key error, in case this filename already has a row (e.g.
    recovering from a prior partial failure that left disk/Chroma/Postgres
    out of sync with each other).
    """
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO documents (filename, uploaded_by, chunk_count) VALUES (%s, %s, %s) "
            "ON CONFLICT (filename) DO UPDATE SET "
            "uploaded_by = EXCLUDED.uploaded_by, chunk_count = EXCLUDED.chunk_count, ingested_at = now()",
            (filename, user_id, chunk_count),
        )


def delete_document(filename: str) -> None:
    with _pool.connection() as conn:
        conn.execute("DELETE FROM documents WHERE filename = %s", (filename,))


def document_exists(filename: str) -> bool:
    with _pool.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE filename = %s", (filename,)
        ).fetchone()
    return row is not None


def list_all_filenames() -> set[str]:
    """Every currently-known filename -- what /ingest checks a new upload's
    name against to reject a duplicate (see api.py).
    """
    with _pool.connection() as conn:
        rows = conn.execute("SELECT filename FROM documents").fetchall()
    return {r[0] for r in rows}


def create_session(user_id: str) -> dict:
    session_id = str(uuid.uuid4())
    with _pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO chat_sessions (id, user_id) VALUES (%s, %s) "
            "RETURNING id, title, created_at",
            (session_id, user_id),
        ).fetchone()
    return {"id": row[0], "title": row[1], "created_at": row[2].isoformat()}


def list_sessions(user_id: str) -> list[dict]:
    """Sessions that have a title -- i.e. at least one question asked --
    matching the previous in-memory SessionStore's history_sessions()
    behavior of hiding empty/just-created sessions from the sidebar.
    """
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM chat_sessions "
            "WHERE user_id = %s AND title IS NOT NULL ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [{"id": r[0], "title": r[1], "created_at": r[2].isoformat()} for r in rows]


def get_messages(session_id: str) -> list[dict]:
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT role, content, meta FROM chat_messages "
            "WHERE session_id = %s ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [{"role": r[0], "content": r[1], "meta": r[2]} for r in rows]


def add_message(session_id: str, role: str, content: str, meta: dict | None) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, meta) VALUES (%s, %s, %s, %s)",
            (session_id, role, content, Jsonb(meta) if meta is not None else None),
        )


def get_session_title(session_id: str) -> str | None:
    """The session's current title (or None) -- api.py hands this to the
    LLM as context on every /ask call so it can keep, refine, or broaden the
    title as the conversation evolves, rather than it being frozen at
    whatever the first message alone suggested.
    """
    with _pool.connection() as conn:
        row = conn.execute(
            "SELECT title FROM chat_sessions WHERE id = %s", (session_id,)
        ).fetchone()
    return row[0] if row else None


def set_session_title(session_id: str, title: str) -> None:
    """Unconditional -- unlike the library/document rows, a session's title
    is meant to keep changing across its lifetime, not just get set once.
    """
    with _pool.connection() as conn:
        conn.execute(
            "UPDATE chat_sessions SET title = %s WHERE id = %s",
            (title, session_id),
        )


def list_config_settings() -> list[dict]:
    with _pool.connection() as conn:
        rows = conn.execute("SELECT category, key, value FROM config_settings").fetchall()
    return [{"category": r[0], "key": r[1], "value": r[2]} for r in rows]


def seed_config_defaults(defaults: list[dict]) -> None:
    """Inserts each {category, key, value, description} row only if that
    (category, key) doesn't already exist -- never overwrites a value an
    admin has since edited directly in Postgres, so this is safe to call on
    every startup.
    """
    with _pool.connection() as conn:
        for d in defaults:
            conn.execute(
                "INSERT INTO config_settings (category, key, value, description) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (category, key) DO NOTHING",
                (d["category"], d["key"], Jsonb(d["value"]), d.get("description")),
            )
