# =============================================================================
# backend/src/conversation/memory.py
# Redis-based session management and SQLite persistence for Daraz Voice Assistant.
#
# Changes from original:
#   - Sessions now carry user_id (set at WebSocket connect from JWT)
#   - build_inference_payload() prepends the CRM context block to the system prompt
#   - micro_compact() is called after every turn to clear consumed tool results
#   - Session dict gains: user_id, turn_count, crm_dirty
# =============================================================================

import json
import re
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import redis
import bleach

from src.config import (
    REDIS_URL,
    REDIS_SESSION_TTL,
    build_system_prompt,
    CONTEXT_BUDGET_TOKENS,
    MAX_TURNS,
    WELCOME_MESSAGE,
)

logger = logging.getLogger(__name__)

# =============================================================================
# REDIS CLIENT
# =============================================================================
_redis: redis.Redis = redis.from_url(REDIS_URL, decode_responses=True)
_SESSION_PREFIX = "session:"


def _key(session_id: str) -> str:
    """Namespaced Redis key for a session."""
    return f"{_SESSION_PREFIX}{session_id}"


# =============================================================================
# LEGACY SYNC DATABASE (SQLite — kept for backward compat with existing sessions)
# New code should use src.db (aiosqlite) for new tables.
# =============================================================================
_DB_DIR = os.getenv("DB_DIR", "/data")
_DB_PATH = os.path.join(_DB_DIR, "sessions.db")


def _get_connection() -> sqlite3.Connection:
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _sanitize(text: str) -> str:
    """Strips all HTML/JS from a string before it enters SQLite."""
    return bleach.clean(text, tags=[], attributes={}, strip=True)


# =============================================================================
# SCHEMA (existing tables only — new tables are in src/db.py)
# =============================================================================
def init_db() -> None:
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id  TEXT PRIMARY KEY,
                title       TEXT DEFAULT 'New Chat',
                state       TEXT DEFAULT '{}',
                turns       INTEGER DEFAULT 0,
                status      TEXT DEFAULT 'active',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id);

            CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions(updated_at DESC);
        """)
        conn.commit()
        logger.info(f"[database] Initialized SQLite at {_DB_PATH}")
    finally:
        conn.close()


# =============================================================================
# SESSION CRUD (legacy sync layer)
# =============================================================================
def save_session(session_id: str, session_data: dict) -> None:
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        title = "New Chat"
        for msg in session_data.get("history", []):
            if msg.get("role") == "user" and msg.get("content"):
                raw_title = _sanitize(str(msg["content"]))[:50]
                title = raw_title + ("..." if len(str(msg["content"])) > 50 else "")
                break

        conn.execute(
            """
            INSERT INTO sessions (session_id, title, state, turns, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                title      = excluded.title,
                state      = excluded.state,
                turns      = excluded.turns,
                status     = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                title,
                json.dumps(session_data.get("state", {})),
                session_data.get("turns", 0),
                session_data.get("status", "active"),
                now,
                now,
            ),
        )

        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for msg in session_data.get("history", []):
            safe_content = _sanitize(str(msg.get("content") or ""))
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, msg.get("role", "unknown"), safe_content, now),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"[database] Error saving session {session_id}: {e}")
    finally:
        conn.close()


def load_session(session_id: str) -> Optional[dict]:
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        messages = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return {
            "history":     [{"role": m["role"], "content": m["content"]} for m in messages],
            "state":       json.loads(row["state"]) if row["state"] else {},
            "turns":       row["turns"],
            "status":      row["status"],
            # user_id / turn_count not in legacy table — default to None/0
            "user_id":     None,
            "turn_count":  0,
            "crm_dirty":   False,
        }
    except Exception as e:
        logger.error(f"[database] Error loading session {session_id}: {e}")
        return None
    finally:
        conn.close()


def list_sessions() -> list:
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT s.session_id, s.title, s.status, s.turns,
                   s.created_at, s.updated_at,
                   COUNT(m.id) as message_count
            FROM sessions s
            LEFT JOIN messages m ON s.session_id = m.session_id
            GROUP BY s.session_id
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
        sessions = []
        for row in rows:
            last_msg = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (row["session_id"],),
            ).fetchone()
            preview = ""
            if last_msg:
                preview = last_msg["content"][:80]
                if len(last_msg["content"]) > 80:
                    preview += "..."
            sessions.append({
                "session_id":    row["session_id"],
                "title":         row["title"],
                "status":        row["status"],
                "turns":         row["turns"],
                "message_count": row["message_count"],
                "created_at":    row["created_at"],
                "updated_at":    row["updated_at"],
                "preview":       preview,
            })
        return sessions
    except Exception as e:
        logger.error(f"[database] Error listing sessions: {e}")
        return []
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    conn = _get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[database] Error deleting session {session_id}: {e}")
        return False
    finally:
        conn.close()


def load_all_sessions_to_memory() -> dict:
    conn = _get_connection()
    result = {}
    try:
        rows = conn.execute("SELECT session_id FROM sessions").fetchall()
        for row in rows:
            session = load_session(row["session_id"])
            if session:
                result[row["session_id"]] = session
        return result
    except Exception as e:
        logger.error(f"[database] Error loading sessions: {e}")
        return {}
    finally:
        conn.close()


# =============================================================================
# REDIS SESSION HELPERS
# =============================================================================
def _load_from_redis(session_id: str) -> Optional[dict]:
    try:
        raw = _redis.get(_key(session_id))
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.error(f"[context] Redis read error for {session_id}: {e}")
    return None


def _save_to_redis(session_id: str, session: dict) -> None:
    try:
        _redis.setex(_key(session_id), REDIS_SESSION_TTL, json.dumps(session))
    except Exception as e:
        logger.error(f"[context] Redis write error for {session_id}: {e}")


def _delete_from_redis(session_id: str) -> None:
    try:
        _redis.delete(_key(session_id))
    except Exception as e:
        logger.error(f"[context] Redis delete error for {session_id}: {e}")


# =============================================================================
# PUBLIC SESSION API
# =============================================================================
_STATE_PATTERN    = re.compile(r"<STATE>\s*(.*?)(?:</STATE>|$)", re.DOTALL | re.IGNORECASE)
_STATE_KV_PATTERN = re.compile(r"(Budget|Item|Preferences|Resolved)\s*:\s*([^,<]+)", re.IGNORECASE)


def init_sessions_from_db() -> None:
    init_db()
    loaded = load_all_sessions_to_memory()
    for session_id, session in loaded.items():
        _save_to_redis(session_id, session)
    logger.info(f"[context] Loaded {len(loaded)} sessions from DB → Redis")


def _make_empty_session(user_id: Optional[str] = None) -> dict:
    """Canonical empty session structure with all fields."""
    return {
        "history":    [],
        "state": {
            "budget":      None,
            "item":        None,
            "preferences": None,
            "resolved":    "no",
        },
        "turns":      0,
        "status":     "active",
        # New fields
        "user_id":    user_id,
        "turn_count": 0,
        "crm_dirty":  False,
    }


def get_or_create_session(session_id: str, user_id: Optional[str] = None) -> dict:
    """
    Returns the session dict from Redis (hot path), falls back to SQLite,
    or creates a new session. If user_id is provided and the session doesn't
    have one yet, it is set here.
    """
    session = _load_from_redis(session_id)
    if session:
        # Backfill user_id if session was created before auth was added
        if user_id and not session.get("user_id"):
            session["user_id"] = user_id
            _save_to_redis(session_id, session)
        return session

    db_session = load_session(session_id)
    if db_session:
        if user_id and not db_session.get("user_id"):
            db_session["user_id"] = user_id
        _save_to_redis(session_id, db_session)
        return db_session

    session = _make_empty_session(user_id=user_id)
    _save_to_redis(session_id, session)
    return session


def add_message_to_chat(session_id: str, role: str, text: str) -> None:
    """Hot path: append message and write to Redis only. SQLite is flushed in background."""
    session = get_or_create_session(session_id)
    session["history"].append({"role": role, "content": text})
    _save_to_redis(session_id, session)
    # SQLite write deferred — call flush_session_to_db() in a background task


def apply_micro_compact(session_id: str) -> None:
    """Hot path: compact history in Redis only. SQLite flushed separately."""
    from src.conversation.compaction import micro_compact, estimate_tokens
    session = get_or_create_session(session_id)
    before = estimate_tokens(session["history"])
    session["history"] = micro_compact(session["history"])
    after = estimate_tokens(session["history"])
    _save_to_redis(session_id, session)
    if before != after:
        logger.debug(f"[micro_compact] session={session_id} tokens {before}→{after}")


def get_chat_history(session_id: str) -> list:
    return get_or_create_session(session_id)["history"]


def get_session_state(session_id: str) -> dict:
    return get_or_create_session(session_id)["state"]


def get_session_status(session_id: str) -> str:
    return get_or_create_session(session_id)["status"]


def set_session_status(session_id: str, status: str) -> None:
    """Hot path: status update to Redis only."""
    session = get_or_create_session(session_id)
    session["status"] = status
    _save_to_redis(session_id, session)


def increment_turn(session_id: str) -> None:
    """Hot path: turn increment to Redis only."""
    session = get_or_create_session(session_id)
    session["turns"] += 1
    _save_to_redis(session_id, session)


def flush_session_to_db(session_id: str) -> None:
    """Persist current Redis session state to SQLite. Call from a background thread."""
    session = _load_from_redis(session_id)
    if session:
        save_session(session_id, session)


def is_session_maxed(session_id: str) -> bool:
    return get_or_create_session(session_id)["turns"] >= MAX_TURNS


def reset_session(session_id: str) -> None:
    session = _load_from_redis(session_id)
    if session:
        save_session(session_id, session)
        _delete_from_redis(session_id)


def list_active_sessions() -> list:
    try:
        keys = _redis.keys(f"{_SESSION_PREFIX}*")
        return [k.replace(_SESSION_PREFIX, "") for k in keys]
    except Exception as e:
        logger.error(f"[context] Redis keys error: {e}")
        return []


def get_welcome_message(session_id: str) -> dict:
    get_or_create_session(session_id)
    return {
        "session_id": session_id,
        "response":   WELCOME_MESSAGE,
        "latency_ms": 0.0,
        "status":     "active",
        "turns_used": 0,
        "turns_max":  MAX_TURNS,
    }


def _fit_history_to_budget(history: list, budget_tokens: int) -> list:
    """
    Return the longest suffix of `history` whose estimated token count is
    within `budget_tokens`.  Trims from the oldest messages first so the
    model always sees the most recent context.
    """
    from src.conversation.compaction import estimate_tokens
    if estimate_tokens(history) <= budget_tokens:
        return history  # already fits — no trim needed

    # Walk from the back, accumulating messages until we hit the budget
    selected = []
    running_tokens = 0
    for msg in reversed(history):
        msg_tokens = estimate_tokens([msg])
        if running_tokens + msg_tokens > budget_tokens:
            break
        selected.append(msg)
        running_tokens += msg_tokens

    return list(reversed(selected))


def build_inference_payload(
    session_id: str,
    new_user_message: str,
    rag_context: str = "",
) -> list:
    """
    Builds the messages list for a single LLM call.

    History is trimmed to CONTEXT_BUDGET_TOKENS using a token-budget-aware
    sliding window (oldest messages dropped first) instead of a fixed turn
    count, so we never blow the context window regardless of message length.

    RAG context is ephemeral — injected into a copy of the system message
    used ONLY for this call. It is NOT appended to session["history"].

    CRM context block is prepended to the system prompt when user_id is available.
    The block is rebuilt if session["crm_dirty"] is True (set by handle_crm_tool).
    """
    session = get_or_create_session(session_id)

    # Build CRM context block (cached on session to avoid per-token DB hits)
    crm_block = session.get("_cached_crm_block", "")
    if session.get("crm_dirty") or (not crm_block and session.get("user_id")):
        user_id = session.get("user_id")
        if user_id:
            # Sync fallback: fetch from Redis-cached session state.
            # Async fetch happens in the engine's async turn handler instead.
            # Here we use the last-known cached value; _cached_crm_block is
            # updated by engine.llm after an async CRM fetch.
            pass
        session["crm_dirty"] = False
        _save_to_redis(session_id, session)

    crm_block = session.get("_cached_crm_block", "")

    system_msg = {
        "role":    "system",
        "content": crm_block + build_system_prompt(session["state"], rag_context=rag_context),
    }

    # Token-budget-aware trim: keep the most recent messages that fit
    trimmed = _fit_history_to_budget(session["history"], CONTEXT_BUDGET_TOKENS)
    return [system_msg] + trimmed + [{"role": "user", "content": new_user_message}]


async def refresh_crm_block(session_id: str) -> None:
    """
    Async: fetch the CRM profile and cache the block on the session.
    Called once per session init and whenever crm_dirty is set.
    """
    session = get_or_create_session(session_id)
    user_id = session.get("user_id")
    if not user_id:
        return
    try:
        from src.tools.crm import get_profile, build_crm_context_block
        profile  = await get_profile(user_id)
        crm_block = build_crm_context_block(profile)
        session["_cached_crm_block"] = crm_block
        session["crm_dirty"] = False
        _save_to_redis(session_id, session)
    except Exception as e:
        logger.warning(f"[memory] refresh_crm_block failed for {session_id}: {e}")


def extract_and_strip_state(session_id: str, raw_response: str) -> str:
    session = get_or_create_session(session_id)
    match = _STATE_PATTERN.search(raw_response)
    if match:
        _update_state_from_block(session["state"], match.group(1))
        _save_to_redis(session_id, session)
    clean = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()
    clean = _STATE_PATTERN.sub("", clean).strip()
    clean = re.sub(r"Resolved\s*:\s*(yes|no)", "", clean, flags=re.IGNORECASE).strip()
    return clean


def is_conversation_resolved(session_id: str) -> bool:
    state = get_or_create_session(session_id)["state"]
    return state.get("resolved", "no").lower().strip() == "yes"


def _update_state_from_block(state: dict, state_block: str) -> None:
    for match in _STATE_KV_PATTERN.finditer(state_block):
        key   = match.group(1).strip().lower()
        value = match.group(2).strip()
        if value.lower() in ("unknown", "none", "n/a", ""):
            continue
        state[key] = value
