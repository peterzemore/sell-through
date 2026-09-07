"""Models that turn a listing into a survival curve. Every model exposes
fit(rows) and sold_by(rows, t) -> P(first sale on or before day t)."""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from sellthrough.cohort import Row
from sellthrough.features import (Vocabulary, batch_bucket_index, design_matrix,
                                  fit_vocabulary, price_band_index)
from sellthrough.km import kaplan_meier


class KMNull:
    """One Kaplan-Meier curve for everyone: the null the others must beat."""
    name = "km_null"

    def fit(self, rows: list[Row]) -> "KMNull":
        self.curve = kaplan_meier([r.days for r in rows], [r.event for r in rows])
        return self

    def sold_by(self, rows: list[Row], t: float) -> np.ndarray:
        return np.full(len(rows), 1.0 - self.curve.survival_at(t))


class KMStrata:
    """A Kaplan-Meier curve per stratum; unseen strata fall back to the pooled curve."""

    def __init__(self, name: str, key):
        self.name, self.key = name, key

    def fit(self, rows: list[Row]) -> "KMStrata":
        self.pooled = kaplan_meier([r.days for r in rows], [r.event for r in rows])
        groups: dict = {}
        for r in rows:
            groups.setdefault(self.key(r), []).append(r)
        self.curves = {k: kaplan_meier([r.days for r in g], [r.event for r in g]) for k, g in groups.items()}
        return self

    def sold_by(self, rows: list[Row], t: float) -> np.ndarray:
        return np.array([1.0 - self.curves.get(self.key(r), self.pooled).survival_at(t) for r in rows])


def _stratum_price(r: Row) -> int:
    return price_band_index(r.price)


def _stratum_price_batch(r: Row) -> tuple[int, int]:
    return price_band_index(r.price), batch_bucket_index(r.batch_size)


class CoxPH:
    """lifelines Cox proportional hazards on the design matrix, L2 penalised."""

    def __init__(self, penalizer: float = 0.1, min_tag_count: int = 30):
        self.penalizer, self.min_tag_count = penalizer, min_tag_count
        self.name = f"cox(penalizer={penalizer})"

    def fit(self, rows: list[Row]) -> "CoxPH":
        import pandas as pd
        from lifelines import CoxPHFitter
        self.vocab = fit_vocabulary(rows, self.min_tag_count)
        X = design_matrix(rows, self.vocab)
        df = pd.DataFrame(X, columns=[f"x{i}" for i in range(X.shape[1])])
        # lifelines wants strictly positive durations; a same-day sale is day 0.
        df["T"] = np.array([r.days for r in rows], float) + 0.5
        df["E"] = [r.event for r in rows]
        self.model = CoxPHFitter(penalizer=self.penalizer)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model.fit(df, duration_col="T", event_col="E", fit_options={"step_size": 0.5})
        return self

    def sold_by(self, rows: list[Row], t: float) -> np.ndarray:
        import pandas as pd
        X = design_matrix(rows, self.vocab)
        df = pd.DataFrame(X, columns=[f"x{i}" for i in range(X.shape[1])])
        surv = self.model.predict_survival_function(df, times=[t + 0.5])
        return 1.0 - surv.iloc[0].to_numpy()


@dataclass
class DiscreteHazard:
    """Discrete-time hazard model: the listing's follow-up is cut into periods of
    `bin_days`, each period is one row with an event flag, and a logistic regression
    with one intercept per period plus the listing features is fit by penalised IRLS.
    S(t) is the product of (1 - hazard) over the periods up to t. numpy only."""
    l2: float = 1.0
    bin_days: int = 10
    max_days: int = 360
    min_tag_count: int = 30
    name: str = field(init=False)

    def __post_init__(self):
        self.name = f"dthazard(l2={self.l2}, bin={self.bin_days}d)"
        self.n_bins = self.max_days // self.bin_days

    def _expand(self, X: np.ndarray, days: np.ndarray, event: np.ndarray):
        rows_x, rows_b, rows_y = [], [], []
        for i in range(len(days)):
            d = min(int(days[i]), self.max_days - 1)
            last = d // self.bin_days              # period index containing day d
            for k in range(last + 1):
                rows_x.append(X[i]); rows_b.append(k)
                rows_y.append(1 if (event[i] and k == last and days[i] < self.max_days) else 0)
        B = np.zeros((len(rows_b), self.n_bins)); B[np.arange(len(rows_b)), rows_b] = 1.0
        return np.hstack([B, np.array(rows_x)]), np.array(rows_y, float)

    def fit(self, rows: list[Row]) -> "DiscreteHazard":
        self.vocab = fit_vocabulary(rows, self.min_tag_count)
        X = design_matrix(rows, self.vocab)
        Z, y = self._expand(X, np.array([r.days for r in rows]), np.array([r.event for r in rows]))
        pen = np.full(Z.shape[1], self.l2); pen[: self.n_bins] = 1e-3   # period intercepts nearly free
        w = np.zeros(Z.shape[1])
        for _ in range(50):
            eta = Z @ w
            mu = 1.0 / (1.0 + np.exp(-eta))
            grad = Z.T @ (mu - y) + pen * w
            H = (Z * (mu * (1 - mu))[:, None]).T @ Z + np.diag(pen)
            step = np.linalg.solve(H, grad)
            w -= step
            if np.max(np.abs(step)) < 1e-6:
                break
        self.w = w
        return self

    def sold_by(self, rows: list[Row], t: float) -> np.ndarray:
        X = design_matrix(rows, self.vocab)
        k_full = int(t) // self.bin_days                         # periods fully inside [0, t]
        frac = (t - k_full * self.bin_days) / self.bin_days      # partial credit for the last one
        lin = X @ self.w[self.n_bins:]
        surv = np.ones(len(rows))
        for k in range(min(k_full + 1, self.n_bins)):
            h = 1.0 / (1.0 + np.exp(-(self.w[k] + lin)))
            surv *= (1.0 - h) if k < k_full else (1.0 - h) ** frac
        return 1.0 - surv


def baselines() -> list:
    return [KMNull(), KMStrata("km_by_price_band", _stratum_price),
            KMStrata("km_by_price_x_batch", _stratum_price_batch)]


def cox_grid() -> list:
    return [CoxPH(p) for p in (0.05, 0.2, 1.0)]


def hazard_grid() -> list:
    return [DiscreteHazard(l2=l) for l in (0.1, 1.0, 10.0)]
