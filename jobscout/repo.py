"""Query layer: everything the pages are allowed to ask the database.

Pages never write SQL. That keeps the parameter binding (and therefore the
injection safety) in one reviewable file, and lets the expensive read paths be
cached in one place.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd

from jobscout import db
from jobscout.db import STAGES, utcnow

# --------------------------------------------------------------------------- #
# Employer frame cache
# --------------------------------------------------------------------------- #
# The employer table is read-mostly: 283 rows that change only when an admin
# re-imports or re-scores. Charts and filters therefore run against one cached
# DataFrame instead of re-querying and re-boxing rows on every callback.
_cache_lock = threading.Lock()
_frame: pd.DataFrame | None = None
_frame_stamp: float = 0.0
_FRAME_TTL = 300.0  # seconds


def invalidate_cache() -> None:
    global _frame
    with _cache_lock:
        _frame = None


def employers_frame(force: bool = False) -> pd.DataFrame:
    """All employers as a DataFrame. Cached; callers must not mutate it."""
    global _frame, _frame_stamp
    with _cache_lock:
        fresh = _frame is not None and (time.monotonic() - _frame_stamp) < _FRAME_TTL
        if fresh and not force:
            return _frame

        rows = db.query(
            """
            SELECT id, name, sector, address, phone, website, maps_url,
                   lat, lon, rating, reviews, has_website, score
            FROM employers
            ORDER BY score DESC, name ASC
            """
        )
        df = pd.DataFrame([dict(r) for r in rows])
        if df.empty:
            df = pd.DataFrame(
                columns=[
                    "id", "name", "sector", "address", "phone", "website",
                    "maps_url", "lat", "lon", "rating", "reviews",
                    "has_website", "score",
                ]
            )
        else:
            df["has_website"] = df["has_website"].astype(bool)
            df["reviews"] = df["reviews"].fillna(0).astype(int)
            df["score"] = df["score"].astype(int)
            df["search_blob"] = (
                df["name"].fillna("") + " " + df["sector"].fillna("") + " " + df["address"].fillna("")
            ).str.casefold()
        _frame = df
        _frame_stamp = time.monotonic()
        return df


def sectors() -> list[str]:
    df = employers_frame()
    if df.empty:
        return []
    return sorted(df["sector"].dropna().unique().tolist())


def employer(employer_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM employers WHERE id = ?", (employer_id,))
    return dict(row) if row else None


def filter_employers(
    *,
    search: str = "",
    sector: str = "",
    no_website_only: bool = False,
    min_score: int = 0,
    sort_by: str = "score",
    ascending: bool = False,
    limit: int | None = None,
) -> pd.DataFrame:
    """Vectorised directory filter. Returns a copy, safe to mutate."""
    df = employers_frame()
    if df.empty:
        return df.copy()

    mask = pd.Series(True, index=df.index)
    term = (search or "").strip().casefold()
    if term:
        mask &= df["search_blob"].str.contains(term, regex=False, na=False)
    if sector:
        mask &= df["sector"].eq(sector)
    if no_website_only:
        mask &= ~df["has_website"]
    if min_score > 0:
        mask &= df["score"].ge(min_score)

    out = df.loc[mask]
    if sort_by in out.columns:
        out = out.sort_values(
            by=[sort_by, "name"],
            ascending=[ascending, True],
            na_position="last",
            kind="mergesort",
        )
    if limit:
        out = out.head(limit)
    return out.copy()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def user_by_email(email: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    return dict(row) if row else None


def user_by_id(user_id: int) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    return dict(row) if row else None


def user_count() -> int:
    row = db.query_one("SELECT COUNT(*) AS n FROM users")
    return int(row["n"]) if row else 0


def create_user(email: str, name: str, password_hash: str, role: str = "scout") -> int:
    return db.execute(
        """
        INSERT INTO users (email,name,password_hash,role,is_active,created_at)
        VALUES (?,?,?,?,1,?)
        """,
        (email.strip().lower(), name.strip(), password_hash, role, utcnow()),
    )


def touch_login(user_id: int) -> None:
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (utcnow(), user_id))


def all_users() -> list[dict[str, Any]]:
    rows = db.query(
        """
        SELECT u.id, u.email, u.name, u.role, u.is_active, u.created_at, u.last_login_at,
               (SELECT COUNT(*) FROM tracking t WHERE t.user_id = u.id) AS tracked,
               (SELECT COUNT(*) FROM emails e WHERE e.user_id = u.id
                  AND e.status IN ('sent','simulated'))                AS emails_sent
        FROM users u
        ORDER BY u.created_at ASC
        """
    )
    return [dict(r) for r in rows]


def set_user_role(user_id: int, role: str) -> None:
    if role not in {"scout", "admin"}:
        raise ValueError("unknown role")
    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))


def set_user_active(user_id: int, active: bool) -> None:
    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))


def set_user_password(user_id: int, password_hash: str) -> None:
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


def delete_user(user_id: int) -> None:
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))


def admin_count() -> int:
    row = db.query_one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1")
    return int(row["n"]) if row else 0


# --------------------------------------------------------------------------- #
# Tracking board
# --------------------------------------------------------------------------- #
def tracking_for(user_id: int) -> dict[str, dict[str, Any]]:
    rows = db.query("SELECT * FROM tracking WHERE user_id = ?", (user_id,))
    return {r["employer_id"]: dict(r) for r in rows}


def tracked_frame(user_id: int) -> pd.DataFrame:
    """Employers this user tracks, joined with their tracking state."""
    rows = db.query(
        """
        SELECT e.id, e.name, e.sector, e.phone, e.website, e.maps_url,
               e.rating, e.reviews, e.has_website, e.score,
               t.stage, t.starred, t.notes, t.contact_name, t.contact_email, t.updated_at
        FROM tracking t JOIN employers e ON e.id = t.employer_id
        WHERE t.user_id = ?
        ORDER BY e.score DESC, e.name ASC
        """,
        (user_id,),
    )
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["starred"] = df["starred"].astype(bool)
        df["has_website"] = df["has_website"].astype(bool)
    return df


def upsert_tracking(user_id: int, employer_id: str, **fields: Any) -> None:
    allowed = {"stage", "starred", "notes", "contact_name", "contact_email"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown tracking field(s): {sorted(bad)}")
    if "stage" in fields and fields["stage"] not in STAGES:
        raise ValueError("unknown stage")

    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO tracking (user_id, employer_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, employer_id) DO NOTHING
            """,
            (user_id, employer_id, utcnow()),
        )
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            params: list[Any] = [
                int(v) if k == "starred" else v for k, v in fields.items()
            ]
            params += [utcnow(), user_id, employer_id]
            conn.execute(
                f"UPDATE tracking SET {sets}, updated_at = ? WHERE user_id = ? AND employer_id = ?",
                params,
            )


def toggle_star(user_id: int, employer_id: str) -> bool:
    row = db.query_one(
        "SELECT starred FROM tracking WHERE user_id = ? AND employer_id = ?",
        (user_id, employer_id),
    )
    new = not (row and row["starred"])
    upsert_tracking(user_id, employer_id, starred=new)
    return new


def untrack(user_id: int, employer_id: str) -> None:
    db.execute(
        "DELETE FROM tracking WHERE user_id = ? AND employer_id = ?", (user_id, employer_id)
    )


def stage_counts(user_id: int) -> dict[str, int]:
    rows = db.query(
        "SELECT stage, COUNT(*) AS n FROM tracking WHERE user_id = ? GROUP BY stage",
        (user_id,),
    )
    counts = {s: 0 for s in STAGES}
    for r in rows:
        if r["stage"] in counts:
            counts[r["stage"]] = int(r["n"])
    return counts


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def templates_for(user_id: int) -> list[dict[str, Any]]:
    rows = db.query(
        """
        SELECT * FROM templates
        WHERE user_id IS NULL OR user_id = ?
        ORDER BY user_id IS NULL DESC, name ASC
        """,
        (user_id,),
    )
    return [dict(r) for r in rows]


def template(template_id: int, user_id: int) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT * FROM templates WHERE id = ? AND (user_id IS NULL OR user_id = ?)",
        (template_id, user_id),
    )
    return dict(row) if row else None


def save_template(user_id: int, name: str, subject: str, body: str) -> int:
    return db.execute(
        "INSERT INTO templates (user_id,name,subject,body,created_at) VALUES (?,?,?,?,?)",
        (user_id, name.strip() or "Untitled", subject, body, utcnow()),
    )


def delete_template(template_id: int, user_id: int) -> None:
    # Shared templates (user_id IS NULL) are admin-managed and not deletable here.
    db.execute("DELETE FROM templates WHERE id = ? AND user_id = ?", (template_id, user_id))


# --------------------------------------------------------------------------- #
# Emails
# --------------------------------------------------------------------------- #
def log_email(
    user_id: int,
    employer_id: str | None,
    to_addr: str,
    subject: str,
    body: str,
    status: str,
    error: str = "",
) -> int:
    sent_at = utcnow() if status in {"sent", "simulated"} else None
    return db.execute(
        """
        INSERT INTO emails (user_id,employer_id,to_addr,subject,body,status,error,created_at,sent_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (user_id, employer_id, to_addr, subject, body, status, error[:500], utcnow(), sent_at),
    )


def emails_for(user_id: int, limit: int = 200) -> list[dict[str, Any]]:
    rows = db.query(
        """
        SELECT e.*, p.name AS employer_name
        FROM emails e LEFT JOIN employers p ON p.id = e.employer_id
        WHERE e.user_id = ? ORDER BY e.created_at DESC LIMIT ?
        """,
        (user_id, limit),
    )
    return [dict(r) for r in rows]


def emails_sent_today(user_id: int) -> int:
    row = db.query_one(
        """
        SELECT COUNT(*) AS n FROM emails
        WHERE user_id = ? AND status IN ('sent','simulated')
          AND date(created_at) = date('now')
        """,
        (user_id,),
    )
    return int(row["n"]) if row else 0


def email_activity(user_id: int | None = None, days: int = 30) -> pd.DataFrame:
    sql = """
        SELECT date(created_at) AS day, status, COUNT(*) AS n
        FROM emails
        WHERE created_at >= date('now', ?)
    """
    params: list[Any] = [f"-{int(days)} day"]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    sql += " GROUP BY day, status ORDER BY day"
    return pd.DataFrame([dict(r) for r in db.query(sql, params)])


# --------------------------------------------------------------------------- #
# AI usage + admin stats
# --------------------------------------------------------------------------- #
def log_ai_run(
    user_id: int | None,
    kind: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    ok: bool = True,
) -> None:
    db.execute(
        """
        INSERT INTO ai_runs (user_id,kind,model,input_tokens,output_tokens,ok,created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (user_id, kind, model, input_tokens, output_tokens, 1 if ok else 0, utcnow()),
    )


def ai_usage(days: int = 30) -> dict[str, Any]:
    row = db.query_one(
        """
        SELECT COUNT(*) AS runs,
               COALESCE(SUM(input_tokens),0)  AS input_tokens,
               COALESCE(SUM(output_tokens),0) AS output_tokens,
               COALESCE(SUM(1 - ok),0)        AS failures
        FROM ai_runs WHERE created_at >= date('now', ?)
        """,
        (f"-{int(days)} day",),
    )
    return dict(row) if row else {"runs": 0, "input_tokens": 0, "output_tokens": 0, "failures": 0}


def ai_runs_by_kind(days: int = 30) -> pd.DataFrame:
    rows = db.query(
        """
        SELECT kind, COUNT(*) AS n FROM ai_runs
        WHERE created_at >= date('now', ?) GROUP BY kind ORDER BY n DESC
        """,
        (f"-{int(days)} day",),
    )
    return pd.DataFrame([dict(r) for r in rows])


def platform_stats() -> dict[str, Any]:
    row = db.query_one(
        """
        SELECT
          (SELECT COUNT(*) FROM users)                                      AS users,
          (SELECT COUNT(*) FROM users WHERE is_active=1)                    AS users_active,
          (SELECT COUNT(*) FROM employers)                                  AS employers,
          (SELECT COUNT(*) FROM employers WHERE has_website=0)              AS no_site,
          (SELECT COUNT(*) FROM tracking)                                   AS tracked,
          (SELECT COUNT(*) FROM emails)                                     AS emails,
          (SELECT COUNT(*) FROM emails WHERE status IN ('sent','simulated')) AS emails_sent,
          (SELECT COUNT(*) FROM emails WHERE status='failed')               AS emails_failed,
          (SELECT COUNT(*) FROM templates)                                  AS templates,
          (SELECT COUNT(*) FROM ai_runs)                                    AS ai_runs
        """
    )
    return dict(row) if row else {}


def recent_audit(limit: int = 60) -> list[dict[str, Any]]:
    rows = db.query(
        """
        SELECT a.*, u.email FROM audit a LEFT JOIN users u ON u.id = a.user_id
        ORDER BY a.created_at DESC LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in rows]


def overview_metrics(user_id: int) -> dict[str, Any]:
    df = employers_frame()
    rated = df[df["rating"].notna()] if not df.empty else df
    counts = stage_counts(user_id)
    return {
        "employers": int(len(df)),
        "no_site": int((~df["has_website"]).sum()) if not df.empty else 0,
        "avg_rating": round(float(rated["rating"].mean()), 2) if len(rated) else 0.0,
        "reviews": int(df["reviews"].sum()) if not df.empty else 0,
        "sectors": int(df["sector"].nunique()) if not df.empty else 0,
        "tracked": sum(counts.values()),
        "contacted": counts["contacted"] + counts["replied"] + counts["interview"] + counts["offer"],
        "replied": counts["replied"] + counts["interview"] + counts["offer"],
        "priority": int((df["score"] >= 7).sum()) if not df.empty else 0,
    }


def sector_breakdown() -> pd.DataFrame:
    """Per-sector counts, website gap and mean score — one grouped pass."""
    df = employers_frame()
    if df.empty:
        return pd.DataFrame(columns=["sector", "total", "no_site", "gap_pct", "avg_score"])
    g = df.groupby("sector", dropna=False)
    out = pd.DataFrame(
        {
            "total": g.size(),
            "no_site": g["has_website"].apply(lambda s: int((~s).sum())),
            "avg_score": g["score"].mean().round(2),
            "avg_rating": g["rating"].mean().round(2),
        }
    ).reset_index()
    out["gap_pct"] = (out["no_site"] / out["total"] * 100).round(1)
    return out.sort_values("total", ascending=False, ignore_index=True)
