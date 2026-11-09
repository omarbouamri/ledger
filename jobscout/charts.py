"""Plotly figures.

Colour decisions
----------------
Every palette below was checked with the dataviz validator (lightness band,
chroma floor, CVD separation, normal-vision floor, contrast against the chart
surface) in both modes — not eyeballed.

* Categorical, light: #b14a10 / #0069a8 / #a8297f  — all six checks pass
* Categorical, dark:  #d2702f / #2f8fd6 / #cf4f93  — all six checks pass
* One-series charts use a single brand hue with direct value labels; bar length
  already carries the magnitude, so a second encoding would be noise.
* Ordered stages (the tracking board) use a sequential single-hue ramp, light to dark.
* Email status uses the reserved status palette (good / warning / critical) and
  always ships with a labelled legend, never colour alone.

Dark mode is a *selected* set of steps against the dark surface, not a flip of
the light one.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go

from jobscout.db import STAGE_LABELS, STAGES

# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
LIGHT = {
    "surface": "#fbf8f1",
    "ink": "#2b2620",
    "ink_soft": "#675f52",
    "ink_faint": "#9a8f7d",
    "rule": "#ddd2ba",
    "brand": "#b14a10",
    "cat": ("#b14a10", "#0069a8", "#a8297f"),
    "seq": ("#f0ddc9", "#e0b494", "#cf8a5f", "#b96233", "#9c4a19", "#7e3616"),
    "good": "#4c6b3f",
    "warning": "#a98100",
    "critical": "#a3352b",
}
DARK = {
    "surface": "#2a251e",
    "ink": "#ece3d3",
    "ink_soft": "#b5a891",
    "ink_faint": "#85795f",
    "rule": "#3c342a",
    "brand": "#d2702f",
    "cat": ("#d2702f", "#2f8fd6", "#cf4f93"),
    "seq": ("#4a3524", "#64452c", "#855634", "#a76a3c", "#c48047", "#e0a070"),
    "good": "#9bbd85",
    "warning": "#d9ac4b",
    "critical": "#e1786c",
}

FONT_SANS = '"Source Sans 3", system-ui, sans-serif'
FONT_SERIF = '"Fraunces", Georgia, serif'


def tokens(dark: bool) -> dict[str, Any]:
    return DARK if dark else LIGHT


def _base(dark: bool, height: int, *, legend: bool = False) -> go.Figure:
    t = tokens(dark)
    fig = go.Figure()
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=16, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_SANS, size=12.5, color=t["ink_soft"]),
        hoverlabel=dict(
            bgcolor=t["surface"],
            bordercolor=t["rule"],
            font=dict(family=FONT_SANS, size=12.5, color=t["ink"]),
        ),
        showlegend=legend,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            font=dict(size=12, color=t["ink_soft"]),
            bgcolor="rgba(0,0,0,0)",
        ),
        dragmode=False,
        separators=". ",
    )
    axis = dict(
        showgrid=False,
        zeroline=False,
        linecolor=t["rule"],
        tickfont=dict(size=11.5, color=t["ink_faint"]),
        title=None,
        automargin=True,
    )
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def _ramp(seq: Sequence[str], n: int) -> list[str]:
    """Spread a sequential ramp over n ordered slots."""
    if n <= 0:
        return []
    if n == 1:
        return [seq[-2]]
    last = len(seq) - 1
    return [seq[round(i * last / (n - 1))] for i in range(n)]


def empty_note(dark: bool, text: str, height: int = 220) -> go.Figure:
    t = tokens(dark)
    fig = _base(dark, height)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.add_annotation(
        text=text,
        showarrow=False,
        font=dict(family=FONT_SERIF, size=14, color=t["ink_faint"]),
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
    )
    return fig


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
def sector_bar(breakdown: pd.DataFrame, dark: bool, top: int = 10) -> go.Figure:
    """Employers per sector. One series: brand hue + direct value labels."""
    if breakdown.empty:
        return empty_note(dark, "No employers on file yet.")
    t = tokens(dark)
    d = breakdown.nlargest(top, "total").iloc[::-1]
    fig = _base(dark, max(240, 34 * len(d)))
    fig.add_trace(
        go.Bar(
            y=d["sector"],
            x=d["total"],
            orientation="h",
            marker=dict(color=t["brand"], line=dict(width=0)),
            width=0.58,
            text=d["total"],
            textposition="outside",
            textfont=dict(size=11.5, color=t["ink_faint"]),
            cliponaxis=False,
            customdata=d[["no_site", "avg_rating"]].to_numpy(),
            hovertemplate=(
                "<b>%{y}</b><br>%{x} employers<br>"
                "%{customdata[0]} with no website<br>"
                "mean rating %{customdata[1]}<extra></extra>"
            ),
        )
    )
    fig.update_xaxes(visible=False, range=[0, float(d["total"].max()) * 1.16])
    fig.update_yaxes(linecolor="rgba(0,0,0,0)", tickfont=dict(size=12, color=t["ink"]))
    return fig


def gap_bar(breakdown: pd.DataFrame, dark: bool, top: int = 8, min_total: int = 4) -> go.Figure:
    """Share of each sector with no website on file."""
    if breakdown.empty:
        return empty_note(dark, "No employers on file yet.")
    t = tokens(dark)
    d = breakdown[breakdown["total"] >= min_total].nlargest(top, "gap_pct").iloc[::-1]
    if d.empty:
        return empty_note(dark, "Not enough rows in any one sector yet.")
    fig = _base(dark, max(230, 34 * len(d)))
    fig.add_trace(
        go.Bar(
            y=d["sector"],
            x=d["gap_pct"],
            orientation="h",
            marker=dict(color=t["brand"], line=dict(width=0)),
            width=0.58,
            text=[f"{v:.0f}%" for v in d["gap_pct"]],
            textposition="outside",
            textfont=dict(size=11.5, color=t["ink_faint"]),
            cliponaxis=False,
            customdata=d[["no_site", "total"]].to_numpy(),
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata[0]} of %{customdata[1]} have no "
                "website<extra></extra>"
            ),
        )
    )
    fig.update_xaxes(visible=False, range=[0, 112])
    fig.update_yaxes(linecolor="rgba(0,0,0,0)", tickfont=dict(size=12, color=t["ink"]))
    return fig


def score_distribution(df: pd.DataFrame, dark: bool) -> go.Figure:
    """How many employers sit at each 0-9 opportunity score."""
    if df.empty:
        return empty_note(dark, "No employers on file yet.")
    t = tokens(dark)
    counts = df["score"].value_counts().reindex(range(10), fill_value=0).sort_index()
    fig = _base(dark, 240)
    fig.add_trace(
        go.Bar(
            x=counts.index.astype(str),
            y=counts.to_numpy(),
            marker=dict(color=t["brand"], line=dict(width=0)),
            width=0.62,
            text=[v if v else "" for v in counts.to_numpy()],
            textposition="outside",
            textfont=dict(size=11, color=t["ink_faint"]),
            cliponaxis=False,
            hovertemplate="Score %{x}<br>%{y} employers<extra></extra>",
        )
    )
    fig.update_yaxes(visible=False, range=[0, float(counts.max()) * 1.2])
    fig.update_xaxes(tickfont=dict(size=12, color=t["ink"]), title=None)
    return fig


def reputation_scatter(df: pd.DataFrame, dark: bool) -> go.Figure:
    """Rating against review volume, split by whether a website is on file.

    Two categories, so categorical slots 1 and 2 with a labelled legend.
    """
    if df.empty:
        return empty_note(dark, "No employers on file yet.")
    t = tokens(dark)
    rated = df[df["rating"].notna() & (df["reviews"] > 0)]
    if rated.empty:
        return empty_note(dark, "No rated employers on file yet.")

    fig = _base(dark, 330, legend=True)
    groups = (
        ("No website on file", rated[~rated["has_website"]], t["cat"][0], "diamond"),
        ("Website on file", rated[rated["has_website"]], t["cat"][1], "circle"),
    )
    for label, sub, colour, symbol in groups:
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["reviews"],
                y=sub["rating"],
                mode="markers",
                name=label,
                marker=dict(
                    color=colour,
                    size=9,
                    symbol=symbol,  # shape backs up the colour
                    opacity=0.82,
                    line=dict(width=1.4, color=t["surface"]),
                ),
                customdata=sub[["name", "sector", "score"]].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                    "%{y} / 5 from %{x} reviews<br>score %{customdata[2]}<extra></extra>"
                ),
            )
        )
    fig.update_xaxes(
        type="log",
        title=dict(text="Reviews (log)", font=dict(size=11, color=t["ink_faint"])),
        showgrid=True,
        gridcolor=t["rule"],
        gridwidth=1,
    )
    fig.update_yaxes(
        title=dict(text="Public rating", font=dict(size=11, color=t["ink_faint"])),
        range=[2.4, 5.25],
        showgrid=True,
        gridcolor=t["rule"],
    )
    return fig


# --------------------------------------------------------------------------- #
# Tracking
# --------------------------------------------------------------------------- #
def stage_funnel(counts: Mapping[str, int], dark: bool) -> go.Figure:
    """Ordered stages, so a sequential ramp light -> dark."""
    t = tokens(dark)
    values = [int(counts.get(s, 0)) for s in STAGES]
    if not any(values):
        return empty_note(dark, "Nothing tracked yet — star an employer to begin.", 260)
    labels = [STAGE_LABELS[s] for s in STAGES]
    colours = _ramp(t["seq"], len(STAGES))

    fig = _base(dark, 300)
    fig.add_trace(
        go.Bar(
            y=labels[::-1],
            x=values[::-1],
            orientation="h",
            marker=dict(color=colours[::-1], line=dict(width=2, color=t["surface"])),
            width=0.66,
            text=[v if v else "" for v in values[::-1]],
            textposition="outside",
            textfont=dict(size=11.5, color=t["ink_faint"]),
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x} employers<extra></extra>",
        )
    )
    fig.update_xaxes(visible=False, range=[0, max(values) * 1.2 or 1])
    fig.update_yaxes(linecolor="rgba(0,0,0,0)", tickfont=dict(size=12.5, color=t["ink"]))
    return fig


# --------------------------------------------------------------------------- #
# Email + AI
# --------------------------------------------------------------------------- #
_STATUS_STYLE = {
    "sent": ("good", "Sent"),
    "simulated": ("warning", "Simulated"),
    "failed": ("critical", "Failed"),
    "invalid": ("critical", "Invalid address"),
    "queued": ("ink_faint", "Queued"),
}


def email_timeline(activity: pd.DataFrame, dark: bool) -> go.Figure:
    """Daily send counts per status, using the reserved status palette."""
    if activity.empty:
        return empty_note(dark, "No messages logged in the last 30 days.", 260)
    t = tokens(dark)
    pivot = (
        activity.pivot_table(index="day", columns="status", values="n", aggfunc="sum")
        .fillna(0)
        .sort_index()
    )
    full = pd.date_range(pivot.index.min(), pivot.index.max(), freq="D").strftime("%Y-%m-%d")
    pivot = pivot.reindex(full, fill_value=0)

    fig = _base(dark, 280, legend=True)
    for status in pivot.columns:
        token_key, label = _STATUS_STYLE.get(str(status), ("ink_faint", str(status).title()))
        fig.add_trace(
            go.Scatter(
                x=pivot.index,
                y=pivot[status],
                name=label,
                mode="lines+markers",
                line=dict(color=t[token_key], width=2, shape="spline", smoothing=0.4),
                marker=dict(size=7, color=t[token_key], line=dict(width=1.4, color=t["surface"])),
                hovertemplate="%{x}<br>" + label + ": %{y}<extra></extra>",
            )
        )
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(tickfont=dict(size=11, color=t["ink_faint"]))
    fig.update_yaxes(showgrid=True, gridcolor=t["rule"], rangemode="tozero")
    return fig


def ai_usage_bar(by_kind: pd.DataFrame, dark: bool) -> go.Figure:
    if by_kind.empty:
        return empty_note(dark, "No AI calls in the last 30 days.", 200)
    t = tokens(dark)
    d = by_kind.iloc[::-1]
    pretty = {"draft_email": "Email drafts", "brief": "Approach briefs", "ask": "Directory questions"}
    fig = _base(dark, max(180, 40 * len(d)))
    fig.add_trace(
        go.Bar(
            y=[pretty.get(k, k) for k in d["kind"]],
            x=d["n"],
            orientation="h",
            marker=dict(color=t["brand"], line=dict(width=0)),
            width=0.5,
            text=d["n"],
            textposition="outside",
            textfont=dict(size=11.5, color=t["ink_faint"]),
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x} calls<extra></extra>",
        )
    )
    fig.update_xaxes(visible=False, range=[0, float(d["n"].max()) * 1.2])
    fig.update_yaxes(linecolor="rgba(0,0,0,0)", tickfont=dict(size=12, color=t["ink"]))
    return fig


GRAPH_CONFIG = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": False,
}
