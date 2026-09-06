"""Rolling-origin splits. At prediction date d you know what happened before d and
nothing after it, so the fit set is censored at d and the evaluation set is the
listings that came after d and have had the full horizon to sell."""
from __future__ import annotations

import datetime as dt
from dataclasses import replace

from sellthrough.cohort import Row
from sellthrough.protocol import HORIZON_DAYS


def fit_set(rows: list[Row], origin: dt.date) -> list[Row]:
    out = []
    for r in rows:
        if r.listed_at >= origin:
            continue
        visible = (origin - r.listed_at).days
        if r.event and r.days < visible:
            out.append(r)
        else:
            out.append(replace(r, event=0, days=visible, first_sale_at=None))
    return out


def eval_set(rows: list[Row], origin: dt.date, window_end: dt.date,
             horizon: int = HORIZON_DAYS) -> list[Row]:
    return [r for r in rows
            if origin <= r.listed_at <= window_end and (r.snapshot - r.listed_at).days >= horizon]


def label(r: Row, horizon: int = HORIZON_DAYS) -> int:
    """1 if the variant sold within the horizon. Only meaningful on an eval_set row."""
    return int(bool(r.event) and r.days <= horizon)
