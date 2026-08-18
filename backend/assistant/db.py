"""Postgres persistence for the document library and chat history, keyed by
user_id -- for now a per-browser anonymous ID minted by the frontend (see
frontend/doc_assist/domain/identity.py), swapped for a real authenticated
user id once auth exists with no schema changes needed.

Also owns config_settings -- live app configuration (system prompts,
retrieval tuning, etc.), source-of-truth here and read through a Redis cache
by assistant/config_store.py so an edit made directly in Postgres takes
effect without a code change or redeploy.

Owns all reads/writes to Postgres. Vector storage stays in Chroma (see
assistant/ingestion/store.py) -- this module never touches embeddings, only
the "what did this user upload / ask" metadata that needs to survive a
container restart and browser refresh.
"""

import os
import uuid

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://docassist:docassist@localhost:5432/docassist"
)

# open=False: don't connect at import time (module is imported by things that
# don't need the DB yet, e.g. during test collection) -- init_db() opens it
# explicitly from api.py's startup hook.
_pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id);

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


def init_db() -> None:
    """Open the pool and create tables if they don't exist yet.

    Called once from api.py's startup hook. Safe to call repeatedly --
    CREATE TABLE/INDEX IF NOT EXISTS -- so a container restart never fails on
    "already exists".
    """
    _pool.open(wait=True)
    with _pool.connection() as conn:
        conn.execute(_SCHEMA_SQL)


def ensure_user(user_id: str) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO users (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            (user_id,),
        )


def list_documents(user_id: str) -> list[dict]:
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT filename, chunk_count, ingested_at FROM documents "
            "WHERE user_id = %s ORDER BY ingested_at ASC",
            (user_id,),
        ).fetchall()
    return [{"name": r[0], "chunk_count": r[1], "ingested_at": r[2].isoformat()} for r in rows]


def add_document(user_id: str, filename: str, chunk_count: int) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO documents (user_id, filename, chunk_count) VALUES (%s, %s, %s)",
            (user_id, filename, chunk_count),
        )


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


def set_session_title_if_unset(session_id: str, title: str) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "UPDATE chat_sessions SET title = %s WHERE id = %s AND title IS NULL",
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
