"""The Dash application: shell, routing, theme, and page registration.

The Dash app is mounted on the Flask server at ``/app/``. A ``before_request``
guard on that prefix means an unauthenticated visitor is redirected to the login
page before any of the dashboard bundle is served.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import dash
from dash import Input, Output, State, dcc, html
from flask import Flask, redirect, request
from flask_login import current_user

from config import settings
from jobscout.pages import admin, assistant, contact, deck, directory, overview, tracking

ROUTE_PREFIX = "/app/"

NAV = [
    ("Overview", ROUTE_PREFIX),
    ("Directory", ROUTE_PREFIX + "directory"),
    ("Tracking", ROUTE_PREFIX + "tracking"),
    ("Contact", ROUTE_PREFIX + "contact"),
    ("Assistant", ROUTE_PREFIX + "assistant"),
    ("Deck", ROUTE_PREFIX + "deck"),
]

PAGES = {
    ROUTE_PREFIX: overview,
    ROUTE_PREFIX + "directory": directory,
    ROUTE_PREFIX + "tracking": tracking,
    ROUTE_PREFIX + "contact": contact,
    ROUTE_PREFIX + "assistant": assistant,
    ROUTE_PREFIX + "deck": deck,
    ROUTE_PREFIX + "admin": admin,
}

INDEX_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="light">
<head>
{%metas%}
<title>{%title%}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,500&family=Source+Sans+3:wght@400;500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,500;1,8..60,500&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<script>
  // Paint the stored theme before first paint, so there is no light flash.
  try {
    var t = localStorage.getItem("jobscout-theme");
    document.documentElement.setAttribute("data-theme", t === "dark" ? "dark" : "light");
  } catch (e) {}
</script>
{%favicon%}
{%css%}
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
</footer>
</body>
</html>
"""


_SUN = html.Span(
    className="ico-sun",
    children=html.Span("☀", style={"fontSize": "14px", "lineHeight": "1"}),
)
_MOON = html.Span(
    className="ico-moon",
    children=html.Span("☾", style={"fontSize": "14px", "lineHeight": "1"}),
)


def _topbar(active: str, user: Any) -> html.Div:
    nav_links = [
        html.A(
            label,
            href=href,
            className="active" if href == active else "",
            **{"data-route": href},
        )
        for label, href in NAV
    ]
    if getattr(user, "is_admin", False):
        href = ROUTE_PREFIX + "admin"
        nav_links.append(
            html.A("Admin", href=href, className="active" if href == active else "")
        )

    return html.Div(
        [
            html.A(
                [
                    html.Span("JS", className="seal"),
                    html.Span(
                        [
                            html.Span(settings.APP_NAME, className="mark"),
                            html.Span(settings.TAGLINE, className="tag"),
                        ],
                        className="brand-text",
                    ),
                ],
                href=ROUTE_PREFIX,
                className="brand",
            ),
            html.Nav(nav_links),
            html.Div(
                [
                    html.Div(
                        [
                            html.Strong(getattr(user, "name", "")),
                            html.Span("Administrator" if getattr(user, "is_admin", False) else "Scout"),
                        ],
                        className="whoami",
                    ),
                    html.Button(
                        [_SUN, _MOON],
                        id="theme-toggle",
                        className="theme-btn",
                        title="Switch theme",
                        **{"aria-label": "Switch theme"},
                        n_clicks=0,
                    ),
                    html.A("Sign out", href="/logout", className="btn small"),
                ],
                className="topbar-right",
            ),
        ],
        className="topbar",
    )


def create_dash(server: Flask) -> dash.Dash:
    app = dash.Dash(
        __name__,
        server=server,
        url_base_pathname=ROUTE_PREFIX,
        title=settings.APP_NAME,
        update_title=None,
        index_string=INDEX_TEMPLATE,
        suppress_callback_exceptions=True,
        assets_folder="static",
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"},
            {
                "name": "description",
                "content": f"{settings.APP_NAME} — {settings.TAGLINE}",
            },
        ],
    )

    # ---- auth gate for every Dash route -------------------------------------
    @server.before_request
    def _guard_dashboard():
        path = request.path
        if not path.startswith(ROUTE_PREFIX):
            return None
        # Static assets and the callback endpoint ride the same session cookie.
        if current_user.is_authenticated:
            return None
        if path.startswith(ROUTE_PREFIX + "_dash-"):
            return ("Not signed in", 401)
        return redirect("/login?next=" + path)

    app.layout = html.Div(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="theme-store", storage_type="local"),
            html.Div(id="theme-applied", style={"display": "none"}),
            html.Div(id="topbar-slot"),
            html.Div(id="page-slot", className="page"),
            html.Div(
                [
                    f"{settings.APP_NAME} · compiled from public listings · ",
                    f"folio {date.today():%Y}",
                ],
                className="footer-note",
            ),
        ]
    )

    # ---- shell ---------------------------------------------------------------
    @app.callback(
        Output("topbar-slot", "children"),
        Output("page-slot", "children"),
        Output("page-slot", "className"),
        Input("url", "pathname"),
        Input("theme-store", "data"),
    )
    def _render(pathname: str | None, theme: str | None) -> tuple[Any, Any, str]:
        path = pathname or ROUTE_PREFIX
        if not path.endswith("/") and path.rstrip("/") == ROUTE_PREFIX.rstrip("/"):
            path = ROUTE_PREFIX
        dark = theme == "dark"
        module = PAGES.get(path)

        if module is admin and not getattr(current_user, "is_admin", False):
            body = html.Div(
                [
                    html.Div("Restricted", className="eyebrow"),
                    html.H2("The admin panel is for administrators."),
                    html.P(
                        "Ask an administrator to raise your role if you need it.",
                        style={"marginTop": "10px"},
                    ),
                ],
                className="panel",
            )
            return _topbar(path, current_user), body, "page"

        if module is None:
            body = html.Div(
                [
                    html.Div("404", className="eyebrow"),
                    html.H2("No such page in this ledger."),
                    html.Div(
                        html.A("Back to the overview", href=ROUTE_PREFIX, className="btn primary"),
                        style={"marginTop": "16px"},
                    ),
                ],
                className="panel",
            )
            return _topbar(path, current_user), body, "page"

        shell_class = "deck" if module is deck else "page"
        return _topbar(path, current_user), module.layout(dark=dark), shell_class

    # ---- theme toggle --------------------------------------------------------
    # Two one-way callbacks rather than one that both reads and writes the
    # store, which Dash would reject as circular.
    app.clientside_callback(
        """
        function (clicks, current) {
            if (!clicks) { return window.dash_clientside.no_update; }
            return (current === "dark") ? "light" : "dark";
        }
        """,
        Output("theme-store", "data"),
        Input("theme-toggle", "n_clicks"),
        State("theme-store", "data"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        """
        function (theme) {
            var value = (theme === "dark") ? "dark" : "light";
            document.documentElement.setAttribute("data-theme", value);
            try { localStorage.setItem("jobscout-theme", value); } catch (e) {}
            return value;
        }
        """,
        Output("theme-applied", "data-theme"),
        Input("theme-store", "data"),
    )

    for module in (overview, directory, tracking, contact, assistant, deck, admin):
        module.register(app)

    return app
