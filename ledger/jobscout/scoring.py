"""Opportunity scoring.

The original ledger scored an entry from its public rating and review count
only, one Python/JS call per row. Here the whole table is scored in a single
vectorised NumPy pass, and two signals that actually matter for *scouting work*
are added:

``rating``   how well regarded the employer is (0 when unrated)
``reviews``  how much evidence backs that rating, log-compressed so a 4.3 with
             900 reviews outranks a lone 5.0
``gap``      no website on file -> an obvious, nameable thing to offer
``reach``    a phone number on file -> you can actually get through today

The four are blended with the weights in :mod:`config` and mapped to 0-9, the
same band the directory chips use.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from config import settings

SCORE_MAX = 9


def _as_float(values: Sequence[Any]) -> np.ndarray:
    out = np.zeros(len(values), dtype=np.float64)
    for i, v in enumerate(values):
        if v is None:
            continue
        try:
            out[i] = float(v)
        except (TypeError, ValueError):
            out[i] = 0.0
    return out


def score_rows(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Return an int array of 0-9 opportunity scores, one per row."""
    if not rows:
        return np.zeros(0, dtype=np.int64)

    rating = _as_float([r.get("rating") for r in rows])
    reviews = _as_float([r.get("reviews") for r in rows])
    has_site = np.array([bool(r.get("has_website")) for r in rows], dtype=bool)
    has_phone = np.array([bool(str(r.get("phone") or "").strip()) for r in rows], dtype=bool)

    # rating -> 0..1, unrated stays 0 rather than being treated as a zero-star
    rating_n = np.clip(rating / 5.0, 0.0, 1.0)

    # reviews -> 0..1 on a log scale against the busiest employer in the set
    peak = float(reviews.max())
    if peak > 0:
        reviews_n = np.log10(reviews + 1.0) / np.log10(peak + 1.0)
    else:
        reviews_n = np.zeros_like(reviews)

    gap_n = np.where(has_site, 0.0, 1.0)
    reach_n = np.where(has_phone, 1.0, 0.0)

    w_sum = settings.W_RATING + settings.W_REVIEWS + settings.W_GAP + settings.W_REACH
    if w_sum <= 0:
        w_sum = 1.0

    blended = (
        rating_n * settings.W_RATING
        + reviews_n * settings.W_REVIEWS
        + gap_n * settings.W_GAP
        + reach_n * settings.W_REACH
    ) / w_sum

    return np.rint(np.clip(blended, 0.0, 1.0) * SCORE_MAX).astype(np.int64)


def score_band(score: int) -> str:
    """CSS class suffix for a score chip: ``s-high`` / ``s-mid`` / ``s-low``."""
    if score >= 7:
        return "s-high"
    if score >= 5:
        return "s-mid"
    return "s-low"


def band_label(score: int) -> str:
    if score >= 7:
        return "Priority"
    if score >= 5:
        return "Worth a look"
    return "Low signal"
