"""Admin panel: accounts, platform health, data maintenance, audit trail.

Every write here re-checks ``current_user.is_admin`` server-side. Hiding the nav
link is cosmetic; the check in each callback is the control.
"""

from __future__ import annotations

import secrets
from typing import Any

import dash
from dash import ALL, Input, Output, State, callback_context, dcc, html, no_update
from flask_login import current_user
from werkzeug.security import generate_password_hash

from config import settings
from jobscout import ai, charts, db, mailer, repo, ui


def _is_admin() -> bool:
    return bool(getattr(current_user, "is_admin", False))


def layout(dark: bool = False) -> Any:
    if not _is_admin():
        return ui.panel("Restricted", "", ui.empty("The admin panel is for administrators."))

    stats = repo.platform_stats()
    usage = repo.ai_usage(30)

    return html.Div(
        [
            dcc.Store(id="adm-bump", data=0),
            dcc.Store(id="adm-dark", data=dark),
            ui.masthead(
                "Administration",
                "The instance,",
                "from the inside.",
                "Accounts, data, delivery and the audit trail. Every action on this page "
                "is recorded with the account that performed it.",
                folio="Admin",
                folio_sub=f"{stats.get('users', 0)} accounts",
            ),
            ui.stat_strip(
                [
                    ("Accounts", ui.fmt_int(stats.get("users", 0)), "",
                     f"{stats.get('users_active', 0)} active"),
                    ("Employers", ui.fmt_int(stats.get("employers", 0)), "",
                     f"{stats.get('no_site', 0)} without a site"),
                    ("Messages logged", ui.fmt_int(stats.get("emails", 0)), "rust",
                     f"{stats.get('emails_failed', 0)} failed"),
                    ("AI calls", ui.fmt_int(stats.get("ai_runs", 0)), "moss",
                     f"{usage['failures']} failed in 30d"),
                ]
            ),
            html.Div(id="adm-flash"),
            # ---- accounts ----------------------------------------------------
            html.Div(
                [
                    ui.section_head("Accounts"),
                    html.Div(id="adm-users", className="fade-up"),
                    html.Div(
                        ui.panel(
                            "Create an account",
                            "The new account receives the password you type here",
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            ui.field("Name", dcc.Input(id="adm-new-name", type="text")),
                                            ui.field("Email", dcc.Input(id="adm-new-email", type="email")),
                                        ],
                                        className="field-row",
                                    ),
                                    html.Div(
                                        [
                                            ui.field(
                                                "Password",
                                                dcc.Input(id="adm-new-pass", type="text",
                                                          placeholder="At least 10 characters"),
                                                "Shown in plain text so you can pass it on. "
                                                "Tell the holder to change it.",
                                            ),
                                            ui.field(
                                                "Role",
                                                dcc.Dropdown(
                                                    id="adm-new-role",
                                                    options=[
                                                        {"label": "Scout", "value": "scout"},
                                                        {"label": "Administrator", "value": "admin"},
                                                    ],
                                                    value="scout",
                                                    clearable=False,
                                                ),
                                            ),
                                        ],
                                        className="field-row",
                                    ),
                                    html.Div(
                                        [
                                            html.Button("Create account", id="adm-create",
                                                        className="btn primary", n_clicks=0),
                                            html.Button("Suggest a password", id="adm-suggest",
                                                        className="btn", n_clicks=0),
                                        ],
                                        className="btn-row",
                                    ),
                                ]
                            ),
                        ),
                        style={"marginTop": "20px"},
                    ),
                ],
                className="section",
            ),
            # ---- health ------------------------------------------------------
            html.Div(
                [
                    ui.section_head("Health and configuration"),
                    html.Div(
                        [
                            ui.panel(
                                "Delivery",
                                mailer.status_note(),
                                html.Div(
                                    [
                                        ui.kv_table(
                                            [
                                                ("Dry run", "ON" if settings.MAIL_DRY_RUN else "OFF"),
                                                ("SMTP host", settings.SMTP_HOST or "— not set"),
                                                ("SMTP port", settings.SMTP_PORT),
                                                ("STARTTLS", "yes" if settings.SMTP_STARTTLS else "no"),
                                                ("Implicit SSL", "yes" if settings.SMTP_SSL else "no"),
                                                ("From", settings.MAIL_FROM or "— not set"),
                                                ("Daily cap per account", settings.MAIL_DAILY_CAP),
                                            ]
                                        ),
                                        html.Div(
                                            [
                                                ui.field(
                                                    "Send a test message to",
                                                    dcc.Input(id="adm-test-to", type="email",
                                                              placeholder="you@example.com"),
                                                ),
                                                html.Button("Send test", id="adm-test-send",
                                                            className="btn", n_clicks=0),
                                            ],
                                            style={"marginTop": "18px"},
                                        ),
                                        html.Div(id="adm-test-out", style={"marginTop": "12px"}),
                                    ]
                                ),
                            ),
                            ui.panel(
                                "AI",
                                ai.status_note(),
                                html.Div(
                                    [
                                        ui.kv_table(
                                            [
                                                ("Model", settings.AI_MODEL),
                                                ("Effort", settings.AI_EFFORT),
                                                ("Max output tokens", settings.AI_MAX_TOKENS),
                                                ("Calls, 30 days", ui.fmt_int(usage["runs"])),
                                                ("Input tokens, 30 days", ui.fmt_compact(usage["input_tokens"])),
                                                ("Output tokens, 30 days", ui.fmt_compact(usage["output_tokens"])),
                                            ]
                                        ),
                                        ui.graph(charts.ai_usage_bar(repo.ai_runs_by_kind(30), dark)),
                                    ]
                                ),
                            ),
                        ],
                        className="grid-2-even",
                    ),
                    html.Div(
                        [
                            ui.panel(
                                "Scoring weights",
                                "Read from the environment at boot. Change them there, then re-score.",
                                html.Div(
                                    [
                                        ui.kv_table(
                                            [
                                                ("Rating (JOBSCOUT_W_RATING)", settings.W_RATING),
                                                ("Reviews (JOBSCOUT_W_REVIEWS)", settings.W_REVIEWS),
                                                ("Website gap (JOBSCOUT_W_GAP)", settings.W_GAP),
                                                ("Reachability (JOBSCOUT_W_REACH)", settings.W_REACH),
                                            ]
                                        ),
                                        html.Div(
                                            [
                                                html.Button("Re-score every employer", id="adm-rescore",
                                                            className="btn", n_clicks=0),
                                                html.Button("Re-import the seed file", id="adm-reseed",
                                                            className="btn", n_clicks=0),
                                            ],
                                            className="btn-row",
                                            style={"marginTop": "18px"},
                                        ),
                                    ]
                                ),
                            ),
                            ui.panel(
                                "Signup",
                                "Who can create an account on this instance",
                                ui.kv_table(
                                    [
                                        ("Open signup", "ON" if settings.ALLOW_SIGNUP else "OFF"),
                                        ("Invite code required", "yes" if settings.SIGNUP_INVITE_CODE else "no"),
                                        ("Secure cookies", "yes" if settings.SESSION_COOKIE_SECURE else "no"),
                                        ("Session lifetime", f"{settings.PERMANENT_SESSION_LIFETIME_DAYS} days"),
                                        ("Database", str(settings.DB_PATH)),
                                    ]
                                ),
                            ),
                        ],
                        className="grid-2-even",
                        style={"marginTop": "20px"},
                    ),
                ],
                className="section",
            ),
            # ---- audit -------------------------------------------------------
            html.Div(
                [
                    ui.section_head("Audit trail", "60 most recent events"),
                    html.Div(id="adm-audit", className="fade-up"),
                ],
                className="section",
            ),
        ]
    )


def _user_table() -> Any:
    users = repo.all_users()
    rows = []
    me = int(getattr(current_user, "uid", 0))
    for u in users:
        is_me = u["id"] == me
        rows.append(
            html.Tr(
                [
                    html.Td(
                        [
                            html.Span(u["role"].title(), className="cat-tag"),
                            html.Span(u["name"] or "—"),
                        ],
                        className="td-name",
                    ),
                    html.Td(html.Span(u["email"], className="mono", style={"fontSize": "12px"})),
                    html.Td(ui.badge("Active", "moss") if u["is_active"] else ui.badge("Suspended", "danger")),
                    html.Td(ui.fmt_int(u["tracked"]), className="num"),
                    html.Td(ui.fmt_int(u["emails_sent"]), className="num"),
                    html.Td(
                        (u["last_login_at"] or "—")[:16].replace("T", " "),
                        style={"fontSize": "12px", "color": "var(--ink-faint)"},
                    ),
                    html.Td(
                        html.Div(
                            [
                                html.Button(
                                    "Make scout" if u["role"] == "admin" else "Make admin",
                                    id={"type": "adm-role", "id": u["id"]},
                                    className="btn small",
                                    n_clicks=0,
                                    disabled=is_me,
                                ),
                                html.Button(
                                    "Reinstate" if not u["is_active"] else "Suspend",
                                    id={"type": "adm-active", "id": u["id"]},
                                    className="btn small",
                                    n_clicks=0,
                                    disabled=is_me,
                                ),
                                html.Button(
                                    "Reset password",
                                    id={"type": "adm-reset", "id": u["id"]},
                                    className="btn small",
                                    n_clicks=0,
                                ),
                                html.Button(
                                    "Delete",
                                    id={"type": "adm-delete", "id": u["id"]},
                                    className="btn small danger",
                                    n_clicks=0,
                                    disabled=is_me,
                                ),
                            ],
                            className="btn-row",
                        )
                    ),
                ],
                className="main-row",
            )
        )

    return html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Account"),
                            html.Th("Email"),
                            html.Th("Status"),
                            html.Th("Tracked"),
                            html.Th("Sent"),
                            html.Th("Last seen"),
                            html.Th("Actions"),
                        ]
                    )
                ),
                html.Tbody(rows),
            ],
            className="ledger",
            style={"minWidth": "980px"},
        ),
        className="ledger-table-wrap",
    )


def _audit_table() -> Any:
    events = repo.recent_audit(60)
    if not events:
        return html.Div(ui.empty("Nothing recorded yet."), className="panel")
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span(e["action"], className="mono",
                                              style={"fontSize": "12px", "color": "var(--rust)"}),
                                    html.Span("  " + (e["detail"] or ""),
                                              style={"fontSize": "12.5px"}),
                                ],
                                className="region-name",
                            ),
                            html.Div(
                                f"{e['email'] or 'system'} · {e['created_at'][:19].replace('T', ' ')}",
                                className="region-meta",
                            ),
                        ]
                    )
                ],
                className="region-row",
            )
            for e in events
        ],
        className="region-list panel",
    )


def register(app: dash.Dash) -> None:
    @app.callback(
        Output("adm-users", "children"),
        Output("adm-audit", "children"),
        Input("adm-bump", "data"),
    )
    def _tables(_bump):
        if not _is_admin():
            return ui.empty("Restricted."), ui.empty("Restricted.")
        return _user_table(), _audit_table()

    # ---- create ------------------------------------------------------------
    @app.callback(
        Output("adm-flash", "children", allow_duplicate=True),
        Output("adm-bump", "data", allow_duplicate=True),
        Output("adm-new-name", "value"),
        Output("adm-new-email", "value"),
        Input("adm-create", "n_clicks"),
        State("adm-new-name", "value"),
        State("adm-new-email", "value"),
        State("adm-new-pass", "value"),
        State("adm-new-role", "value"),
        State("adm-bump", "data"),
        prevent_initial_call=True,
    )
    def _create(clicks, name, email, password, role, bump):
        if not clicks or not _is_admin():
            return no_update, no_update, no_update, no_update
        name = (name or "").strip()
        email = (email or "").strip().lower()
        password = password or ""
        role = role if role in {"scout", "admin"} else "scout"

        if len(name) < 2:
            return ui.alert("Give the account a name.", "err"), no_update, no_update, no_update
        if "@" not in email or "." not in email.split("@")[-1]:
            return ui.alert("That is not a valid email address.", "err"), no_update, no_update, no_update
        if len(password) < 10:
            return ui.alert("The password needs at least 10 characters.", "err"), no_update, no_update, no_update
        if repo.user_by_email(email):
            return ui.alert("An account already exists for that address.", "err"), no_update, no_update, no_update

        uid = repo.create_user(email, name, generate_password_hash(password), role)
        db.log_audit(int(current_user.uid), "admin_create_user", f"{email} role={role} id={uid}")
        return (
            ui.alert(f"Created {email} as {role}.", "ok"),
            int(bump or 0) + 1,
            "",
            "",
        )

    @app.callback(
        Output("adm-new-pass", "value"),
        Input("adm-suggest", "n_clicks"),
        prevent_initial_call=True,
    )
    def _suggest(clicks):
        if not clicks or not _is_admin():
            return no_update
        return secrets.token_urlsafe(12)

    # ---- per-user actions --------------------------------------------------
    @app.callback(
        Output("adm-flash", "children", allow_duplicate=True),
        Output("adm-bump", "data", allow_duplicate=True),
        Input({"type": "adm-role", "id": ALL}, "n_clicks"),
        Input({"type": "adm-active", "id": ALL}, "n_clicks"),
        Input({"type": "adm-reset", "id": ALL}, "n_clicks"),
        Input({"type": "adm-delete", "id": ALL}, "n_clicks"),
        State("adm-bump", "data"),
        prevent_initial_call=True,
    )
    def _user_action(_r, _a, _p, _d, bump):
        trigger = callback_context.triggered_id
        if not isinstance(trigger, dict) or not _is_admin():
            return no_update, no_update
        # Guard against the fan-out firing with every n_clicks still None.
        if not any(ui.any_clicks(ev.get("value")) for ev in callback_context.triggered):
            return no_update, no_update

        kind = trigger["type"]
        target_id = int(trigger["id"])
        me = int(current_user.uid)
        target = repo.user_by_id(target_id)
        if not target:
            return ui.alert("That account no longer exists.", "err"), int(bump or 0) + 1

        if target_id == me and kind in {"adm-role", "adm-active", "adm-delete"}:
            return ui.alert("You cannot change your own role or access.", "warn"), no_update

        bumped = int(bump or 0) + 1

        if kind == "adm-role":
            new_role = "scout" if target["role"] == "admin" else "admin"
            if new_role == "scout" and repo.admin_count() <= 1:
                return ui.alert("This is the last administrator — promote someone else first.", "warn"), no_update
            repo.set_user_role(target_id, new_role)
            db.log_audit(me, "admin_set_role", f"{target['email']} -> {new_role}")
            return ui.alert(f"{target['email']} is now a {new_role}.", "ok"), bumped

        if kind == "adm-active":
            new_state = not bool(target["is_active"])
            if not new_state and target["role"] == "admin" and repo.admin_count() <= 1:
                return ui.alert("This is the last active administrator.", "warn"), no_update
            repo.set_user_active(target_id, new_state)
            db.log_audit(me, "admin_set_active", f"{target['email']} active={new_state}")
            return (
                ui.alert(
                    f"{target['email']} is {'active again' if new_state else 'suspended'}.", "ok"
                ),
                bumped,
            )

        if kind == "adm-reset":
            new_password = secrets.token_urlsafe(12)
            repo.set_user_password(target_id, generate_password_hash(new_password))
            db.log_audit(me, "admin_reset_password", target["email"])
            return (
                ui.alert(
                    [
                        f"New password for {target['email']}: ",
                        html.Span(new_password, className="mono",
                                  style={"background": "var(--paper)", "padding": "2px 6px"}),
                        ". It is shown once — pass it on now.",
                    ],
                    "warn",
                ),
                bumped,
            )

        if kind == "adm-delete":
            if target["role"] == "admin" and repo.admin_count() <= 1:
                return ui.alert("This is the last administrator.", "warn"), no_update
            repo.delete_user(target_id)
            db.log_audit(me, "admin_delete_user", target["email"])
            return (
                ui.alert(
                    f"Deleted {target['email']} along with their tracking board and mail log.", "ok"
                ),
                bumped,
            )

        return no_update, no_update

    # ---- data maintenance --------------------------------------------------
    @app.callback(
        Output("adm-flash", "children", allow_duplicate=True),
        Output("adm-bump", "data", allow_duplicate=True),
        Input("adm-rescore", "n_clicks"),
        Input("adm-reseed", "n_clicks"),
        State("adm-bump", "data"),
        prevent_initial_call=True,
    )
    def _maintenance(_rescore, _reseed, bump):
        trigger = callback_context.triggered_id
        if not _is_admin() or trigger not in {"adm-rescore", "adm-reseed"}:
            return no_update, no_update
        me = int(current_user.uid)

        if trigger == "adm-rescore":
            n = db.rescore_all()
            repo.invalidate_cache()
            db.log_audit(me, "admin_rescore", f"{n} rows")
            return ui.alert(f"Re-scored {n} employers with the current weights.", "ok"), int(bump or 0) + 1

        n = db.seed_employers(force=True)
        repo.invalidate_cache()
        db.log_audit(me, "admin_reseed", f"{n} rows")
        if not n:
            return ui.alert("No seed file found at data/employers.json.", "warn"), no_update
        return ui.alert(f"Re-imported {n} employers from the seed file.", "ok"), int(bump or 0) + 1

    # ---- test mail ---------------------------------------------------------
    @app.callback(
        Output("adm-test-out", "children"),
        Input("adm-test-send", "n_clicks"),
        State("adm-test-to", "value"),
        prevent_initial_call=True,
    )
    def _test_mail(clicks, to_addr):
        if not clicks or not _is_admin():
            return no_update
        if not mailer.valid_email(to_addr or ""):
            return ui.alert("Enter a valid address first.", "err")
        report = mailer.send_test(int(current_user.uid), to_addr.strip())
        db.log_audit(int(current_user.uid), "admin_test_mail", f"{to_addr} · {report.summary()}")
        tone = "ok" if report.sent else ("warn" if report.simulated else "err")
        detail = (" " + " ".join(report.messages)) if report.messages else ""
        return ui.alert(report.summary().capitalize() + "." + detail, tone)
