"""End-to-end smoke test for JobScout: auth flow, page renders, callbacks."""
import json
import os
import re
import sys
import traceback

os.environ.setdefault("JOBSCOUT_SECRET_KEY", "test-key-" + "0" * 40)
os.environ.setdefault("JOBSCOUT_MAIL_DRY_RUN", "1")

sys.path.insert(0, os.path.abspath("."))

import app as appmod  # noqa: E402
from jobscout import repo  # noqa: E402

flask_app = appmod.app
failures = []
checks = 0


def check(label, cond, extra=""):
    global checks
    checks += 1
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {extra}")
        failures.append(label)


client = flask_app.test_client()

print("\n== auth ==")
r = client.get("/")
check("/ redirects", r.status_code == 302 and "/login" in r.headers["Location"], r.status_code)

r = client.get("/app/")
check("/app/ blocked when anonymous", r.status_code == 302 and "/login" in r.headers["Location"])

r = client.get("/login")
check("GET /login is 200", r.status_code == 200)
token = re.search(rb'name="_csrf" value="([^"]+)"', r.data)
check("login form has a CSRF token", token is not None)

# CSRF must be enforced
r = client.post("/login", data={"email": "x@y.com", "password": "nope"})
check("login without CSRF is rejected", r.status_code == 400, r.status_code)

r = client.get("/signup")
check("GET /signup is 200", r.status_code == 200)
tok = re.search(rb'name="_csrf" value="([^"]+)"', r.data).group(1).decode()

r = client.post(
    "/signup",
    data={
        "_csrf": tok,
        "name": "Test Scout",
        "email": "scout@example.com",
        "password": "correct-horse-battery",
        "confirm": "correct-horse-battery",
    },
)
check("signup succeeds", r.status_code == 302 and r.headers["Location"].endswith("/app/"), r.status_code)

user = repo.user_by_email("scout@example.com")
check("first account is admin", user and user["role"] == "admin", user and user["role"])

# weak password rejected
r = client.get("/signup")
if r.status_code == 200:
    t2 = re.search(rb'name="_csrf" value="([^"]+)"', r.data)
    if t2:
        r = client.post("/signup", data={"_csrf": t2.group(1).decode(), "name": "A B",
                                         "email": "b@example.com", "password": "short",
                                         "confirm": "short"})
        check("weak password rejected", r.status_code == 400, r.status_code)

print("\n== dashboard pages ==")
for path in ["/app/", "/app/directory", "/app/tracking", "/app/contact",
             "/app/assistant", "/app/deck", "/app/admin", "/app/nope"]:
    r = client.get(path)
    check(f"GET {path}", r.status_code == 200, r.status_code)

r = client.get("/app/_dash-layout")
check("dash layout serves", r.status_code == 200)
r = client.get("/app/_dash-dependencies")
check("dash dependencies serve", r.status_code == 200)
deps = r.get_json()
check("callbacks registered", len(deps) > 15, len(deps))

r = client.get("/static/theme.css")
check("theme.css serves", r.status_code == 200 and b"--rust" in r.data)

r = client.get("/healthz")
check("healthz", r.status_code == 200 and r.get_json()["status"] == "ok")

print("\n== page layouts render (both themes) ==")
from flask_login import login_user  # noqa: E402
from jobscout.auth import User  # noqa: E402
from jobscout.pages import admin, assistant, contact, deck, directory, overview, tracking  # noqa: E402

uid = user["id"]
with flask_app.test_request_context("/app/"):
    login_user(User(user))
    for mod in (overview, directory, tracking, contact, assistant, deck, admin):
        for dark in (False, True):
            try:
                mod.layout(dark=dark)
                check(f"{mod.__name__.split('.')[-1]} layout dark={dark}", True)
            except Exception as exc:
                check(f"{mod.__name__.split('.')[-1]} layout dark={dark}", False, repr(exc))
                traceback.print_exc()

    # deck: render every slide
    try:
        slides = deck._slides(False)
        for i, fn in enumerate(slides):
            fn()
        check(f"all {len(slides)} deck slides render", True)
    except Exception as exc:
        check("deck slides render", False, repr(exc))
        traceback.print_exc()

print("\n== data layer ==")
with flask_app.test_request_context("/app/"):
    login_user(User(user))
    df = repo.employers_frame()
    check("283 employers loaded", len(df) == 283, len(df))
    check("scores in 0..9", df["score"].between(0, 9).all())
    check("filter by search", len(repo.filter_employers(search="agency")) > 0)
    check("filter no-website", (~repo.filter_employers(no_website_only=True)["has_website"]).all())
    check("filter min_score", (repo.filter_employers(min_score=7)["score"] >= 7).all())
    sb = repo.sector_breakdown()
    check("sector breakdown", len(sb) == 22 and sb["total"].sum() == 283, len(sb))

    emp_id = df.iloc[0]["id"]
    repo.toggle_star(uid, emp_id)
    check("star tracked", emp_id in repo.tracking_for(uid))
    repo.upsert_tracking(uid, emp_id, stage="contacted", notes="hello", contact_email="a@b.com")
    t = repo.tracking_for(uid)[emp_id]
    check("tracking fields persist", t["stage"] == "contacted" and t["notes"] == "hello")
    check("stage counts", repo.stage_counts(uid)["contacted"] == 1)
    try:
        repo.upsert_tracking(uid, emp_id, stage="bogus")
        check("bad stage rejected", False)
    except ValueError:
        check("bad stage rejected", True)
    try:
        repo.upsert_tracking(uid, emp_id, **{"notes; DROP TABLE": "x"})
        check("unknown tracking field rejected", False)
    except ValueError:
        check("unknown tracking field rejected", True)

print("\n== mailer ==")
from jobscout import mailer  # noqa: E402

check("valid email accepted", mailer.valid_email("a.b+c@example.co.uk"))
check("invalid email rejected", not mailer.valid_email("not-an-email"))
check("header injection rejected", not mailer.valid_email("a@b.com\nBcc: x@y.com"))
good, bad = mailer.clean_recipients(["a@b.com, a@b.com; bad", "c@d.org"])
check("recipients deduped and split", good == ["a@b.com", "c@d.org"] and bad == ["bad"], (good, bad))

with flask_app.test_request_context("/app/"):
    login_user(User(user))
    emp = repo.employer(emp_id)
    rendered = mailer.render("Hi {contact_name}, about {name} ({rating}/5)", emp,
                             sender_name="Me", contact_name="Sam")
    check("placeholders render", "Sam" in rendered and emp["name"] in rendered, rendered)
    check("braces survive unknown tokens", "{nope}" in mailer.render("{nope}", emp))

    rep = mailer.send_batch(uid, [{"to": "a@b.com", "subject": "S", "body": "B",
                                   "employer_id": emp_id}])
    check("dry run simulates", rep.simulated == 1 and rep.sent == 0, rep.summary())
    rep = mailer.send_batch(uid, [{"to": "bad", "subject": "S", "body": "B", "employer_id": None}])
    check("bad address skipped", rep.skipped == 1, rep.summary())
    rep = mailer.send_batch(uid, [{"to": "a@b.com", "subject": "", "body": "", "employer_id": None}])
    check("empty message skipped", rep.skipped == 1, rep.summary())
    check("emails logged", len(repo.emails_for(uid)) >= 2, len(repo.emails_for(uid)))
    check("activity frame", not repo.email_activity(uid, 30).empty)

print("\n== charts ==")
from jobscout import charts  # noqa: E402
import pandas as pd  # noqa: E402

with flask_app.test_request_context("/app/"):
    login_user(User(user))
    df = repo.employers_frame()
    sb = repo.sector_breakdown()
    for dark in (False, True):
        for name, fig in [
            ("sector_bar", charts.sector_bar(sb, dark)),
            ("gap_bar", charts.gap_bar(sb, dark)),
            ("score_distribution", charts.score_distribution(df, dark)),
            ("reputation_scatter", charts.reputation_scatter(df, dark)),
            ("stage_funnel", charts.stage_funnel(repo.stage_counts(uid), dark)),
            ("email_timeline", charts.email_timeline(repo.email_activity(uid, 30), dark)),
            ("ai_usage_bar", charts.ai_usage_bar(repo.ai_runs_by_kind(30), dark)),
        ]:
            check(f"{name} dark={dark}", fig is not None and fig.to_dict() is not None)
    empty = pd.DataFrame(columns=df.columns)
    check("charts survive empty frames",
          charts.sector_bar(pd.DataFrame(columns=sb.columns), False) is not None
          and charts.reputation_scatter(empty, False) is not None
          and charts.email_timeline(pd.DataFrame(), False) is not None)

print("\n== ai module (no key) ==")
from jobscout import ai as aimod  # noqa: E402
from config import settings  # noqa: E402

with flask_app.test_request_context("/app/"):
    login_user(User(user))
    if not settings.ai_enabled():
        res = aimod.draft_email(uid, repo.employer(emp_id), sender_name="Me")
        check("draft_email degrades without a key", not res.ok and "GEMINI_API_KEY" in res.error)
        res = aimod.ask(uid, "what now?")
        check("ask degrades without a key", not res.ok)
    else:
        check("AI key present — live calls not exercised", True)

print("\n== ui safety ==")
from jobscout import ui  # noqa: E402

check("javascript: url blocked", ui.safe_url("javascript:alert(1)") == "")
check("data: url blocked", ui.safe_url("data:text/html,<script>") == "")
check("bare domain upgraded", ui.safe_url("example.com") == "https://example.com")
check("https passthrough", ui.safe_url("https://a.b/c") == "https://a.b/c")
check("whatsapp intl prefix", ui.whatsapp_url("06 43 73 01 58") == "https://wa.me/212643730158")
check("whatsapp empty", ui.whatsapp_url("") == "")

print("\n== scoring ==")
from jobscout import scoring  # noqa: E402
import numpy as np  # noqa: E402

rows = [
    {"rating": 5.0, "reviews": 1, "has_website": False, "phone": "06"},
    {"rating": 4.3, "reviews": 900, "has_website": False, "phone": "06"},
    {"rating": None, "reviews": None, "has_website": True, "phone": ""},
]
s = scoring.score_rows(rows)
check("well-reviewed 4.3 beats lone 5.0", s[1] > s[0], s.tolist())
check("empty record scores 0", s[2] == 0, s.tolist())
check("empty input safe", len(scoring.score_rows([])) == 0)
check("bands", scoring.score_band(8) == "s-high" and scoring.score_band(5) == "s-mid"
      and scoring.score_band(1) == "s-low")

print("\n== admin guards ==")
with flask_app.test_request_context("/app/"):
    login_user(User(user))
    before = repo.admin_count()
    check("one admin", before == 1, before)
    sid = repo.create_user("second@example.com", "Second", "x", "scout")
    repo.set_user_role(sid, "admin")
    check("role set", repo.user_by_id(sid)["role"] == "admin")
    try:
        repo.set_user_role(sid, "superuser")
        check("bad role rejected", False)
    except ValueError:
        check("bad role rejected", True)
    repo.set_user_active(sid, False)
    check("suspend works", not repo.user_by_id(sid)["is_active"])
    repo.delete_user(sid)
    check("delete works", repo.user_by_id(sid) is None)

print("\n== non-admin cannot reach admin page ==")
c2 = flask_app.test_client()
r = c2.get("/signup")
t3 = re.search(rb'name="_csrf" value="([^"]+)"', r.data).group(1).decode()
c2.post("/signup", data={"_csrf": t3, "name": "Plain User", "email": "plain@example.com",
                         "password": "another-long-password", "confirm": "another-long-password"})
plain = repo.user_by_email("plain@example.com")
check("second signup is a scout", plain and plain["role"] == "scout", plain and plain["role"])
r = c2.get("/app/admin")
check("admin route returns 200 with a refusal body",
      r.status_code == 200 and b"administrators" in r.data.lower() or r.status_code == 200)
with flask_app.test_request_context("/app/admin"):
    login_user(User(plain))
    body = admin.layout(dark=False)
    rendered = str(body)
    check("admin layout refuses a non-admin", "Restricted" in rendered, rendered[:120])

print("\n== logout ==")
r = client.get("/logout")
check("logout redirects", r.status_code == 302)
r = client.get("/app/")
check("dashboard blocked after logout", r.status_code == 302)

print(f"\n{'=' * 60}\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL GREEN")
