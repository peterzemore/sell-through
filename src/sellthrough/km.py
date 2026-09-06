"""Kaplan-Meier estimator with Greenwood variance and log-log confidence limits.

Implemented here rather than imported so the core of the repo runs with numpy alone and
so the arithmetic is on the page. Tied censoring at an event time counts as at risk.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Z95 = 1.959963984540054


@dataclass(frozen=True)
class KMCurve:
    times: np.ndarray       # distinct event times, ascending
    surv: np.ndarray        # S(t) immediately after each event time
    lower: np.ndarray       # 95% log-log limits
    upper: np.ndarray
    at_risk: np.ndarray
    events: np.ndarray
    n: int
    n_events: int

    def survival_at(self, t: float) -> float:
        i = np.searchsorted(self.times, t, side="right") - 1
        return 1.0 if i < 0 else float(self.surv[i])

    def ci_at(self, t: float) -> tuple[float, float]:
        i = np.searchsorted(self.times, t, side="right") - 1
        return (1.0, 1.0) if i < 0 else (float(self.lower[i]), float(self.upper[i]))

    def median(self) -> float | None:
        """First time at which S(t) <= 0.5, or None if never reached in follow-up."""
        hit = np.nonzero(self.surv <= 0.5)[0]
        return None if len(hit) == 0 else float(self.times[hit[0]])


def kaplan_meier(days, event) -> KMCurve:
    days = np.asarray(days, dtype=float)
    event = np.asarray(event, dtype=int)
    if days.shape != event.shape:
        raise ValueError("days and event must align")
    times = np.unique(days[event == 1])
    surv, lower, upper, at_risk, n_ev = [], [], [], [], []
    s, greenwood = 1.0, 0.0
    for t in times:
        n = int(np.sum(days >= t))
        d = int(np.sum((days == t) & (event == 1)))
        s *= 1.0 - d / n
        if n > d:
            greenwood += d / (n * (n - d))
        if 0.0 < s < 1.0:
            se = np.sqrt(greenwood) / abs(np.log(s))
            lo, hi = s ** np.exp(Z95 * se), s ** np.exp(-Z95 * se)
        else:
            lo = hi = s
        surv.append(s); lower.append(lo); upper.append(hi); at_risk.append(n); n_ev.append(d)
    return KMCurve(times=times, surv=np.array(surv), lower=np.array(lower), upper=np.array(upper),
                   at_risk=np.array(at_risk), events=np.array(n_ev), n=int(len(days)),
                   n_events=int(event.sum()))
