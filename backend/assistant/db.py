"""Postgres persistence for user accounts, the document library, and chat
history.

Chat sessions/messages are per-user -- users.id doubles as the login
username (see assistant/auth.py for password hashing/JWT issuance), so
chat_sessions.user_id is exactly whatever api.get_current_user() decoded
from the caller's JWT, never a client-supplied value. Documents are global
instead: there's one shared Chroma collection for every user's questions to
draw from, so the library listing matches that -- uploaded_by is
attribution only, never a filter.

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
-- id doubles as the login username once an account is registered --
-- password_hash is NULL for any row that predates real auth (there are
-- none left once this migrates cleanly, but nothing else about this table
-- assumes it's non-null).
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    password_hash TEXT,
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

-- Who did what to the shared document library, and when -- the admin
-- password alone doesn't say WHO used it, since it's a shared secret, not a
-- per-user credential. An upload is recorded here once an admin approves it
-- (see pending_documents below), authenticated as whoever originally
-- uploaded it, not whoever approved it.
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL CHECK (action IN ('upload', 'delete')),
    filename TEXT NOT NULL,
    performed_by TEXT NOT NULL REFERENCES users(id),
    performed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON admin_audit_log(performed_at DESC);

-- A user's upload is staged here, not ingested immediately -- file bytes
-- live at staged_path (under a separate PENDING_DIR, not DATA_DIR) until an
-- admin approves or rejects it from the admin app. Approving runs the same
-- ingestion pipeline /ingest used to run inline before, then inserts into
-- `documents`; rejecting just deletes this row and the staged file. Rows
-- are kept (status updated, not deleted) after review, so "pending
-- approvals" (status = 'pending') and admin review history read from the
-- same table.
CREATE TABLE IF NOT EXISTS pending_documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    staged_path TEXT NOT NULL,
    uploaded_by TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    chunk_count INTEGER,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_documents(status, uploaded_at);

-- One row per OpenAI call that has a token cost -- a chat completion (/ask)
-- or an embedding batch (an approved upload's ingestion). cost_usd is an
-- ESTIMATE from assistant/pricing.py's hardcoded per-token rates, not a
-- billing-accurate figure -- OpenAI doesn't return actual dollar cost per
-- call. Feeds the admin monitoring dashboard's tokens/cost/average-usage
-- figures.
CREATE TABLE IF NOT EXISTS token_usage_log (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('chat', 'embedding')),
    model TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER NOT NULL,
    cost_usd NUMERIC(12, 6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_token_usage_time ON token_usage_log(created_at DESC);
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

# One-time migration for a users table created before real accounts existed
# -- CREATE TABLE IF NOT EXISTS above never adds a column to an existing
# table, so an existing volume needs this explicitly.
_MIGRATE_USERS_SQL = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
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
        conn.execute(_MIGRATE_USERS_SQL)
        conn.execute(_MIGRATE_DOCUMENTS_SQL)


def close_db() -> None:
    """Closes the pool -- call once from api.py's shutdown hook so
    connections are released cleanly instead of just dropped when the
    process exits.
    """
    _pool.close()


def create_account(username: str, password_hash: str) -> bool:
    """Returns True if the account was created, False if the username was
    already taken. ON CONFLICT DO NOTHING (not UPSERT) -- two concurrent
    registrations racing for the same username must never let the second
    one silently overwrite the first's password hash.
    """
    with _pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO users (id, password_hash) VALUES (%s, %s) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            (username, password_hash),
        ).fetchone()
    return row is not None


def get_password_hash(username: str) -> str | None:
    with _pool.connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = %s", (username,)
        ).fetchone()
    return row[0] if row else None


def set_password_hash(username: str, password_hash: str) -> bool:
    """Returns True if the account existed and was updated, False if there
    was no such username -- used by both the self-service change-password
    flow (caller already re-verified the old password) and the
    admin-password-gated reset flow (no old password needed at all).
    """
    with _pool.connection() as conn:
        row = conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s RETURNING id",
            (password_hash, username),
        ).fetchone()
    return row is not None


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


def list_all_filenames() -> set[str]:
    """Every currently-known filename -- what /ingest checks a new upload's
    name against to reject a duplicate (see api.py). Combined with
    list_pending_filenames() there, so a name already awaiting approval
    can't be queued a second time either.
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


def get_session_owner(session_id: str) -> str | None:
    """The username chat_sessions.user_id this session belongs to (or None
    if it doesn't exist) -- api.py checks this against the authenticated
    caller before returning a session's messages, so one user can't read
    another's chat by guessing/enumerating session ids.
    """
    with _pool.connection() as conn:
        row = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE id = %s", (session_id,)
        ).fetchone()
    return row[0] if row else None


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


def log_admin_action(action: str, filename: str, performed_by: str) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO admin_audit_log (action, filename, performed_by) VALUES (%s, %s, %s)",
            (action, filename, performed_by),
        )


def list_admin_audit_log(limit: int = 50) -> list[dict]:
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT action, filename, performed_by, performed_at FROM admin_audit_log "
            "ORDER BY performed_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [
        {"action": r[0], "filename": r[1], "performed_by": r[2], "performed_at": r[3].isoformat()}
        for r in rows
    ]


# -- pending_documents (upload-approval queue) --------------------------------


def create_pending_document(pending_id: str, filename: str, staged_path: str, uploaded_by: str) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO pending_documents (id, filename, staged_path, uploaded_by) "
            "VALUES (%s, %s, %s, %s)",
            (pending_id, filename, staged_path, uploaded_by),
        )


def list_pending_filenames() -> set[str]:
    """Filenames currently awaiting approval -- combined with
    list_all_filenames() in api.py so a name already queued can't be
    uploaded a second time by someone else before it's reviewed.
    """
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT filename FROM pending_documents WHERE status = 'pending'"
        ).fetchall()
    return {r[0] for r in rows}


def list_pending_documents_for_user(user_id: str) -> list[dict]:
    """A user's own not-yet-reviewed uploads -- what the chatbot sidebar
    shows as "waiting for admin approval". Never another user's pending
    uploads; see list_all_pending_documents for the admin app's view.
    """
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, filename, uploaded_at FROM pending_documents "
            "WHERE uploaded_by = %s AND status = 'pending' ORDER BY uploaded_at ASC",
            (user_id,),
        ).fetchall()
    return [{"id": r[0], "filename": r[1], "uploaded_at": r[2].isoformat()} for r in rows]


def list_all_pending_documents() -> list[dict]:
    """Every not-yet-reviewed upload, across all users -- the admin app's
    approval queue.
    """
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, filename, uploaded_by, uploaded_at FROM pending_documents "
            "WHERE status = 'pending' ORDER BY uploaded_at ASC"
        ).fetchall()
    return [
        {"id": r[0], "filename": r[1], "uploaded_by": r[2], "uploaded_at": r[3].isoformat()}
        for r in rows
    ]


def get_pending_document(pending_id: str) -> dict | None:
    with _pool.connection() as conn:
        row = conn.execute(
            "SELECT id, filename, staged_path, uploaded_by, status FROM pending_documents "
            "WHERE id = %s",
            (pending_id,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "filename": row[1], "staged_path": row[2], "uploaded_by": row[3], "status": row[4]}


def mark_pending_approved(pending_id: str, chunk_count: int) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "UPDATE pending_documents SET status = 'approved', chunk_count = %s, "
            "reviewed_at = now() WHERE id = %s",
            (chunk_count, pending_id),
        )


def mark_pending_rejected(pending_id: str) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "UPDATE pending_documents SET status = 'rejected', reviewed_at = now() WHERE id = %s",
            (pending_id,),
        )


def count_pending_documents() -> int:
    with _pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*) FROM pending_documents WHERE status = 'pending'"
        ).fetchone()
    return row[0]


# -- token_usage_log (admin monitoring) ---------------------------------------


def log_token_usage(
    kind: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int,
    cost_usd: float,
) -> None:
    with _pool.connection() as conn:
        conn.execute(
            "INSERT INTO token_usage_log "
            "(kind, model, prompt_tokens, completion_tokens, total_tokens, cost_usd) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (kind, model, prompt_tokens, completion_tokens, total_tokens, cost_usd),
        )


def get_usage_summary() -> dict:
    """Aggregate figures for the admin monitoring dashboard: total tokens
    consumed and estimated cost across every logged call (chat +
    embedding), plus the average tokens per /ask call specifically --
    embedding batches vary wildly in size with document length, so folding
    them into the same average would make "average usage" meaningless as a
    per-question figure.
    """
    with _pool.connection() as conn:
        totals = conn.execute(
            "SELECT COALESCE(SUM(total_tokens), 0), COALESCE(SUM(cost_usd), 0) FROM token_usage_log"
        ).fetchone()
        avg_chat = conn.execute(
            "SELECT COALESCE(AVG(total_tokens), 0) FROM token_usage_log WHERE kind = 'chat'"
        ).fetchone()
    return {
        "tokens_consumed": totals[0],
        "cost_usd": float(totals[1]),
        "average_token_usage": float(avg_chat[0]),
    }
