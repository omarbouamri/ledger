"""Deck: a presentation of what JobScout is, built from live numbers.

The slides are generated from the database at render time, so the figures in the
deck are never stale against the dashboard beside it.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import dash
from dash import ALL, Input, Output, State, callback_context, dcc, html, no_update
from flask_login import current_user

from config import settings
from jobscout import ai, charts, mailer, repo, ui


def _bullets(items: list[tuple[str, str]]) -> Any:
    return html.Ul(
        [html.Li([html.Strong(head + " "), tail]) for head, tail in items]
    )


def _slides(dark: bool) -> list[Callable[[], Any]]:
    uid = int(current_user.uid)
    m = repo.overview_metrics(uid)
    breakdown = repo.sector_breakdown()
    employers = repo.employers_frame()
    stats = repo.platform_stats()
    city = settings.CITY.split(",")[0]

    gap_pct = (m["no_site"] / m["employers"] * 100) if m["employers"] else 0
    worst = breakdown[breakdown["total"] >= 4].nlargest(1, "gap_pct")
    worst_row = worst.to_dict("records")[0] if not worst.empty else None

    def title() -> Any:
        return html.Div(
            [
                html.Div("A field book for finding work", className="kicker"),
                html.H2([f"{settings.APP_NAME}.", html.Br(), html.Em("Who to call, and why.")]),
                html.Div(
                    f"{m['employers']} employers in {city}, scored on reputation and on the "
                    "gaps worth a phone call — then tracked from first contact to an offer.",
                    className="lede",
                ),
                html.Div(
                    ui.stat_strip(
                        [
                            ("Employers", ui.fmt_int(m["employers"]), "", ""),
                            ("No website", ui.fmt_int(m["no_site"]), "rust", f"{gap_pct:.0f}% of the list"),
                            ("Avg rating", f"{m['avg_rating']:.2f}", "", ""),
                            ("Reviews", ui.fmt_compact(m["reviews"]), "moss", ""),
                        ]
                    ),
                    className="slide-body",
                    style={"marginBottom": "0"},
                ),
            ]
        )

    def problem() -> Any:
        return html.Div(
            [
                html.Div("The problem", className="kicker"),
                html.H2(["Good leads die in", html.Br(), html.Em("a spreadsheet.")]),
                html.Div(
                    "A list of businesses is not a plan. Without a score you work "
                    "alphabetically; without a stage you forget who you already called; "
                    "without a log you have no idea what you actually sent.",
                    className="lede",
                ),
                html.Div(
                    _bullets(
                        [
                            ("No ranking.", "Every row looks as urgent as every other row."),
                            ("No memory.", "Yesterday's call is lost by Thursday."),
                            ("No drafting.", "The blank email is where contact stops."),
                            ("No record.", "Nothing to review when a month produces nothing."),
                        ]
                    ),
                    className="slide-body",
                ),
            ]
        )

    def scoring() -> Any:
        return html.Div(
            [
                html.Div("How it ranks", className="kicker"),
                html.H2(["One mark from", html.Em(" zero to nine.")]),
                html.Div(
                    "Four signals, weighted and blended in a single vectorised pass over "
                    "the whole table, stored on the row and indexed — so the directory "
                    "sorts in SQL rather than in Python.",
                    className="lede",
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                _bullets(
                                    [
                                        ("Rating.", f"the public score out of 5 — weight {settings.W_RATING:g}"),
                                        ("Review weight.", f"log-scaled, so evidence counts — weight {settings.W_REVIEWS:g}"),
                                        ("Website gap.", f"nothing to send people to — weight {settings.W_GAP:g}"),
                                        ("Reachability.", f"a phone number on file — weight {settings.W_REACH:g}"),
                                    ]
                                )
                            ]
                        ),
                        ui.graph(charts.score_distribution(employers, dark)),
                    ],
                    className="slide-body grid-2-even",
                ),
            ]
        )

    def opportunity() -> Any:
        headline = (
            f"{worst_row['sector']} is the thinnest: "
            f"{worst_row['no_site']} of {worst_row['total']} have no site."
            if worst_row
            else "The gap is spread evenly across sectors."
        )
        return html.Div(
            [
                html.Div("Where the work is", className="kicker"),
                html.H2([f"{m['no_site']} businesses with", html.Br(), html.Em("nowhere to send people.")]),
                html.Div(headline, className="lede"),
                html.Div(
                    [
                        ui.graph(charts.gap_bar(breakdown, dark)),
                        ui.graph(charts.reputation_scatter(employers, dark)),
                    ],
                    className="slide-body grid-2-even",
                ),
            ]
        )

    def tracking_slide() -> Any:
        return html.Div(
            [
                html.Div("Tracking", className="kicker"),
                html.H2(["Seven stages,", html.Em(" one per account.")]),
                html.Div(
                    "Star an employer and it enters your board. Stage, contact, notes and "
                    "every message sent stay attached to your account — not shared, not "
                    "global.",
                    className="lede",
                ),
                html.Div(
                    [
                        ui.graph(charts.stage_funnel(repo.stage_counts(uid), dark)),
                        _bullets(
                            [
                                ("Scouted → Closed.", "a fixed vocabulary, so the board is comparable week to week"),
                                ("Automatic advance.", "sending a message moves an employer to Contacted"),
                                ("Per-account.", "your notes are yours; the directory is shared"),
                            ]
                        ),
                    ],
                    className="slide-body grid-2-even",
                ),
            ]
        )

    def contact_slide() -> Any:
        return html.Div(
            [
                html.Div("Contact", className="kicker"),
                html.H2(["Templated mail,", html.Em(" logged on every send.")]),
                html.Div(
                    "Placeholders fill from the employer's own record. Every attempt — "
                    "sent, simulated, failed or rejected — lands in the log with its "
                    "reason.",
                    className="lede",
                ),
                html.Div(
                    _bullets(
                        [
                            ("Placeholders.", "{name}, {sector}, {rating}, {reviews} and seven more"),
                            ("Dry run by default.", f"currently {'ON — nothing is delivered' if settings.MAIL_DRY_RUN else 'OFF — mail is live'}"),
                            ("Daily cap.", f"{settings.MAIL_DAILY_CAP} messages per account, enforced before the socket opens"),
                            ("Headers built safely.", "composed through email.message, so a subject cannot inject a header"),
                            ("Transport.", mailer.status_note()),
                        ]
                    ),
                    className="slide-body",
                ),
            ]
        )

    def ai_slide() -> Any:
        usage = repo.ai_usage(30)
        return html.Div(
            [
                html.Div("Gemini", className="kicker"),
                html.H2(["The blank email,", html.Em(" already written.")]),
                html.Div(
                    "Gemini drafts from the record in front of it: a specific opening "
                    "observation, one ask, under 150 words. It is instructed never to "
                    "invent a fact about an employer and to name a missing field instead.",
                    className="lede",
                ),
                html.Div(
                    [
                        _bullets(
                            [
                                ("Draft an email.", "goal, tone and language, straight into the composer"),
                                ("Approach brief.", "read on the business, likely gap, opening angle, risks"),
                                ("Ask the directory.", "answered from live aggregates, not a stale export"),
                                ("Metered.", f"{usage['runs']} calls and {ui.fmt_compact(usage['input_tokens'] + usage['output_tokens'])} tokens in 30 days"),
                                ("Status.", ai.status_note()),
                            ]
                        ),
                        ui.graph(charts.ai_usage_bar(repo.ai_runs_by_kind(30), dark)),
                    ],
                    className="slide-body grid-2-even",
                ),
            ]
        )

    def build() -> Any:
        return html.Div(
            [
                html.Div("How it is built", className="kicker"),
                html.H2(["Python,", html.Em(" end to end.")]),
                html.Div(
                    "One Flask process. Server-rendered auth pages, a Dash dashboard "
                    "mounted behind a login guard, Plotly for every figure, SQLite with "
                    "WAL for storage.",
                    className="lede",
                ),
                html.Div(
                    [
                        _bullets(
                            [
                                ("Dash + Plotly.", "every chart recoloured for light and dark from validated palettes"),
                                ("Flask-Login.", "scrypt hashes, CSRF tokens, throttled attempts, rotated sessions"),
                                ("SQLite + WAL.", "precomputed scores on an index; reads never block on a write"),
                                ("NumPy scoring.", "the whole table scored in one pass, not row by row"),
                                ("Cached frame.", "the read-mostly directory is held as one DataFrame, not re-queried per callback"),
                            ]
                        ),
                        ui.kv_table(
                            [
                                ("Accounts", ui.fmt_int(stats.get("users", 0))),
                                ("Employers", ui.fmt_int(stats.get("employers", 0))),
                                ("Tracked rows", ui.fmt_int(stats.get("tracked", 0))),
                                ("Messages logged", ui.fmt_int(stats.get("emails", 0))),
                                ("Templates", ui.fmt_int(stats.get("templates", 0))),
                                ("AI calls", ui.fmt_int(stats.get("ai_runs", 0))),
                            ]
                        ),
                    ],
                    className="slide-body grid-2-even",
                ),
            ]
        )

    def close() -> Any:
        return html.Div(
            [
                html.Div("Next", className="kicker"),
                html.H2(["Open the directory,", html.Br(), html.Em("and start calling.")]),
                html.Div(
                    f"{m['priority']} employers currently score 7 or higher. "
                    f"{m['no_site']} have no website at all. That is the week's work.",
                    className="lede",
                ),
                html.Div(
                    html.Div(
                        [
                            dcc.Link("Open the directory", href="/app/directory", className="btn primary"),
                            dcc.Link("Work the tracking board", href="/app/tracking", className="btn"),
                            dcc.Link("Write a message", href="/app/contact", className="btn"),
                        ],
                        className="btn-row",
                    ),
                    className="slide-body",
                ),
                html.Div(
                    f"{settings.APP_NAME} · {date.today():%d %B %Y}",
                    className="auth-legal",
                ),
            ]
        )

    return [title, problem, scoring, opportunity, tracking_slide, contact_slide, ai_slide, build, close]


TITLES = [
    "Title",
    "The problem",
    "How it ranks",
    "Where the work is",
    "Tracking",
    "Contact",
    "Gemini",
    "How it is built",
    "Next",
]


def layout(dark: bool = False) -> Any:
    return html.Div(
        [
            dcc.Store(id="deck-i", data=0),
            dcc.Store(id="deck-dark", data=dark),
            html.Div(id="deck-slide"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Button("← Back", id="deck-prev", className="btn", n_clicks=0),
                            html.Button("Next →", id="deck-next", className="btn primary", n_clicks=0),
                        ],
                        className="btn-row",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "",
                                id={"type": "deck-dot", "i": i},
                                className="deck-dot",
                                n_clicks=0,
                                title=t,
                                **{"aria-label": t},
                            )
                            for i, t in enumerate(TITLES)
                        ],
                        className="deck-dots",
                    ),
                    html.Div(id="deck-counter", className="deck-counter"),
                ],
                className="deck-nav",
            ),
        ]
    )


def register(app: dash.Dash) -> None:
    @app.callback(
        Output("deck-slide", "children"),
        Output("deck-counter", "children"),
        Output("deck-prev", "disabled"),
        Output("deck-next", "disabled"),
        Output({"type": "deck-dot", "i": ALL}, "className"),
        Input("deck-i", "data"),
        State("deck-dark", "data"),
    )
    def _render(index, dark):
        slides = _slides(bool(dark))
        i = max(0, min(int(index or 0), len(slides) - 1))
        return (
            html.Div(slides[i](), className="slide"),
            f"{TITLES[i]} — {i + 1} of {len(slides)}",
            i == 0,
            i == len(slides) - 1,
            ["deck-dot on" if j == i else "deck-dot" for j in range(len(TITLES))],
        )

    @app.callback(
        Output("deck-i", "data"),
        Input("deck-prev", "n_clicks"),
        Input("deck-next", "n_clicks"),
        Input({"type": "deck-dot", "i": ALL}, "n_clicks"),
        State("deck-i", "data"),
        prevent_initial_call=True,
    )
    def _navigate(_prev, _next, dot_clicks, index):
        trigger = callback_context.triggered_id
        i = int(index or 0)
        last = len(TITLES) - 1
        if trigger == "deck-prev":
            return max(0, i - 1)
        if trigger == "deck-next":
            return min(last, i + 1)
        if isinstance(trigger, dict) and ui.any_clicks(dot_clicks):
            return max(0, min(last, int(trigger.get("i", 0))))
        return no_update
