"""Overview: the state of the directory and of your own tracking board."""

from __future__ import annotations

from datetime import date
from typing import Any

import dash
from dash import html
from flask_login import current_user

from config import settings
from jobscout import charts, repo, ui


def layout(dark: bool = False) -> Any:
    uid = int(current_user.uid)
    m = repo.overview_metrics(uid)
    breakdown = repo.sector_breakdown()
    employers = repo.employers_frame()
    counts = repo.stage_counts(uid)

    reply_rate = (m["replied"] / m["contacted"] * 100) if m["contacted"] else 0.0

    return html.Div(
        [
            ui.masthead(
                settings.CITY,
                f"{m['employers']} employers,",
                "scored and on file.",
                "A working record of businesses operating in "
                f"{settings.CITY.split(',')[0]} — pulled from public listings, scored on "
                "reputation, review weight and the gaps worth calling about, and kept "
                "here so nothing is forgotten between calls.",
                folio="Folio No. 01",
                folio_sub=f"{m['employers']} entries · {m['sectors']} lines of work",
            ),
            ui.stat_strip(
                [
                    ("Employers", ui.fmt_int(m["employers"]), "", f"{m['sectors']} lines of work"),
                    ("No website on file", ui.fmt_int(m["no_site"]), "rust", "the clearest opening"),
                    ("Average rating", f"{m['avg_rating']:.2f}", "", "across rated entries"),
                    ("Review volume", ui.fmt_compact(m["reviews"]), "moss", "public reviews counted"),
                ]
            ),
            # ---- your own numbers -------------------------------------------
            html.Div(
                [
                    ui.section_head(
                        "Your tracking board",
                        f"{m['tracked']} tracked · {m['contacted']} contacted",
                    ),
                    html.Div(
                        [
                            ui.panel(
                                "Stages",
                                "Where the employers you track currently sit",
                                ui.graph(charts.stage_funnel(counts, dark)),
                            ),
                            html.Div(
                                [
                                    ui.panel(
                                        "Working the list",
                                        "Your own progress through the directory",
                                        ui.kv_table(
                                            [
                                                ("Tracked", ui.fmt_int(m["tracked"])),
                                                ("Contacted", ui.fmt_int(m["contacted"])),
                                                ("Replied or further", ui.fmt_int(m["replied"])),
                                                ("Reply rate", f"{reply_rate:.0f}%"),
                                                ("Priority employers (7+)", ui.fmt_int(m["priority"])),
                                                (
                                                    "Share of directory tracked",
                                                    f"{(m['tracked'] / m['employers'] * 100 if m['employers'] else 0):.0f}%",
                                                ),
                                            ]
                                        ),
                                    ),
                                    ui.panel(
                                        "Reading the score",
                                        "How JobScout ranks an entry",
                                        html.Div(
                                            [
                                                html.P(
                                                    "Each employer gets a mark from 0–9. It blends the "
                                                    "public rating, how many reviews back it up (log "
                                                    "scaled, so a well-reviewed 4.3 can outrank a lone "
                                                    "5.0), whether a website is missing, and whether "
                                                    "there is a phone number to call today.",
                                                    style={"margin": "0 0 12px"},
                                                ),
                                                html.Div(
                                                    [
                                                        ui.score_chip(2),
                                                        ui.score_chip(6),
                                                        ui.score_chip(8),
                                                        html.Span(
                                                            "low signal · worth a look · priority",
                                                            style={
                                                                "fontSize": "12px",
                                                                "color": "var(--ink-faint)",
                                                                "marginLeft": "4px",
                                                            },
                                                        ),
                                                    ],
                                                    style={
                                                        "display": "flex",
                                                        "gap": "6px",
                                                        "alignItems": "center",
                                                    },
                                                ),
                                            ]
                                        ),
                                    ),
                                ],
                                className="stack",
                            ),
                        ],
                        className="grid-2 fade-up",
                    ),
                ],
                className="section",
            ),
            # ---- the directory itself ---------------------------------------
            html.Div(
                [
                    ui.section_head("The directory at a glance"),
                    # Two panels of roughly equal height per row, rather than one
                    # tall panel beside a stack of two: the columns then end on
                    # the same line instead of leaving a ragged edge.
                    html.Div(
                        [
                            ui.panel(
                                "By line of work",
                                "Employers on file per sector, ten largest",
                                ui.graph(charts.sector_bar(breakdown, dark)),
                            ),
                            ui.panel(
                                "Website gap by line of work",
                                "Which sectors are least likely to have a site on file",
                                ui.graph(charts.gap_bar(breakdown, dark)),
                            ),
                        ],
                        className="grid-2-even fade-up",
                    ),
                    html.Div(
                        [
                            ui.panel(
                                "Reputation against review volume",
                                "Each dot is one employer. Diamonds have no website on "
                                "file — a strong rating with nowhere to send people.",
                                ui.graph(charts.reputation_scatter(employers, dark)),
                            ),
                            ui.panel(
                                "Score distribution",
                                "How the 0–9 marks fall across the directory",
                                ui.graph(charts.score_distribution(employers, dark)),
                            ),
                        ],
                        className="grid-2 fade-up",
                        style={"marginTop": "20px"},
                    ),
                ],
                className="section",
            ),
            # ---- shortcuts ---------------------------------------------------
            html.Div(
                [
                    ui.section_head("Next move"),
                    html.Div(
                        [
                            ui.panel(
                                "Highest-scoring, not yet tracked",
                                "Start here",
                                _quick_list(uid),
                            ),
                            ui.panel(
                                "Jump to",
                                "",
                                html.Div(
                                    [
                                        html.A("Open the directory", href="/app/directory", className="btn"),
                                        html.A("Work the tracking board", href="/app/tracking", className="btn"),
                                        html.A("Write a message", href="/app/contact", className="btn primary"),
                                        html.A("Ask the assistant", href="/app/assistant", className="btn"),
                                    ],
                                    className="btn-row",
                                ),
                            ),
                        ],
                        className="grid-2 fade-up",
                    ),
                ],
                className="section",
            ),
            html.Div(
                f"Folio compiled {date.today():%d %B %Y}",
                style={
                    "fontSize": "12px",
                    "color": "var(--ink-faint)",
                    "fontStyle": "italic",
                },
            ),
        ]
    )


def _quick_list(uid: int) -> Any:
    tracked = set(repo.tracking_for(uid))
    df = repo.employers_frame()
    if df.empty:
        return ui.empty("No employers on file yet.")
    fresh = df[~df["id"].isin(tracked)].head(6)
    if fresh.empty:
        return ui.empty("You are already tracking every high scorer. Good.")
    rows = [
        html.Div(
            [
                html.Div(
                    [
                        html.Div(rec["name"], className="region-name"),
                        html.Div(
                            f"{rec['sector']} · "
                            + ("site on file" if rec["has_website"] else "no website"),
                            className="region-meta",
                        ),
                    ]
                ),
                ui.score_chip(int(rec["score"])),
            ],
            className="region-row",
        )
        for rec in fresh.to_dict("records")
    ]
    return html.Div(rows, className="region-list")


def register(app: dash.Dash) -> None:
    """No page-local callbacks: the overview is rendered fresh on navigation."""
    return None
