"""
জনগণের কণ্ঠস্বর — Database layer
Supports both PostgreSQL (Render) and SQLite (local dev).
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta

from config import DATABASE_URL, DATABASE_PATH

BDT = timezone(timedelta(hours=6))

# Detect database type
USE_POSTGRES = bool(DATABASE_URL)


def _get_conn():
    """Return a database connection."""
    if USE_POSTGRES:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(DATABASE_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def _fetchone(conn, query, params=()):
    """Fetch one row as dict."""
    if USE_POSTGRES:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params)
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    else:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def _fetchall(conn, query, params=()):
    """Fetch all rows as list of dicts."""
    if USE_POSTGRES:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    else:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def _execute(conn, query, params=()):
    """Execute a query."""
    if USE_POSTGRES:
        cur = conn.cursor()
        cur.execute(query, params)
        cur.close()
    else:
        conn.execute(query, params)


def _adapt_query(query):
    """Convert SQLite ? placeholders to PostgreSQL %s."""
    if USE_POSTGRES:
        return query.replace("?", "%s")
    return query


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    if USE_POSTGRES:
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                body TEXT DEFAULT '',
                image_url TEXT DEFAULT '',
                category TEXT DEFAULT 'bangladesh',
                source_name TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                url_hash TEXT UNIQUE,
                views INTEGER DEFAULT 0,
                ai_written INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                published_at TIMESTAMP DEFAULT NOW()
            )
        """)
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS agent_log (
                id SERIAL PRIMARY KEY,
                message TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        _execute(conn, """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Indexes
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category)")
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC)")
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_posts_image ON posts(image_url)")
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_posts_hash ON posts(url_hash)")
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                body TEXT DEFAULT '',
                image_url TEXT DEFAULT '',
                category TEXT DEFAULT 'bangladesh',
                source_name TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                url_hash TEXT UNIQUE,
                views INTEGER DEFAULT 0,
                ai_written INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                published_at TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category);
            CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_posts_image ON posts(image_url);
            CREATE INDEX IF NOT EXISTS idx_posts_hash ON posts(url_hash);

            CREATE TABLE IF NOT EXISTS agent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

    # Default settings
    for k, v in [("agent_enabled", "1"), ("agent_interval", "20"), ("post_count", "0")]:
        try:
            _execute(conn, _adapt_query("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT (key) DO NOTHING"), (k, v))
        except Exception:
            pass
    conn.commit()
    conn.close()


# ── Posts ──────────────────────────────────────────────

def insert_post(title, summary, body, image_url, category, source_name, source_url, url_hash, ai_written=0):
    """Insert a new post. Returns True if inserted, False if duplicate."""
    conn = _get_conn()
    try:
        now = datetime.now(BDT).strftime("%Y-%m-%d %H:%M:%S")
        _execute(conn, _adapt_query(
            """INSERT INTO posts (title, summary, body, image_url, category,
               source_name, source_url, url_hash, ai_written, created_at, published_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)"""
        ), (title, summary, body, image_url, category, source_name, source_url, url_hash, ai_written, now, now))
        conn.commit()
        count = _fetchone(conn, "SELECT COUNT(*) as cnt FROM posts")["cnt"]
        _execute(conn, _adapt_query("UPDATE settings SET value=? WHERE key='post_count'"), (str(count),))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def url_hash_exists(url_hash):
    """Check if a URL hash already exists."""
    conn = _get_conn()
    row = _fetchone(conn, _adapt_query("SELECT 1 FROM posts WHERE url_hash=?"), (url_hash,))
    conn.close()
    return row is not None


def get_posts(category=None, limit=30, offset=0, with_image_first=False):
    """Get posts, optionally filtered by category."""
    conn = _get_conn()
    query = "SELECT * FROM posts"
    params = []
    if category:
        query += " WHERE category=%s" if USE_POSTGRES else " WHERE category=?"
        params.append(category)
    if with_image_first:
        query += " ORDER BY CASE WHEN image_url='' THEN 1 ELSE 0 END, created_at DESC"
    else:
        query += " ORDER BY created_at DESC"
    if USE_POSTGRES:
        query += " LIMIT %s OFFSET %s"
    else:
        query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = _fetchall(conn, query, params)
    conn.close()
    return rows


def get_post(post_id):
    """Get a single post by ID."""
    conn = _get_conn()
    row = _fetchone(conn, _adapt_query("SELECT * FROM posts WHERE id=?"), (post_id,))
    conn.close()
    return row


def increment_views(post_id):
    """Increment view count."""
    conn = _get_conn()
    _execute(conn, _adapt_query("UPDATE posts SET views = views + 1 WHERE id=?"), (post_id,))
    conn.commit()
    conn.close()


def search_posts(query_text, limit=30):
    """Search posts by title or body."""
    conn = _get_conn()
    pattern = f"%{query_text}%"
    rows = _fetchall(conn, _adapt_query(
        "SELECT * FROM posts WHERE title LIKE ? OR summary LIKE ? OR body LIKE ? ORDER BY created_at DESC LIMIT ?"
    ), (pattern, pattern, pattern, limit))
    conn.close()
    return rows


def count_posts():
    conn = _get_conn()
    row = _fetchone(conn, "SELECT COUNT(*) as cnt FROM posts")
    conn.close()
    return row["cnt"]


def count_posts_by_category():
    conn = _get_conn()
    rows = _fetchall(conn, "SELECT category, COUNT(*) as cnt FROM posts GROUP BY category ORDER BY cnt DESC")
    conn.close()
    return rows


def get_total_views():
    conn = _get_conn()
    row = _fetchone(conn, "SELECT COALESCE(SUM(views), 0) as total FROM posts")
    conn.close()
    return row["total"]


def delete_post(post_id):
    conn = _get_conn()
    _execute(conn, _adapt_query("DELETE FROM posts WHERE id=?"), (post_id,))
    conn.commit()
    conn.close()


# ── Settings ────────────────────────────────────────────

def get_setting(key, default=""):
    conn = _get_conn()
    row = _fetchone(conn, _adapt_query("SELECT value FROM settings WHERE key=?"), (key,))
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = _get_conn()
    if USE_POSTGRES:
        _execute(conn, "INSERT INTO settings(key, value) VALUES(%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s", (key, value, value))
    else:
        _execute(conn, "INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, value))
    conn.commit()
    conn.close()


# ── Agent Log ───────────────────────────────────────────

def log_agent(message):
    conn = _get_conn()
    _execute(conn, _adapt_query("INSERT INTO agent_log(message) VALUES(?)"), (message,))
    conn.commit()
    conn.close()


def get_agent_logs(limit=50):
    conn = _get_conn()
    rows = _fetchall(conn, "SELECT * FROM agent_log ORDER BY id DESC LIMIT %s" if USE_POSTGRES else "SELECT * FROM agent_log ORDER BY id DESC LIMIT ?", (limit,))
    conn.close()
    return rows


def delete_old_posts(days=30):
    """Delete posts older than N days."""
    conn = _get_conn()
    cutoff = (datetime.now(BDT) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    if USE_POSTGRES:
        _execute(conn, "DELETE FROM posts WHERE created_at < %s", (cutoff,))
    else:
        _execute(conn, "DELETE FROM posts WHERE created_at < ?", (cutoff,))
    conn.commit()
    conn.close()