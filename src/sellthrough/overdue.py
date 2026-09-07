"""Milestone 3: which listed items are past the point where one like them would
usually have sold?

The discrete-time hazard model is fit on the whole cohort, then its level is corrected to
the most recent window in which listings have had the full horizon to sell -- the
evaluation showed that discrimination transfers across windows and the level does not.
For every listing that has not sold, the score is the corrected probability that a
listing with its attributes would have sold by its current age. A high score on an
unsold item is the definition of overdue. Live stock, when credentials are available,
separates "still on the shelf" from "gone without a recorded sale"."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from sellthrough.cohort import Row
from sellthrough.models import DiscreteHazard
from sellthrough.protocol import HORIZON_DAYS
from sellthrough.splits import label


@dataclass
class LevelCorrection:
    window_start: dt.date
    n: int
    observed: float
    predicted_before: float
    offset: float          # added to the model's hazard logits
    predicted_after: float


def recent_window(rows: list[Row], days: int = 180, min_listings: int = 50) -> list[Row]:
    """Listings old enough to have had the full horizon, from the most recent `days`.
    Widens to every listing with a full horizon when the recent window is too thin
    to set a level on."""
    snapshot = rows[0].snapshot
    latest = snapshot - dt.timedelta(days=HORIZON_DAYS)
    earliest = latest - dt.timedelta(days=days)
    window = [r for r in rows if earliest <= r.listed_at <= latest]
    if len(window) < min_listings:
        window = [r for r in rows if r.listed_at <= latest]
    if not window:
        raise ValueError("no listings with a full horizon of follow-up; cannot set a level")
    return window


def sold_by_with_offset(model: DiscreteHazard, rows: list[Row], t: float, offset: float) -> np.ndarray:
    from sellthrough.features import design_matrix
    X = design_matrix(rows, model.vocab)
    k_full = int(t) // model.bin_days
    frac = (t - k_full * model.bin_days) / model.bin_days
    lin = X @ model.w[model.n_bins:] + offset
    surv = np.ones(len(rows))
    for k in range(min(k_full + 1, model.n_bins)):
        h = 1.0 / (1.0 + np.exp(-(model.w[k] + lin)))
        surv *= (1.0 - h) if k < k_full else (1.0 - h) ** frac
    return 1.0 - surv


def fit_level(model: DiscreteHazard, window: list[Row]) -> LevelCorrection:
    """Shift the hazard logits so the mean predicted horizon probability on the recent
    window equals what actually happened there. Bisection on a monotone function."""
    y = np.array([label(r) for r in window], float)
    observed = float(y.mean())
    before = float(sold_by_with_offset(model, window, HORIZON_DAYS, 0.0).mean())
    lo, hi = -3.0, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if sold_by_with_offset(model, window, HORIZON_DAYS, mid).mean() < observed:
            lo = mid
        else:
            hi = mid
    offset = (lo + hi) / 2
    after = float(sold_by_with_offset(model, window, HORIZON_DAYS, offset).mean())
    return LevelCorrection(min(r.listed_at for r in window), len(window), observed, before, offset, after)


@dataclass
class Overdue:
    row: Row
    age_days: int
    p_sold_by_now: float
    stock: int | None      # None when unknown


def score_unsold(rows: list[Row], stock: dict[str, int] | None = None, min_days: int = 30,
                 l2: float = 10.0) -> tuple[list[Overdue], LevelCorrection, DiscreteHazard]:
    model = DiscreteHazard(l2=l2).fit(rows)
    level = fit_level(model, recent_window(rows))
    unsold = [r for r in rows if r.event == 0 and r.days >= min_days]
    ages = np.array([r.days for r in unsold], float)
    out = []
    for r, age in zip(unsold, ages):
        t = min(float(age), model.max_days - 1)
        p = float(sold_by_with_offset(model, [r], t, level.offset)[0])
        out.append(Overdue(r, int(age), p, None if stock is None else stock.get(r.variant_id, 0)))
    out.sort(key=lambda o: (-o.p_sold_by_now, -o.age_days))
    return out, level, model


def render(items: list[Overdue], level: LevelCorrection, snapshot: dt.date, top: int, stock_known: bool) -> str:
    on_shelf = [o for o in items if o.stock is None or o.stock > 0]
    gone = [o for o in items if o.stock is not None and o.stock <= 0]
    lines = [f"# Overdue listings as of {snapshot.isoformat()}", "",
             f"Listings with no recorded sale, ranked by the corrected probability that a listing "
             f"with the same price, tags, and listing-day size would have sold by its current age. "
             f"Level correction: on the {level.n} listings from {level.window_start.isoformat()} onward with a "
             f"full {HORIZON_DAYS} days of follow-up, {100 * level.observed:.1f}% sold within {HORIZON_DAYS} days; "
             f"the model said {100 * level.predicted_before:.1f}% before correction and "
             f"{100 * level.predicted_after:.1f}% after (logit offset {level.offset:+.3f}).", ""]
    if not stock_known:
        lines += ["Stock is **unknown** in this run (no credentials), so items that left the shelf without a "
                  "recorded sale are mixed in.", ""]
    lines += [f"## {'On the shelf and overdue' if stock_known else 'Unsold listings'} (top {top} of {len(on_shelf)})", "",
              "| # | Variant | Title | Price | Days listed | P(sold by now) |" + (" On hand |" if stock_known else ""),
              "|---:|---|---|---:|---:|---:|" + ("---:|" if stock_known else "")]
    for i, o in enumerate(on_shelf[:top], 1):
        lines.append(f"| {i} | {o.row.variant_id} | {o.row.title[:60]} | ${o.row.price:.2f} | {o.age_days} | "
                     f"{100 * o.p_sold_by_now:.0f}% |" + (f" {o.stock} |" if stock_known else ""))
    if stock_known:
        lines += ["", f"## Gone without a recorded sale ({len(gone)})", "",
                  "Zero on hand and no sale in the order history: sold outside the system, returned to a "
                  "distributor, moved to another channel, or shrink. Worth a look, not a markdown.", "",
                  "| Variant | Title | Price | Days listed |", "|---|---|---:|---:|"]
        for o in gone[:top]:
            lines.append(f"| {o.row.variant_id} | {o.row.title[:60]} | ${o.row.price:.2f} | {o.age_days} |")
    return "\n".join(lines) + "\n"
