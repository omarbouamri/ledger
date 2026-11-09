"""SQLite persistence layer.

Design notes
------------
* One schema statement block, applied idempotently at boot (``init_db``).
* WAL journaling + a tuned pragma set, so the dashboard can read while a send
  worker writes.
* Every query goes through :func:`connect` (a context manager) so connections
  are always closed and writes are always committed or rolled back.
* The employer table carries a *precomputed* ``score`` column with an index, so
  sorting 283 (or 283k) rows never touches Python.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Sequence

from config import settings
from jobscout.scoring import score_rows

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL DEFAULT '',
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'scout' CHECK (role IN ('scout','admin')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS employers (
    id           TEXT PRIMARY KEY,
    name         TEXT    NOT NULL,
    sector       TEXT    NOT NULL DEFAULT 'Autre',
    address      TEXT    NOT NULL DEFAULT '',
    phone        TEXT    NOT NULL DEFAULT '',
    website      TEXT    NOT NULL DEFAULT '',
    maps_url     TEXT    NOT NULL DEFAULT '',
    lat          REAL,
    lon          REAL,
    rating       REAL,
    reviews      INTEGER,
    has_website  INTEGER NOT NULL DEFAULT 0,
    score        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_employers_score  ON employers(score DESC);
CREATE INDEX IF NOT EXISTS ix_employers_sector ON employers(sector);
CREATE INDEX IF NOT EXISTS ix_employers_site   ON employers(has_website);

-- Per-user tracking state for an employer.
CREATE TABLE IF NOT EXISTS tracking (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    employer_id   TEXT    NOT NULL REFERENCES employers(id) ON DELETE CASCADE,
    stage         TEXT    NOT NULL DEFAULT 'scouted',
    starred       INTEGER NOT NULL DEFAULT 0,
    notes         TEXT    NOT NULL DEFAULT '',
    contact_name  TEXT    NOT NULL DEFAULT '',
    contact_email TEXT    NOT NULL DEFAULT '',
    updated_at    TEXT    NOT NULL,
    PRIMARY KEY (user_id, employer_id)
);
CREATE INDEX IF NOT EXISTS ix_tracking_user  ON tracking(user_id, stage);
CREATE INDEX IF NOT EXISTS ix_tracking_star  ON tracking(user_id, starred);

CREATE TABLE IF NOT EXISTS templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL = shared
    name       TEXT    NOT NULL,
    subject    TEXT    NOT NULL,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    employer_id TEXT    REFERENCES employers(id) ON DELETE SET NULL,
    to_addr     TEXT    NOT NULL,
    subject     TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'queued',
    error       TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    sent_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_emails_user   ON emails(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_emails_status ON emails(status);

CREATE TABLE IF NOT EXISTS ai_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind          TEXT    NOT NULL,
    model         TEXT    NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    ok            INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_runs_created ON ai_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT    NOT NULL,
    detail     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit(created_at DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

STAGES: tuple[str, ...] = (
    "scouted",
    "researched",
    "contacted",
    "replied",
    "interview",
    "offer",
    "closed",
)
STAGE_LABELS = {
    "scouted": "Scouted",
    "researched": "Researched",
    "contacted": "Contacted",
    "replied": "Replied",
    "interview": "Interview",
    "offer": "Offer",
    "closed": "Closed",
}

_init_lock = threading.Lock()
_initialised = False


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Yield a configured connection; commit on success, roll back on error."""
    conn = sqlite3.connect(settings.DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("BEGIN")
        yield conn
        # executescript() commits on its own, so the transaction may already be
        # closed by the time we get here.
        if conn.in_transaction:
            conn.execute("COMMIT")
    except Exception:
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def query(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def query_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid or cur.rowcount


def executemany(sql: str, rows: Iterable[Sequence[Any]]) -> None:
    with connect() as conn:
        conn.executemany(sql, rows)


# --------------------------------------------------------------------------- #
# Boot
# --------------------------------------------------------------------------- #
def init_db(seed: bool = True) -> None:
    """Create the schema (idempotent) and import seed employers once."""
    global _initialised
    with _init_lock:
        settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with connect() as conn:
            conn.executescript(_SCHEMA)
        if seed:
            seed_employers()
            seed_templates()
        _initialised = True


def ensure_ready() -> None:
    if not _initialised:
        init_db()


def seed_employers(force: bool = False) -> int:
    """Load ``data/employers.json`` into the employers table.

    Scores are computed in one vectorised pass and stored, so the directory can
    sort and page in SQL. Re-running is safe: rows are upserted by id.

    Note on ids: two distinct businesses share a Google place id in the original
    export, so the seed file suffixes the second occurrence ("...-2"). Without
    that, the upsert below would silently collapse them into one row.
    """
    if not settings.SEED_FILE.exists():
        return 0
    existing = query_one("SELECT COUNT(*) AS n FROM employers")
    if existing and existing["n"] and not force:
        return 0

    raw = json.loads(settings.SEED_FILE.read_text(encoding="utf-8"))
    scores = score_rows(raw)
    now = utcnow()
    rows = [
        (
            r["id"],
            r["name"],
            r.get("sector") or "Autre",
            r.get("address") or "",
            r.get("phone") or "",
            r.get("website") or "",
            r.get("maps_url") or "",
            r.get("lat"),
            r.get("lon"),
            r.get("rating"),
            r.get("reviews"),
            1 if r.get("has_website") else 0,
            int(scores[i]),
            now,
        )
        for i, r in enumerate(raw)
    ]
    executemany(
        """
        INSERT INTO employers
            (id,name,sector,address,phone,website,maps_url,lat,lon,
             rating,reviews,has_website,score,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, sector=excluded.sector, address=excluded.address,
            phone=excluded.phone, website=excluded.website, maps_url=excluded.maps_url,
            lat=excluded.lat, lon=excluded.lon, rating=excluded.rating,
            reviews=excluded.reviews, has_website=excluded.has_website,
            score=excluded.score
        """,
        rows,
    )
    return len(rows)


def rescore_all() -> int:
    """Recompute every stored score (after the admin changes the weights)."""
    rows = [dict(r) for r in query("SELECT id, rating, reviews, has_website FROM employers")]
    if not rows:
        return 0
    scores = score_rows(rows)
    executemany(
        "UPDATE employers SET score=? WHERE id=?",
        [(int(scores[i]), r["id"]) for i, r in enumerate(rows)],
    )
    return len(rows)


_DEFAULT_TEMPLATES = [
    (
        "Cold intro — no website on file",
        "Quick question about {name}'s web presence",
        "Hello {contact_name},\n\n"
        "I came across {name} while mapping {sector} businesses in Marrakech, and "
        "noticed there is no website on file — even though you are carrying a "
        "{rating}/5 rating across {reviews} reviews. That is a strong reputation "
        "with nowhere to send people.\n\n"
        "I build small, fast sites and booking flows for businesses in exactly "
        "that position. Would a 15-minute call this week be useful?\n\n"
        "Best,\n{sender_name}",
    ),
    (
        "Cold intro — hiring enquiry",
        "Open roles at {name}?",
        "Hello {contact_name},\n\n"
        "I am a developer based in Marrakech and have been following {name} in the "
        "{sector} space. I would like to ask whether you have any openings, or "
        "upcoming project work, where an extra pair of hands would help.\n\n"
        "I have attached nothing for now — happy to send a short portfolio if it is "
        "relevant.\n\n"
        "Thank you for your time,\n{sender_name}",
    ),
    (
        "Follow-up — no reply",
        "Following up: {name}",
        "Hello {contact_name},\n\n"
        "Just floating my earlier note back to the top of your inbox in case it got "
        "buried. No pressure either way — if the timing is wrong, a one-line reply "
        "is enough and I will stop here.\n\n"
        "Best,\n{sender_name}",
    ),
]


def seed_templates() -> int:
    row = query_one("SELECT COUNT(*) AS n FROM templates WHERE user_id IS NULL")
    if row and row["n"]:
        return 0
    now = utcnow()
    executemany(
        "INSERT INTO templates (user_id,name,subject,body,created_at) VALUES (NULL,?,?,?,?)",
        [(n, s, b, now) for n, s, b in _DEFAULT_TEMPLATES],
    )
    return len(_DEFAULT_TEMPLATES)


def log_audit(user_id: int | None, action: str, detail: str = "") -> None:
    execute(
        "INSERT INTO audit (user_id,action,detail,created_at) VALUES (?,?,?,?)",
        (user_id, action, detail[:500], utcnow()),
    )
