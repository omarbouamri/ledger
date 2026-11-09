"""Reusable layout pieces, so every page is built from the same vocabulary."""

from __future__ import annotations

from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

from dash import dcc, html

from jobscout.scoring import band_label, score_band

SUN_PATHS = [
    {"cx": "12", "cy": "12", "r": "4"},
]


def masthead(
    eyebrow: str,
    title_lead: str,
    title_em: str,
    blurb: str,
    folio: str = "",
    folio_sub: str = "",
) -> html.Div:
    right: list[Any] = []
    if folio:
        right.append(
            html.Div(
                [
                    html.Div(folio, className="folio-num"),
                    html.Div(folio_sub, className="folio-date"),
                ],
                className="folio",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(eyebrow, className="eyebrow"),
                    html.H1([title_lead, html.Br(), html.Em(title_em)]),
                    html.P(blurb),
                ]
            ),
            *right,
        ],
        className="masthead fade-up",
    )


def stat_strip(cells: Sequence[tuple[str, Any, str, str]]) -> html.Div:
    """``cells`` is a sequence of (label, value, accent, footnote)."""
    return html.Div(
        [
            html.Div(
                [
                    html.Div(label, className="k"),
                    html.Div(str(value), className=f"v num {accent}".strip()),
                    html.Div(foot, className="foot") if foot else None,
                ],
                className="stat-cell",
            )
            for label, value, accent, foot in cells
        ],
        className="stat-strip fade-up",
    )


def panel(title: str, sub: str = "", children: Any = None, **kwargs: Any) -> html.Div:
    inner: list[Any] = []
    if title:
        inner.append(html.H3(title))
    if sub:
        inner.append(html.Div(sub, className="sub"))
    if children is not None:
        inner.append(children if not isinstance(children, list) else html.Div(children))
    kwargs.setdefault("className", "panel")
    return html.Div(inner, **kwargs)


def section_head(title: str, count_text: str = "", extra: Any = None) -> html.Div:
    return html.Div(
        [
            html.Div(html.H2(title)),
            html.Div(count_text, className="count num") if count_text else None,
            extra,
        ],
        className="section-head",
    )


def score_chip(score: int) -> html.Span:
    return html.Span(
        str(score),
        className=f"score-chip {score_band(score)} num",
        title=band_label(score),
    )


def site_flag(has_website: bool) -> html.Span:
    return html.Span(
        "On file" if has_website else "None found",
        className=f"site-flag {'yes' if has_website else 'no'}",
    )


def badge(text: str, tone: str = "") -> html.Span:
    return html.Span(text, className=f"badge {tone}".strip())


def alert(text: Any, tone: str = "") -> html.Div:
    return html.Div(text, className=f"alert {tone}".strip())


def field(label: str, control: Any, hint: str = "") -> html.Div:
    return html.Div(
        [
            html.Label(label),
            control,
            html.Div(hint, className="hint") if hint else None,
        ],
        className="field",
    )


def graph(fig: Any, **kwargs: Any) -> dcc.Graph:
    """A figure in a box that already knows how tall it is.

    Plotly only sizes its container once its JavaScript has run. Until then an
    unstyled ``dcc.Graph`` is zero pixels high, so the panel around it collapses
    and the chart paints over whatever sits below — which is what made the
    panels in a ``.stack`` column overlap. Reading the height off the figure and
    putting it on the element reserves the space up front, so the column heights
    are right on the very first paint and nothing jumps when Plotly takes over.
    """
    from jobscout.charts import GRAPH_CONFIG

    kwargs.setdefault("config", GRAPH_CONFIG)
    style = dict(kwargs.pop("style", None) or {})
    height = getattr(getattr(fig, "layout", None), "height", None)
    if height and "height" not in style:
        style["height"] = f"{int(height)}px"
    style.setdefault("width", "100%")
    return dcc.Graph(figure=fig, style=style, **kwargs)


def kv_table(rows: Iterable[tuple[str, Any]]) -> html.Table:
    return html.Table(
        html.Tbody([html.Tr([html.Td(k), html.Td(str(v))]) for k, v in rows]),
        className="kv-table",
    )


def detail_line(label: str, value: Any) -> html.Div:
    return html.Div([html.Span(label, className="l"), html.Span(value)], className="detail-row-line")


def empty(text: str) -> html.Div:
    return html.Div(text, className="empty-note")


def link_btn(text: str, href: str, primary: bool = False) -> html.A:
    return html.A(
        text,
        href=href,
        target="_blank",
        rel="noopener noreferrer",
        className="btn primary" if primary else "btn",
    )


def safe_url(raw: str | None) -> str:
    """Return an http(s) URL, or "" for anything else.

    A bare host such as ``example.com`` is upgraded to https. Anything that
    already carries a scheme must be http or https, so ``javascript:``,
    ``data:`` and friends are rejected rather than silently prefixed.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if any(ch in raw for ch in ('"', "'", "<", ">", "\n", "\r", "\t", " ", "\\")):
        return ""

    parts = urlsplit(raw)
    if not parts.scheme:
        # Only a scheme-less value may be upgraded, and only if what precedes
        # the first slash looks like a host rather than "scheme:something".
        head = raw.split("/", 1)[0]
        if ":" in head and not head.rsplit(":", 1)[-1].isdigit():
            return ""
        parts = urlsplit("https://" + raw)

    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit(parts)


def whatsapp_url(phone: str | None) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "212" + digits[1:]
    return "https://wa.me/" + digits


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def fmt_compact(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n)}"


def any_clicks(clicks: Any) -> bool:
    """True if a pattern-matching ``n_clicks`` fan-out carries a real click.

    Dash hands a list for an ``ALL`` input, but a single-match pattern can
    arrive as a bare value, so accept either shape rather than assuming.
    """
    if clicks is None:
        return False
    if isinstance(clicks, (list, tuple)):
        return any(bool(c) for c in clicks)
    return bool(clicks)


def first_value(values: Any) -> Any:
    """The single value behind a pattern-matching input, list-wrapped or not."""
    if isinstance(values, (list, tuple)):
        return values[0] if values else None
    return values
