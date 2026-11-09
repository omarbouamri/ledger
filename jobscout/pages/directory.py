"""Directory: search, filter, sort, star, and open an employer record."""

from __future__ import annotations

from typing import Any

import dash
from dash import ALL, Input, Output, State, callback_context, dcc, html, no_update
from flask_login import current_user

from jobscout import repo, ui
from jobscout.db import STAGE_LABELS, STAGES

PAGE_SIZE = 40

SORTS = [
    {"label": "Score", "value": "score"},
    {"label": "Name", "value": "name"},
    {"label": "Rating", "value": "rating"},
    {"label": "Reviews", "value": "reviews"},
    {"label": "Sector", "value": "sector"},
]


def layout(dark: bool = False) -> Any:
    return html.Div(
        [
            dcc.Store(id="dir-open", data=None),
            dcc.Store(id="dir-page", data=1),
            dcc.Store(id="dir-bump", data=0),
            ui.section_head(
                "The directory",
                extra=html.Div(id="dir-count", className="count num"),
            ),
            html.Div(
                [
                    dcc.Input(
                        id="dir-search",
                        type="text",
                        placeholder="Search name, sector or address…",
                        debounce=False,
                        style={"flex": "1", "minWidth": "200px"},
                    ),
                    html.Div(
                        dcc.Dropdown(
                            id="dir-sector",
                            options=[{"label": s, "value": s} for s in repo.sectors()],
                            placeholder="All lines of work",
                            clearable=True,
                        ),
                        style={"minWidth": "220px", "flex": "0 0 220px"},
                    ),
                    html.Div(
                        dcc.Dropdown(
                            id="dir-sort",
                            options=SORTS,
                            value="score",
                            clearable=False,
                        ),
                        style={"minWidth": "140px", "flex": "0 0 140px"},
                    ),
                    html.Button("↓", id="dir-dir", className="chip-toggle", n_clicks=0,
                                title="Reverse the sort"),
                    dcc.Checklist(
                        id="dir-flags",
                        options=[
                            {"label": "No website only", "value": "nosite"},
                            {"label": "Priority (7+)", "value": "priority"},
                            {"label": "Tracked only", "value": "tracked"},
                        ],
                        value=[],
                        inline=True,
                        inputStyle={"marginRight": "5px", "width": "auto"},
                        labelStyle={
                            "display": "flex",
                            "alignItems": "center",
                            "gap": "4px",
                            "fontSize": "13px",
                            "color": "var(--ink-soft)",
                            "marginRight": "12px",
                            "whiteSpace": "nowrap",
                        },
                    ),
                    html.Button("Clear", id="dir-reset", className="reset-link", n_clicks=0),
                ],
                className="filter-bar",
            ),
            html.Div(id="dir-table", className="fade-up"),
            html.Div(id="dir-more", style={"marginTop": "18px", "textAlign": "center"}),
        ]
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _ascending(sort_by: str | None, clicks: int | None) -> bool:
    """Text sorts read best A→Z, numbers best high→low. The button flips either."""
    natural_ascending = (sort_by or "score") in {"name", "sector"}
    return natural_ascending != bool((clicks or 0) % 2)


def _header() -> Any:
    return html.Thead(
        html.Tr(
            [
                html.Th(style={"width": "30px"}),
                html.Th("Name"),
                html.Th("Rating"),
                html.Th("Reviews"),
                html.Th("Score"),
                html.Th("Website"),
                html.Th("Stage"),
            ]
        )
    )


def _detail(rec: dict[str, Any], track: dict[str, Any] | None) -> Any:
    site = ui.safe_url(rec.get("website"))
    wa = ui.whatsapp_url(rec.get("phone"))
    maps = ui.safe_url(rec.get("maps_url"))
    emp_id = rec["id"]
    stage = (track or {}).get("stage", "scouted")

    actions: list[Any] = []
    if wa:
        actions.append(ui.link_btn("WhatsApp", wa))
    if site:
        actions.append(ui.link_btn("Visit site", site))
    if maps:
        actions.append(ui.link_btn("Open in Maps", maps))
    actions.append(
        dcc.Link(
            "Write a message",
            href=f"/app/contact?employer={emp_id}",
            className="btn primary",
        )
    )

    return html.Tr(
        html.Td(
            html.Div(
                [
                    html.Div(
                        [
                            html.H4("Contact"),
                            ui.detail_line("Phone", rec.get("phone") or "—"),
                            ui.detail_line("Address", rec.get("address") or "—"),
                            ui.detail_line("Website", site or "none on file"),
                        ],
                        className="detail-col",
                    ),
                    html.Div(
                        [
                            html.H4("Standing"),
                            ui.detail_line(
                                "Rating",
                                f"{rec['rating']} / 5" if rec.get("rating") is not None else "not rated",
                            ),
                            ui.detail_line("Reviews", ui.fmt_int(rec.get("reviews") or 0)),
                            ui.detail_line("Score", f"{rec['score']} of 9"),
                            ui.detail_line("Sector", rec.get("sector") or "—"),
                        ],
                        className="detail-col",
                    ),
                    html.Div(
                        [
                            html.H4("Follow up"),
                            html.Div(actions, className="detail-actions btn-row"),
                            html.Div(
                                [
                                    html.Label("Tracking stage", className="lbl"),
                                    dcc.Dropdown(
                                        id={"type": "dir-stage", "id": emp_id},
                                        options=[
                                            {"label": STAGE_LABELS[s], "value": s} for s in STAGES
                                        ],
                                        value=stage,
                                        clearable=False,
                                    ),
                                ],
                                style={"marginTop": "14px"},
                            ),
                            html.Div(
                                "No website on record — a call or a WhatsApp message is the "
                                "direct route in."
                                if not rec.get("has_website")
                                else "",
                                className="note-box" if not rec.get("has_website") else "",
                            ),
                        ],
                        className="detail-col",
                    ),
                ],
                className="detail-inner",
            ),
            colSpan=7,
            style={"padding": "0"},
        ),
        className="detail-row",
    )


def _rows(records: list[dict[str, Any]], tracking: dict[str, Any], open_id: str | None) -> list[Any]:
    out: list[Any] = []
    for rec in records:
        emp_id = rec["id"]
        track = tracking.get(emp_id)
        starred = bool(track and track["starred"])
        is_open = emp_id == open_id

        out.append(
            html.Tr(
                [
                    html.Td(
                        html.Button(
                            "★" if starred else "☆",
                            id={"type": "dir-star", "id": emp_id},
                            className=f"star-btn {'on' if starred else ''}".strip(),
                            n_clicks=0,
                            title="Save to your tracking board",
                        )
                    ),
                    html.Td(
                        [
                            html.Span(rec["sector"], className="cat-tag"),
                            html.Button(
                                rec["name"],
                                id={"type": "dir-row", "id": emp_id},
                                className="row-link",
                                n_clicks=0,
                            ),
                        ],
                        className="td-name",
                    ),
                    html.Td(
                        f"{rec['rating']:.1f}" if rec.get("rating") is not None else "—",
                        className="num",
                    ),
                    html.Td(ui.fmt_int(rec.get("reviews") or 0), className="num"),
                    html.Td(ui.score_chip(int(rec["score"]))),
                    html.Td(ui.site_flag(bool(rec["has_website"]))),
                    html.Td(
                        ui.badge(STAGE_LABELS[track["stage"]], "rust")
                        if track
                        else html.Span("—", style={"color": "var(--ink-faint)"})
                    ),
                ],
                className=f"main-row {'expanded' if is_open else ''}".strip(),
            )
        )
        if is_open:
            out.append(_detail(rec, track))
    return out


# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #
def register(app: dash.Dash) -> None:
    @app.callback(
        Output("dir-table", "children"),
        Output("dir-count", "children"),
        Output("dir-more", "children"),
        Input("dir-search", "value"),
        Input("dir-sector", "value"),
        Input("dir-sort", "value"),
        Input("dir-dir", "n_clicks"),
        Input("dir-flags", "value"),
        Input("dir-open", "data"),
        Input("dir-page", "data"),
        Input("dir-bump", "data"),
    )
    def _render(search, sector, sort_by, dir_clicks, flags, open_id, page, _bump):
        uid = int(current_user.uid)
        flags = flags or []
        ascending = _ascending(sort_by, dir_clicks)

        df = repo.filter_employers(
            search=search or "",
            sector=sector or "",
            no_website_only="nosite" in flags,
            min_score=7 if "priority" in flags else 0,
            sort_by=sort_by or "score",
            ascending=ascending,
        )
        tracking = repo.tracking_for(uid)
        if "tracked" in flags and not df.empty:
            df = df[df["id"].isin(tracking.keys())]

        total = len(df)
        shown = min(total, max(1, int(page or 1)) * PAGE_SIZE)
        records = df.head(shown).to_dict("records")

        grand = len(repo.employers_frame())
        count_text = f"{total} of {grand} entries"

        if not records:
            table = html.Div(
                ui.empty("Nothing matches those filters. Try clearing one."),
                className="panel",
            )
        else:
            table = html.Div(
                html.Table(
                    [_header(), html.Tbody(_rows(records, tracking, open_id))],
                    className="ledger",
                ),
                className="ledger-table-wrap",
            )

        more = (
            html.Button(
                f"Show {min(PAGE_SIZE, total - shown)} more",
                id="dir-load",
                className="btn",
                n_clicks=0,
            )
            if shown < total
            else html.Div(
                f"End of the list — {total} entries." if total else "",
                style={"fontSize": "12px", "color": "var(--ink-faint)", "fontStyle": "italic"},
            )
        )
        return table, count_text, more

    @app.callback(
        Output("dir-page", "data"),
        Input("dir-load", "n_clicks"),
        Input("dir-search", "value"),
        Input("dir-sector", "value"),
        Input("dir-flags", "value"),
        State("dir-page", "data"),
        prevent_initial_call=True,
    )
    def _page(load_clicks, _s, _sec, _f, page):
        trigger = callback_context.triggered_id
        if trigger == "dir-load" and load_clicks:
            return int(page or 1) + 1
        return 1  # any filter change resets paging

    @app.callback(
        Output("dir-open", "data"),
        Input({"type": "dir-row", "id": ALL}, "n_clicks"),
        State("dir-open", "data"),
        prevent_initial_call=True,
    )
    def _toggle_row(clicks, open_id):
        trigger = callback_context.triggered_id
        if not isinstance(trigger, dict) or not ui.any_clicks(clicks):
            return no_update
        emp_id = trigger["id"]
        return None if emp_id == open_id else emp_id

    @app.callback(
        Output("dir-bump", "data", allow_duplicate=True),
        Input({"type": "dir-star", "id": ALL}, "n_clicks"),
        State("dir-bump", "data"),
        prevent_initial_call=True,
    )
    def _star(clicks, bump):
        trigger = callback_context.triggered_id
        if not isinstance(trigger, dict) or not ui.any_clicks(clicks):
            return no_update
        repo.toggle_star(int(current_user.uid), trigger["id"])
        return int(bump or 0) + 1

    @app.callback(
        Output("dir-bump", "data", allow_duplicate=True),
        Input({"type": "dir-stage", "id": ALL}, "value"),
        State("dir-bump", "data"),
        prevent_initial_call=True,
    )
    def _stage(values, bump):
        trigger = callback_context.triggered_id
        if not isinstance(trigger, dict):
            return no_update
        stage = ui.first_value(values)
        if stage not in STAGES:
            return no_update
        repo.upsert_tracking(int(current_user.uid), trigger["id"], stage=stage)
        return int(bump or 0) + 1

    @app.callback(
        Output("dir-search", "value"),
        Output("dir-sector", "value"),
        Output("dir-flags", "value"),
        Input("dir-reset", "n_clicks"),
        prevent_initial_call=True,
    )
    def _reset(_clicks):
        return "", None, []

    @app.callback(
        Output("dir-dir", "children"),
        Input("dir-dir", "n_clicks"),
        Input("dir-sort", "value"),
    )
    def _arrow(clicks, sort_by):
        return "↑" if _ascending(sort_by, clicks) else "↓"
