"""Scoring for a probability of sale within the horizon, plus concordance over the
full follow-up. Everything takes plain numpy arrays."""
from __future__ import annotations

import numpy as np


def brier(p: np.ndarray, y: np.ndarray) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def brier_skill(p: np.ndarray, y: np.ndarray, p_null: np.ndarray | float) -> float:
    """1 - Brier(model) / Brier(null). Positive means better than the null."""
    b_null = brier(np.broadcast_to(np.asarray(p_null, float), np.shape(y)), y)
    return float(1.0 - brier(p, y) / b_null) if b_null > 0 else 0.0


def auc(p: np.ndarray, y: np.ndarray) -> float:
    """Rank-based AUC (Mann-Whitney), ties counted as half."""
    p, y = np.asarray(p, float), np.asarray(y, int)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), float)
    sorted_p = p[order]
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)))


def concordance(risk: np.ndarray, days: np.ndarray, event: np.ndarray) -> float:
    """Harrell's C: over comparable pairs (the earlier time is an event), the share where
    the earlier-selling listing has the higher risk. Risk ties count half."""
    risk, days, event = np.asarray(risk, float), np.asarray(days, float), np.asarray(event, int)
    n = len(risk)
    conc = comparable = 0.0
    for i in range(n):
        if not event[i]:
            continue
        later = days > days[i]
        comparable += later.sum()
        conc += (risk[later] < risk[i]).sum() + 0.5 * (risk[later] == risk[i]).sum()
    return float(conc / comparable) if comparable else float("nan")


def calibration_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    order = np.argsort(p, kind="mergesort")
    out = []
    for chunk in np.array_split(order, bins):
        if len(chunk) == 0:
            continue
        out.append({"n": int(len(chunk)), "predicted": float(p[chunk].mean()),
                    "observed": float(y[chunk].mean())})
    return out


def bootstrap_ci(stat, n: int, draws: int, seed: int, level: float = 0.95) -> list[float]:
    """Percentile interval of stat(index_array) over resamples of range(n)."""
    rng = np.random.default_rng(seed)
    vals = np.array([stat(rng.integers(0, n, n)) for _ in range(draws)], float)
    vals = vals[~np.isnan(vals)]
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return [float(np.quantile(vals, lo)), float(np.quantile(vals, hi))]
