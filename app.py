"""JobScout — entry point.

    python app.py

One Flask process serves three things:

    /            -> redirect to the login page, or to the dashboard
    /login,/signup,/logout
                 -> server-rendered auth (Jinja), sets the session cookie
    /app/...     -> the Dash dashboard, behind a login guard

Configuration is environment-driven; see ``.env.example``.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from flask import Flask

from config import settings
from jobscout import auth, db
from jobscout.dashboard import create_dash

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jobscout")


def create_app() -> Flask:
    server = Flask(
        __name__,
        template_folder="jobscout/templates",
        static_folder="jobscout/static",
        static_url_path="/static",
    )
    server.config.update(
        SECRET_KEY=settings.SECRET_KEY,
        SESSION_COOKIE_SECURE=settings.SESSION_COOKIE_SECURE,
        SESSION_COOKIE_HTTPONLY=settings.SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE=settings.SESSION_COOKIE_SAMESITE,
        PERMANENT_SESSION_LIFETIME=timedelta(days=settings.PERMANENT_SESSION_LIFETIME_DAYS),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        TEMPLATES_AUTO_RELOAD=settings.DEBUG,
        JSON_SORT_KEYS=False,
    )

    db.init_db()

    auth.login_manager.init_app(server)
    server.register_blueprint(auth.bp)

    create_dash(server)

    @server.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return response

    @server.route("/healthz")
    def _health():
        return {"status": "ok", "app": settings.APP_NAME}

    return server


app = create_app()
server = app  # for `gunicorn app:server`


def main() -> None:
    if not os.getenv("JOBSCOUT_SECRET_KEY"):
        log.warning(
            "JOBSCOUT_SECRET_KEY is not set — a random key was generated, so every "
            "restart signs everyone out. Set it before you rely on this."
        )
    if settings.MAIL_DRY_RUN:
        log.info("Mail dry run is ON: messages are logged but never delivered.")
    if not settings.ai_enabled():
        log.info("GEMINI_API_KEY is not set: the AI features are disabled.")

    log.info("%s on http://%s:%s", settings.APP_NAME, settings.HOST, settings.PORT)
    app.run(host=settings.HOST, port=settings.PORT, debug=settings.DEBUG)


if __name__ == "__main__":
    main()
