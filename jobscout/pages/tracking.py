"""Tracking: a seven-stage board over the employers you follow, plus notes."""

from __future__ import annotations

from typing import Any

import dash
from dash import ALL, Input, Output, State, callback_context, dcc, html, no_update
from flask_login import current_user

from jobscout import charts, repo, ui
from jobscout.db import STAGE_LABELS, STAGES


def layout(dark: bool = False) -> Any:
    uid = int(current_user.uid)
    counts = repo.stage_counts(uid)
    total = sum(counts.values())

    return html.Div(
        [
            dcc.Store(id="pipe-sel", data=None),
            dcc.Store(id="pipe-bump", data=0),
            dcc.Store(id="pipe-dark", data=dark),
            ui.section_head("Tracking", f"{total} employers tracked"),
            html.Div(id="pipe-flash"),
            html.Div(id="pipe-board", className="fade-up"),
            html.Div(
                [
                    ui.panel(
                        "Stage mix",
                        "How the tracked list is distributed",
                        ui.graph(charts.stage_funnel(counts, dark), id="pipe-funnel"),
                    ),
                    html.Div(id="pipe-detail"),
                ],
                className="grid-2",
                style={"marginTop": "28px"},
            ),
        ]
    )


def _board(df: Any, selected: str | None) -> Any:
    if df.empty:
        return html.Div(
            ui.empty(
                "Nothing tracked yet. Star an employer in the directory and it appears here."
            ),
            className="panel",
        )

    cols = []
    for stage in STAGES:
        sub = df[df["stage"] == stage]
        cards: list[Any] = []
        for rec in sub.to_dict("records"):
            cards.append(
                html.Div(
                    [
                        html.Div(rec["name"], className="nm"),
                        html.Div(
                            [
                                ui.score_chip(int(rec["score"])),
                                html.Span(rec["sector"]),
                            ],
                            className="mt",
                        ),
                    ],
                    id={"type": "pipe-card", "id": rec["id"]},
                    className="board-card",
                    n_clicks=0,
                    style=(
                        {"borderColor": "var(--rust)", "background": "var(--rust-tint)"}
                        if rec["id"] == selected
                        else {}
                    ),
                )
            )
        cols.append(
            html.Div(
                [
                    html.H4([STAGE_LABELS[stage], html.Span(str(len(sub)), className="n")]),
                    *(cards or [html.Div("—", className="board-empty")]),
                ],
                className="board-col",
            )
        )
    return html.Div(cols, className="board")


def _detail(rec: dict[str, Any] | None) -> Any:
    if rec is None:
        return ui.panel(
            "Record",
            "Pick a card to see and edit its details",
            ui.empty("Nothing selected."),
        )

    site = ui.safe_url(rec.get("website"))
    wa = ui.whatsapp_url(rec.get("phone"))
    links: list[Any] = []
    if wa:
        links.append(ui.link_btn("WhatsApp", wa))
    if site:
        links.append(ui.link_btn("Visit site", site))
    links.append(
        dcc.Link("Write a message", href=f"/app/contact?employer={rec['id']}", className="btn primary")
    )

    return ui.panel(
        rec["name"],
        f"{rec['sector']} · score {rec['score']} of 9",
        html.Div(
            [
                html.Div(
                    [
                        ui.detail_line("Phone", rec.get("phone") or "—"),
                        ui.detail_line(
                            "Rating",
                            f"{rec['rating']} / 5 ({ui.fmt_int(rec.get('reviews') or 0)} reviews)"
                            if rec.get("rating") is not None
                            else "not rated",
                        ),
                        ui.detail_line("Website", site or "none on file"),
                    ],
                    style={"marginBottom": "18px"},
                ),
                html.Div(
                    [
                        ui.field(
                            "Stage",
                            dcc.Dropdown(
                                id="pipe-stage",
                                options=[{"label": STAGE_LABELS[s], "value": s} for s in STAGES],
                                value=rec["stage"],
                                clearable=False,
                            ),
                        ),
                        html.Div(
                            [
                                ui.field(
                                    "Contact name",
                                    dcc.Input(
                                        id="pipe-contact-name",
                                        type="text",
                                        value=rec.get("contact_name") or "",
                                        placeholder="Who you speak to",
                                    ),
                                ),
                                ui.field(
                                    "Contact email",
                                    dcc.Input(
                                        id="pipe-contact-email",
                                        type="email",
                                        value=rec.get("contact_email") or "",
                                        placeholder="name@company.ma",
                                    ),
                                ),
                            ],
                            className="field-row",
                        ),
                        ui.field(
                            "Notes",
                            dcc.Textarea(
                                id="pipe-notes",
                                value=rec.get("notes") or "",
                                placeholder="What was said, what to do next…",
                                style={"minHeight": "120px"},
                            ),
                        ),
                        html.Div(
                            [
                                html.Button("Save record", id="pipe-save", className="btn primary", n_clicks=0),
                                html.Button("Stop tracking", id="pipe-untrack", className="btn danger", n_clicks=0),
                            ],
                            className="btn-row",
                        ),
                    ]
                ),
                html.Div(links, className="btn-row", style={"marginTop": "18px"}),
            ]
        ),
    )


def register(app: dash.Dash) -> None:
    @app.callback(
        Output("pipe-board", "children"),
        Output("pipe-detail", "children"),
        Output("pipe-funnel", "figure"),
        Input("pipe-sel", "data"),
        Input("pipe-bump", "data"),
        State("pipe-dark", "data"),
    )
    def _render(selected, _bump, dark):
        uid = int(current_user.uid)
        df = repo.tracked_frame(uid)
        rec = None
        if selected is not None and not df.empty:
            hit = df[df["id"] == selected]
            if not hit.empty:
                rec = hit.to_dict("records")[0]
        return (
            _board(df, selected),
            _detail(rec),
            charts.stage_funnel(repo.stage_counts(uid), bool(dark)),
        )

    @app.callback(
        Output("pipe-sel", "data"),
        Input({"type": "pipe-card", "id": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _select(clicks):
        trigger = callback_context.triggered_id
        if not isinstance(trigger, dict) or not ui.any_clicks(clicks):
            return no_update
        return trigger["id"]

    @app.callback(
        Output("pipe-bump", "data", allow_duplicate=True),
        Output("pipe-flash", "children", allow_duplicate=True),
        Input("pipe-save", "n_clicks"),
        State("pipe-sel", "data"),
        State("pipe-stage", "value"),
        State("pipe-contact-name", "value"),
        State("pipe-contact-email", "value"),
        State("pipe-notes", "value"),
        State("pipe-bump", "data"),
        prevent_initial_call=True,
    )
    def _save(clicks, emp_id, stage, contact_name, contact_email, notes, bump):
        if not clicks or not emp_id:
            return no_update, no_update
        if stage not in STAGES:
            return no_update, ui.alert("That stage is not recognised.", "err")
        repo.upsert_tracking(
            int(current_user.uid),
            emp_id,
            stage=stage,
            contact_name=(contact_name or "")[:120],
            contact_email=(contact_email or "")[:254],
            notes=(notes or "")[:8000],
        )
        return int(bump or 0) + 1, ui.alert("Record saved.", "ok")

    @app.callback(
        Output("pipe-bump", "data", allow_duplicate=True),
        Output("pipe-flash", "children", allow_duplicate=True),
        Output("pipe-sel", "data", allow_duplicate=True),
        Input("pipe-untrack", "n_clicks"),
        State("pipe-sel", "data"),
        State("pipe-bump", "data"),
        prevent_initial_call=True,
    )
    def _untrack(clicks, emp_id, bump):
        if not clicks or not emp_id:
            return no_update, no_update, no_update
        repo.untrack(int(current_user.uid), emp_id)
        return int(bump or 0) + 1, ui.alert("Removed from your tracking board.", "ok"), None
