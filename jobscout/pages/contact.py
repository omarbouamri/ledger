"""Contact: compose from a template or with Gemini, then send and log."""

from __future__ import annotations

import urllib.parse
from typing import Any

import dash
from dash import Input, Output, State, dcc, html, no_update
from flask_login import current_user

from config import settings
from jobscout import ai, charts, mailer, repo, ui
from jobscout.db import log_audit

GOALS = [
    {"label": "Introduce myself and ask for a short call", "value": "introduce myself and ask for a short call"},
    {"label": "Ask whether they are hiring", "value": "ask whether they have any openings or project work"},
    {"label": "Offer to build or fix their website", "value": "offer to build or improve their website"},
    {"label": "Follow up on an earlier message", "value": "follow up politely on an earlier message that got no reply"},
]
TONES = [
    {"label": "Direct and warm", "value": "direct and warm"},
    {"label": "Formal", "value": "formal and respectful"},
    {"label": "Very short", "value": "extremely brief, three sentences at most"},
]
LANGUAGES = [
    {"label": "English", "value": "English"},
    {"label": "French", "value": "French"},
    {"label": "Both (English, then French)", "value": "English followed by a French translation"},
]


def _employer_options() -> list[dict[str, str]]:
    df = repo.employers_frame()
    if df.empty:
        return []
    return [
        {"label": f"{r['name']} · {r['sector']} · score {r['score']}", "value": r["id"]}
        for r in df.head(400).to_dict("records")
    ]


def _preselected(search: str | None) -> str | None:
    if not search:
        return None
    try:
        params = urllib.parse.parse_qs(search.lstrip("?"))
    except ValueError:
        return None
    values = params.get("employer") or []
    return values[0] if values else None


def layout(dark: bool = False) -> Any:
    uid = int(current_user.uid)
    templates = repo.templates_for(uid)
    sent_today = repo.emails_sent_today(uid)

    transport_note = mailer.status_note()
    tone = "warn" if settings.MAIL_DRY_RUN else ("" if settings.smtp_configured() else "err")

    return html.Div(
        [
            dcc.Location(id="out-url", refresh=False),
            dcc.Store(id="out-draft", data={}),
            dcc.Store(id="out-bump", data=0),
            dcc.Store(id="out-dark", data=dark),
            ui.section_head(
                "Contact",
                f"{sent_today} of {settings.MAIL_DAILY_CAP} messages logged today",
            ),
            ui.alert(
                [html.Strong("Delivery: "), transport_note],
                tone,
            ),
            html.Div(
                [
                    # ---- composer -------------------------------------------
                    html.Div(
                        [
                            ui.panel(
                                "Compose",
                                "Pick an employer, start from a template, then edit freely",
                                html.Div(
                                    [
                                        ui.field(
                                            "Employer",
                                            dcc.Dropdown(
                                                id="out-employer",
                                                options=_employer_options(),
                                                placeholder="Search the directory…",
                                                optionHeight=46,
                                            ),
                                            "Placeholders are filled from this record.",
                                        ),
                                        html.Div(
                                            [
                                                ui.field(
                                                    "Template",
                                                    dcc.Dropdown(
                                                        id="out-template",
                                                        options=[
                                                            {
                                                                "label": t["name"]
                                                                + ("" if t["user_id"] else " (shared)"),
                                                                "value": t["id"],
                                                            }
                                                            for t in templates
                                                        ],
                                                        placeholder="None",
                                                    ),
                                                ),
                                                ui.field(
                                                    "Send to",
                                                    dcc.Input(
                                                        id="out-to",
                                                        type="email",
                                                        placeholder="name@company.ma",
                                                    ),
                                                ),
                                            ],
                                            className="field-row",
                                        ),
                                        html.Div(
                                            [
                                                ui.field(
                                                    "Contact name",
                                                    dcc.Input(
                                                        id="out-contact",
                                                        type="text",
                                                        placeholder="Leave blank for “there”",
                                                    ),
                                                ),
                                                ui.field(
                                                    "Sign as",
                                                    dcc.Input(
                                                        id="out-sender",
                                                        type="text",
                                                        value=getattr(current_user, "name", ""),
                                                    ),
                                                ),
                                            ],
                                            className="field-row",
                                        ),
                                        ui.field(
                                            "Subject",
                                            dcc.Input(id="out-subject", type="text", placeholder="One line"),
                                        ),
                                        ui.field(
                                            "Body",
                                            dcc.Textarea(
                                                id="out-body",
                                                placeholder="Write the message, or let Gemini draft one…",
                                                style={"minHeight": "260px"},
                                            ),
                                            "Placeholders: " + ", ".join("{" + p + "}" for p in mailer.PLACEHOLDERS),
                                        ),
                                        html.Div(
                                            [
                                                html.Button("Fill placeholders", id="out-fill", className="btn", n_clicks=0),
                                                html.Button("Preview", id="out-preview", className="btn", n_clicks=0),
                                                html.Button(
                                                    "Send" if not settings.MAIL_DRY_RUN else "Send (dry run)",
                                                    id="out-send",
                                                    className="btn primary",
                                                    n_clicks=0,
                                                ),
                                                html.Button("Save as template", id="out-save-tpl", className="btn", n_clicks=0),
                                            ],
                                            className="btn-row",
                                        ),
                                        html.Div(id="out-flash", style={"marginTop": "16px"}),
                                        html.Div(id="out-preview-box"),
                                    ]
                                ),
                            )
                        ]
                    ),
                    # ---- AI + activity --------------------------------------
                    html.Div(
                        [
                            ui.panel(
                                "Draft with Gemini",
                                ai.status_note(),
                                html.Div(
                                    [
                                        ui.field(
                                            "Goal",
                                            dcc.Dropdown(id="out-goal", options=GOALS, value=GOALS[0]["value"], clearable=False),
                                        ),
                                        html.Div(
                                            [
                                                ui.field("Tone", dcc.Dropdown(id="out-tone", options=TONES, value=TONES[0]["value"], clearable=False)),
                                                ui.field("Language", dcc.Dropdown(id="out-lang", options=LANGUAGES, value="English", clearable=False)),
                                            ],
                                            className="field-row",
                                        ),
                                        ui.field(
                                            "Anything to add",
                                            dcc.Textarea(
                                                id="out-extra",
                                                placeholder="Optional: your background, a specific offer, a referral…",
                                                style={"minHeight": "80px"},
                                            ),
                                        ),
                                        html.Div(
                                            [
                                                html.Button(
                                                    "Draft the email",
                                                    id="out-ai-draft",
                                                    className="btn primary",
                                                    n_clicks=0,
                                                    disabled=not ai.available(),
                                                ),
                                                html.Button(
                                                    "Approach brief",
                                                    id="out-ai-brief",
                                                    className="btn",
                                                    n_clicks=0,
                                                    disabled=not ai.available(),
                                                ),
                                            ],
                                            className="btn-row",
                                        ),
                                        dcc.Loading(
                                            html.Div(id="out-ai-out", style={"marginTop": "16px"}),
                                            type="default",
                                            color="#a4491f",
                                        ),
                                    ]
                                ),
                            ),
                            ui.panel(
                                "Activity",
                                "Messages logged over the last 30 days",
                                ui.graph(
                                    charts.email_timeline(repo.email_activity(uid, 30), dark),
                                    id="out-activity",
                                ),
                            ),
                            ui.panel("Sent log", "Your most recent messages", html.Div(id="out-log")),
                        ],
                        className="stack",
                    ),
                ],
                className="grid-2",
            ),
        ]
    )


def _log_table(uid: int) -> Any:
    rows = repo.emails_for(uid, limit=40)
    if not rows:
        return ui.empty("Nothing sent yet.")
    tone = {"sent": "moss", "simulated": "rust", "failed": "danger", "invalid": "danger"}
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                r["employer_name"] or r["to_addr"],
                                className="region-name",
                            ),
                            html.Div(
                                f"{r['subject'][:60]} · {r['created_at'][:16].replace('T', ' ')}",
                                className="region-meta",
                            ),
                        ]
                    ),
                    ui.badge(r["status"].title(), tone.get(r["status"], "")),
                ],
                className="region-row",
            )
            for r in rows
        ],
        className="region-list",
    )


def register(app: dash.Dash) -> None:
    # ---- deep link from the directory / tracking board ---------------------
    @app.callback(
        Output("out-employer", "value"),
        Input("out-url", "search"),
        prevent_initial_call=False,
    )
    def _prefill(search):
        emp_id = _preselected(search)
        return emp_id or no_update

    # ---- picking an employer fills what we know ----------------------------
    @app.callback(
        Output("out-to", "value"),
        Output("out-contact", "value"),
        Input("out-employer", "value"),
        prevent_initial_call=True,
    )
    def _from_tracking(emp_id):
        if not emp_id:
            return no_update, no_update
        track = repo.tracking_for(int(current_user.uid)).get(emp_id)
        if not track:
            return "", ""
        return track.get("contact_email") or "", track.get("contact_name") or ""

    # ---- template load -----------------------------------------------------
    @app.callback(
        Output("out-subject", "value", allow_duplicate=True),
        Output("out-body", "value", allow_duplicate=True),
        Input("out-template", "value"),
        prevent_initial_call=True,
    )
    def _load_template(template_id):
        if not template_id:
            return no_update, no_update
        tpl = repo.template(int(template_id), int(current_user.uid))
        if not tpl:
            return no_update, no_update
        return tpl["subject"], tpl["body"]

    # ---- fill placeholders -------------------------------------------------
    @app.callback(
        Output("out-subject", "value", allow_duplicate=True),
        Output("out-body", "value", allow_duplicate=True),
        Output("out-flash", "children", allow_duplicate=True),
        Input("out-fill", "n_clicks"),
        State("out-employer", "value"),
        State("out-subject", "value"),
        State("out-body", "value"),
        State("out-sender", "value"),
        State("out-contact", "value"),
        prevent_initial_call=True,
    )
    def _fill(clicks, emp_id, subject, body, sender, contact):
        if not clicks:
            return no_update, no_update, no_update
        if not emp_id:
            return no_update, no_update, ui.alert("Pick an employer first.", "warn")
        emp = repo.employer(emp_id)
        if not emp:
            return no_update, no_update, ui.alert("That employer is no longer on file.", "err")
        return (
            mailer.render(subject or "", emp, sender_name=sender or "", contact_name=contact or ""),
            mailer.render(body or "", emp, sender_name=sender or "", contact_name=contact or ""),
            ui.alert("Placeholders filled from the record.", "ok"),
        )

    # ---- preview -----------------------------------------------------------
    @app.callback(
        Output("out-preview-box", "children"),
        Input("out-preview", "n_clicks"),
        State("out-employer", "value"),
        State("out-to", "value"),
        State("out-subject", "value"),
        State("out-body", "value"),
        State("out-sender", "value"),
        State("out-contact", "value"),
        prevent_initial_call=True,
    )
    def _preview(clicks, emp_id, to_addr, subject, body, sender, contact):
        if not clicks:
            return no_update
        emp = repo.employer(emp_id) if emp_id else None
        subject_r = mailer.render(subject or "", emp or {}, sender_name=sender or "", contact_name=contact or "")
        body_r = mailer.render(body or "", emp or {}, sender_name=sender or "", contact_name=contact or "")
        valid = mailer.valid_email(to_addr or "")
        return ui.panel(
            "Preview",
            "Exactly what would be sent",
            html.Div(
                [
                    ui.detail_line("To", (to_addr or "—") + ("" if valid else "  ← not a valid address")),
                    ui.detail_line("From", f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM or 'unset'}>"),
                    ui.detail_line("Subject", subject_r or "—"),
                    html.Div(body_r or "—", className="prose", style={"marginTop": "14px"}),
                ]
            ),
            style={"marginTop": "18px", "borderStyle": "dashed"},
            className="panel",
        )

    # ---- send --------------------------------------------------------------
    @app.callback(
        Output("out-flash", "children", allow_duplicate=True),
        Output("out-log", "children", allow_duplicate=True),
        Output("out-activity", "figure"),
        Input("out-send", "n_clicks"),
        State("out-employer", "value"),
        State("out-to", "value"),
        State("out-subject", "value"),
        State("out-body", "value"),
        State("out-sender", "value"),
        State("out-contact", "value"),
        State("out-dark", "data"),
        prevent_initial_call=True,
    )
    def _send(clicks, emp_id, to_addr, subject, body, sender, contact, dark):
        if not clicks:
            return no_update, no_update, no_update
        uid = int(current_user.uid)

        if not mailer.valid_email(to_addr or ""):
            return ui.alert("Enter a valid recipient address first.", "err"), no_update, no_update
        if not (subject or "").strip() or not (body or "").strip():
            return ui.alert("The subject and body cannot be empty.", "err"), no_update, no_update

        emp = repo.employer(emp_id) if emp_id else None
        report = mailer.send_batch(
            uid,
            [
                {
                    "to": to_addr.strip(),
                    "subject": mailer.render(subject, emp or {}, sender_name=sender or "", contact_name=contact or ""),
                    "body": mailer.render(body, emp or {}, sender_name=sender or "", contact_name=contact or ""),
                    "employer_id": emp_id,
                }
            ],
        )
        if emp_id and report.delivered:
            # A sent message is, by definition, contact made.
            track = repo.tracking_for(uid).get(emp_id)
            if not track or track["stage"] in {"scouted", "researched"}:
                repo.upsert_tracking(uid, emp_id, stage="contacted")
            if contact:
                repo.upsert_tracking(uid, emp_id, contact_name=contact[:120])
            repo.upsert_tracking(uid, emp_id, contact_email=to_addr.strip()[:254])

        log_audit(uid, "email_send", f"{to_addr} · {report.summary()}")
        tone = "ok" if report.delivered and not report.failed else ("err" if report.failed else "warn")
        extra = (" " + " ".join(report.messages)) if report.messages else ""
        return (
            ui.alert(report.summary().capitalize() + "." + extra, tone),
            _log_table(uid),
            charts.email_timeline(repo.email_activity(uid, 30), bool(dark)),
        )

    # ---- save template -----------------------------------------------------
    @app.callback(
        Output("out-flash", "children", allow_duplicate=True),
        Output("out-template", "options"),
        Input("out-save-tpl", "n_clicks"),
        State("out-subject", "value"),
        State("out-body", "value"),
        prevent_initial_call=True,
    )
    def _save_template(clicks, subject, body):
        if not clicks:
            return no_update, no_update
        uid = int(current_user.uid)
        if not (subject or "").strip() or not (body or "").strip():
            return ui.alert("Write a subject and a body before saving a template.", "warn"), no_update
        name = " ".join((subject or "").split())[:60] or "Untitled"
        repo.save_template(uid, name, subject, body)
        options = [
            {"label": t["name"] + ("" if t["user_id"] else " (shared)"), "value": t["id"]}
            for t in repo.templates_for(uid)
        ]
        return ui.alert(f"Saved as a template: “{name}”.", "ok"), options

    # ---- AI ----------------------------------------------------------------
    @app.callback(
        Output("out-ai-out", "children"),
        Output("out-subject", "value", allow_duplicate=True),
        Output("out-body", "value", allow_duplicate=True),
        Input("out-ai-draft", "n_clicks"),
        State("out-employer", "value"),
        State("out-goal", "value"),
        State("out-tone", "value"),
        State("out-lang", "value"),
        State("out-extra", "value"),
        State("out-sender", "value"),
        prevent_initial_call=True,
    )
    def _ai_draft(clicks, emp_id, goal, tone, language, extra, sender):
        if not clicks:
            return no_update, no_update, no_update
        if not emp_id:
            return ui.alert("Pick an employer first — the draft is built from its record.", "warn"), no_update, no_update
        emp = repo.employer(emp_id)
        if not emp:
            return ui.alert("That employer is no longer on file.", "err"), no_update, no_update

        result = ai.draft_email(
            int(current_user.uid),
            emp,
            sender_name=sender or getattr(current_user, "name", ""),
            goal=goal or GOALS[0]["value"],
            tone=tone or TONES[0]["value"],
            language=language or "English",
            extra=extra or "",
        )
        if not result.ok:
            return ui.alert(result.error, "err"), no_update, no_update
        note = ui.alert(
            f"Draft loaded into the composer · {result.input_tokens + result.output_tokens} tokens.",
            "ok",
        )
        return note, result.subject or no_update, result.text

    @app.callback(
        Output("out-ai-out", "children", allow_duplicate=True),
        Input("out-ai-brief", "n_clicks"),
        State("out-employer", "value"),
        prevent_initial_call=True,
    )
    def _ai_brief(clicks, emp_id):
        if not clicks:
            return no_update
        if not emp_id:
            return ui.alert("Pick an employer first.", "warn")
        emp = repo.employer(emp_id)
        if not emp:
            return ui.alert("That employer is no longer on file.", "err")
        result = ai.brief(int(current_user.uid), emp)
        if not result.ok:
            return ui.alert(result.error, "err")
        return ui.panel("Approach brief", emp["name"], html.Div(result.text, className="prose"))

    # ---- initial log paint -------------------------------------------------
    @app.callback(
        Output("out-log", "children"),
        Input("out-bump", "data"),
    )
    def _log(_bump):
        return _log_table(int(current_user.uid))
