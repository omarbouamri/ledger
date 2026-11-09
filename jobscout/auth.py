"""Login, signup, logout.

Server-rendered Jinja pages rather than Dash views, for three reasons: the
session cookie must be set by a real HTTP response, an unauthenticated visitor
should never download the dashboard bundle, and a form post is the right tool
for a login.

Protections in place: scrypt password hashing (Werkzeug), a per-session CSRF
token on both forms, a fixed-window rate limit per IP and per email, session
rotation on login, and uniform error text so the form never reveals whether an
address is registered.
"""

from __future__ import annotations

import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from functools import wraps
from typing import Any

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from config import settings
from jobscout import db, repo

bp = Blueprint("auth", __name__)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Sign in to open the field book."
login_manager.session_protection = "strong"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MIN_PASSWORD = 10

# Fixed-window throttle. Process-local by design: this app is a single
# process. Behind multiple workers, move this to Redis or the database.
_ATTEMPT_WINDOW = 900.0  # 15 minutes
_ATTEMPT_LIMIT = 8
_attempts: dict[str, deque[float]] = defaultdict(deque)


class User(UserMixin):
    """Thin flask-login adapter over a users row."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.id = str(row["id"])
        self.uid = int(row["id"])
        self.email = row["email"]
        self.name = row.get("name") or row["email"].split("@")[0]
        self.role = row.get("role", "scout")
        self.active = bool(row.get("is_active", 1))
        self.created_at = row.get("created_at", "")

    @property
    def is_active(self) -> bool:  # consulted by login_user()
        return self.active

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def initials(self) -> str:
        parts = [p for p in re.split(r"[\s._-]+", self.name) if p]
        return "".join(p[0] for p in parts[:2]).upper() or self.email[:2].upper()


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        row = repo.user_by_id(int(user_id))
    except (TypeError, ValueError):
        return None
    if not row or not row.get("is_active"):
        return None
    return User(row)


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #
def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def _check_csrf() -> None:
    sent = request.form.get("_csrf", "")
    expected = session.get("_csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Your form expired. Reload the page and try again.")


# --------------------------------------------------------------------------- #
# Throttle
# --------------------------------------------------------------------------- #
def _throttled(*keys: str) -> bool:
    now = time.monotonic()
    blocked = False
    for key in keys:
        bucket = _attempts[key]
        while bucket and now - bucket[0] > _ATTEMPT_WINDOW:
            bucket.popleft()
        if len(bucket) >= _ATTEMPT_LIMIT:
            blocked = True
    return blocked


def _record_attempt(*keys: str) -> None:
    now = time.monotonic()
    for key in keys:
        _attempts[key].append(now)


def _clear_attempts(*keys: str) -> None:
    for key in keys:
        _attempts.pop(key, None)


def _client_ip() -> str:
    # request.remote_addr is correct for a direct bind. Behind a proxy, run the
    # app under werkzeug's ProxyFix so this stays trustworthy.
    return request.remote_addr or "unknown"


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _safe_next(raw: str | None) -> str:
    """Only ever redirect to a path on this host."""
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/app/"
    return raw


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
@bp.app_context_processor
def _inject() -> dict[str, Any]:
    return {
        "settings": settings,
        "csrf_token": csrf_token,
        "city": settings.CITY.split(",")[0].strip(),
    }


@bp.route("/", methods=["GET"])
def root():
    if current_user.is_authenticated:
        return redirect("/app/")
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_safe_next(request.args.get("next")))

    if request.method == "POST":
        _check_csrf()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        ip_key, mail_key = f"ip:{_client_ip()}", f"mail:{email}"

        if _throttled(ip_key, mail_key):
            flash("Too many attempts. Wait a few minutes and try again.", "err")
            return render_template("login.html", email=email), 429

        row = repo.user_by_email(email)
        ok = bool(row) and check_password_hash(row["password_hash"], password)

        if not ok:
            _record_attempt(ip_key, mail_key)
            # Deliberately identical for a wrong password and an unknown email.
            flash("That email and password do not match.", "err")
            return render_template("login.html", email=email), 401
        if not row["is_active"]:
            flash("This account has been suspended. Contact an administrator.", "err")
            return render_template("login.html", email=email), 403

        _clear_attempts(ip_key, mail_key)
        session.clear()  # rotate: drop any pre-login session fixation
        user = User(row)
        login_user(user, remember=bool(request.form.get("remember")))
        session.permanent = True
        repo.touch_login(user.uid)
        db.log_audit(user.uid, "login", f"from {_client_ip()}")
        return redirect(_safe_next(request.form.get("next") or request.args.get("next")))

    return render_template("login.html", email="")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect("/app/")

    first_account = repo.user_count() == 0
    # The very first account is always allowed — otherwise a fresh install
    # could not be opened at all.
    if not first_account and not settings.ALLOW_SIGNUP:
        return render_template("signup.html", closed=True, form={}), 403

    form = {"name": "", "email": ""}
    if request.method == "POST":
        _check_csrf()
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        invite = (request.form.get("invite") or "").strip()
        form = {"name": name, "email": email}

        ip_key = f"signup:{_client_ip()}"
        if _throttled(ip_key):
            flash("Too many attempts. Wait a few minutes and try again.", "err")
            return render_template("signup.html", form=form, first=first_account), 429

        errors: list[str] = []
        if len(name) < 2:
            errors.append("Enter the name you want on the ledger.")
        if not EMAIL_RE.match(email) or len(email) > 254:
            errors.append("That does not look like an email address.")
        if len(password) < MIN_PASSWORD:
            errors.append(f"Use at least {MIN_PASSWORD} characters in the password.")
        if password != confirm:
            errors.append("The two passwords do not match.")
        if (
            not first_account
            and settings.SIGNUP_INVITE_CODE
            and not hmac.compare_digest(invite, settings.SIGNUP_INVITE_CODE)
        ):
            errors.append("That invite code is not valid.")
        if not errors and repo.user_by_email(email):
            errors.append("An account already exists for that address.")

        if errors:
            _record_attempt(ip_key)
            for err in errors:
                flash(err, "err")
            return render_template("signup.html", form=form, first=first_account), 400

        role = "admin" if first_account else "scout"
        uid = repo.create_user(email, name, generate_password_hash(password), role)
        db.log_audit(uid, "signup", f"role={role}")

        session.clear()
        login_user(User(repo.user_by_id(uid) or {}))
        session.permanent = True
        repo.touch_login(uid)
        if first_account:
            flash("Your account is the first one, so it has administrator rights.", "ok")
        return redirect("/app/")

    return render_template("signup.html", form=form, first=first_account)


@bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    uid = getattr(current_user, "uid", None)
    logout_user()
    session.clear()
    if uid:
        db.log_audit(uid, "logout", "")
    flash("Signed out.", "ok")
    return redirect(url_for("auth.login"))


@bp.app_errorhandler(403)
def _forbidden(_exc):
    return render_template("error.html", code=403, message="That page is for administrators."), 403


@bp.app_errorhandler(404)
def _missing(_exc):
    return render_template("error.html", code=404, message="No such page."), 404
