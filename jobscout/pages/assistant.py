"""Assistant: ask Gemini about the directory, grounded in its real aggregates."""

from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, State, dcc, html, no_update
from flask_login import current_user

from config import settings
from jobscout import ai, repo, ui

SUGGESTIONS = [
    "Which three sectors should I work first, and why?",
    "Where is the biggest website gap worth pitching?",
    "Summarise what this directory is good for and what it cannot tell me.",
    "Draft a week of contact targets from these numbers.",
]


def layout(dark: bool = False) -> Any:
    uid = int(current_user.uid)
    breakdown = repo.sector_breakdown()
    metrics = repo.overview_metrics(uid)
    usage = repo.ai_usage(30)

    return html.Div(
        [
            dcc.Store(id="asst-history", data=[]),
            ui.masthead(
                "Assistant",
                "Ask the ledger",
                "a question.",
                "Gemini answers from the directory's own aggregates — the totals, the "
                "sector table, and the website gap. It is told not to invent facts "
                "about any employer, and to say which figure is missing when the data "
                "cannot answer you.",
            ),
            ui.alert(
                [html.Strong("Gemini: "), ai.status_note()],
                "" if ai.available() else "warn",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            ui.panel(
                                "Your question",
                                "Answered against live numbers, not a snapshot",
                                html.Div(
                                    [
                                        dcc.Textarea(
                                            id="asst-q",
                                            placeholder="e.g. Which sectors have the strongest reputations but the weakest web presence?",
                                            style={"minHeight": "110px"},
                                        ),
                                        html.Div(
                                            [
                                                html.Button(
                                                    "Ask",
                                                    id="asst-send",
                                                    className="btn primary",
                                                    n_clicks=0,
                                                    disabled=not ai.available(),
                                                ),
                                                html.Button("Clear", id="asst-clear", className="btn", n_clicks=0),
                                            ],
                                            className="btn-row",
                                            style={"marginTop": "12px"},
                                        ),
                                        html.Div(
                                            [
                                                html.Div("Try one of these", className="lbl",
                                                         style={"marginBottom": "8px"}),
                                                html.Div(
                                                    [
                                                        html.Button(
                                                            q,
                                                            id={"type": "asst-sugg", "i": i},
                                                            className="btn small",
                                                            n_clicks=0,
                                                        )
                                                        for i, q in enumerate(SUGGESTIONS)
                                                    ],
                                                    className="btn-row",
                                                ),
                                            ],
                                            style={"marginTop": "22px"},
                                        ),
                                    ]
                                ),
                            ),
                            dcc.Loading(
                                html.Div(id="asst-answers", style={"marginTop": "20px"}),
                                type="default",
                                color="#a4491f",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            ui.panel(
                                "What Gemini is given",
                                "The exact context behind every answer",
                                ui.kv_table(
                                    [
                                        ("Employers on file", ui.fmt_int(metrics["employers"])),
                                        ("Sectors", ui.fmt_int(metrics["sectors"])),
                                        ("No website on file", ui.fmt_int(metrics["no_site"])),
                                        ("Average rating", f"{metrics['avg_rating']:.2f}"),
                                        ("Reviews counted", ui.fmt_compact(metrics["reviews"])),
                                        ("Sector rows passed", ui.fmt_int(min(12, len(breakdown)))),
                                        ("Model", settings.AI_MODEL),
                                        ("Effort", settings.AI_EFFORT),
                                    ]
                                ),
                            ),
                            ui.panel(
                                "Usage, last 30 days",
                                "Across every account on this instance",
                                ui.kv_table(
                                    [
                                        ("Calls", ui.fmt_int(usage["runs"])),
                                        ("Input tokens", ui.fmt_compact(usage["input_tokens"])),
                                        ("Output tokens", ui.fmt_compact(usage["output_tokens"])),
                                        ("Failed calls", ui.fmt_int(usage["failures"])),
                                    ]
                                ),
                            ),
                            ui.panel(
                                "What it will not do",
                                "",
                                html.Div(
                                    [
                                        html.P(
                                            "It has no access to any individual employer's record on "
                                            "this page — only the aggregates listed above. For a "
                                            "single-employer brief, open that record in the directory "
                                            "and use the contact page.",
                                            style={"margin": "0 0 10px"},
                                        ),
                                        html.P(
                                            "It cannot browse the web and will not guess at a "
                                            "contact's name or email.",
                                            style={"margin": "0"},
                                        ),
                                    ]
                                ),
                            ),
                        ],
                        className="stack",
                    ),
                ],
                className="grid-2",
            ),
        ]
    )


def _exchange(question: str, answer: Any, tone: str = "") -> Any:
    return html.Div(
        [
            html.Div(question, className="lbl", style={"marginBottom": "8px"}),
            html.Div(answer, className="prose") if not tone else ui.alert(answer, tone),
        ],
        className="panel",
        style={"marginBottom": "16px", "borderLeft": "2px solid var(--rust)"},
    )


def register(app: dash.Dash) -> None:
    @app.callback(
        Output("asst-answers", "children"),
        Output("asst-history", "data"),
        Output("asst-q", "value"),
        Input("asst-send", "n_clicks"),
        Input("asst-clear", "n_clicks"),
        State("asst-q", "value"),
        State("asst-history", "data"),
        prevent_initial_call=True,
    )
    def _ask(send_clicks, clear_clicks, question, history):
        from dash import callback_context

        trigger = callback_context.triggered_id
        history = history or []

        if trigger == "asst-clear":
            return [], [], ""
        if trigger != "asst-send" or not send_clicks:
            return no_update, no_update, no_update

        question = (question or "").strip()
        if not question:
            return (
                [_exchange("", "Type a question first.", "warn"), *_render(history)],
                history,
                no_update,
            )
        if len(question) > 2000:
            question = question[:2000]

        result = ai.ask(int(current_user.uid), question)
        entry = {"q": question, "a": result.text, "ok": result.ok}
        history = [entry, *history][:12]
        return _render(history), history, ""

    def _render(history: list[dict[str, Any]]) -> list[Any]:
        return [
            _exchange(item["q"], item["a"], "" if item.get("ok") else "err")
            for item in history
            if item.get("q")
        ]

    @app.callback(
        Output("asst-q", "value", allow_duplicate=True),
        Input({"type": "asst-sugg", "i": dash.ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _suggest(clicks):
        from dash import callback_context

        trigger = callback_context.triggered_id
        if not isinstance(trigger, dict) or not ui.any_clicks(clicks):
            return no_update
        index = int(trigger.get("i", 0))
        if 0 <= index < len(SUGGESTIONS):
            return SUGGESTIONS[index]
        return no_update
