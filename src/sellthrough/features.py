"""Design matrix for the models. Vocabulary (which tags get a column, the
standardisation constants) is learned from the fit set only, so nothing about the
evaluation listings leaks into the features."""
from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass

import numpy as np

from sellthrough.cohort import Row

KEYWORDS = {
    "kw_exclusive": re.compile(r"exclusive", re.I),
    "kw_chase": re.compile(r"\bchase\b", re.I),
    "kw_vault": re.compile(r"vault", re.I),
    "kw_glow": re.compile(r"glow", re.I),
    "kw_flocked": re.compile(r"flocked", re.I),
    "kw_metallic": re.compile(r"metallic", re.I),
    "kw_diamond": re.compile(r"diamond", re.I),
    "kw_limited": re.compile(r"limited", re.I),
    "kw_convention": re.compile(r"\b(sdcc|nycc|eccc|comic[- ]?con)\b", re.I),
}
# One-hot groups drop their first level as the reference, so the design matrix has
# no exactly collinear columns (Cox without that failed to converge).
PRICE_BANDS = ("band_15_25", "band_25_50", "band_50plus")      # reference: under $15
BATCH_BUCKETS = ("batch_10_39", "batch_40plus")                 # reference: 1-9 listed that day


def price_band_index(p: float) -> int:
    return 0 if p < 15 else 1 if p < 25 else 2 if p < 50 else 3


def batch_bucket_index(n: int) -> int:
    return 0 if n < 10 else 1 if n < 40 else 2


@dataclass(frozen=True)
class Vocabulary:
    tags: tuple[str, ...]
    log_price_mean: float
    log_price_std: float
    log_batch_mean: float
    log_batch_std: float
    active: tuple[bool, ...] = ()   # columns with any variance in the fit set

    @property
    def all_names(self) -> tuple[str, ...]:
        return (("log_price", "log_batch") + PRICE_BANDS + BATCH_BUCKETS
                + tuple(KEYWORDS) + tuple(f"tag:{t}" for t in self.tags))

    @property
    def names(self) -> tuple[str, ...]:
        if not self.active:
            return self.all_names
        return tuple(n for n, a in zip(self.all_names, self.active) if a)


def fit_vocabulary(rows: list[Row], min_tag_count: int = 30) -> Vocabulary:
    counts = collections.Counter(t for r in rows for t in r.tags)
    tags = tuple(sorted(t for t, c in counts.items() if c >= min_tag_count))
    lp = np.log([max(r.price, 0.01) for r in rows])
    lb = np.log1p([r.batch_size for r in rows])
    vocab = Vocabulary(tags=tags, log_price_mean=float(lp.mean()), log_price_std=float(lp.std() or 1.0),
                       log_batch_mean=float(lb.mean()), log_batch_std=float(lb.std() or 1.0))
    # A column that never varies in the fit set (a keyword no listing carried, a
    # batch size that did not occur) carries no information and makes the Cox
    # fitter divide by a zero standard deviation, so it is dropped here, once,
    # from the fit set's point of view.
    full = _full_matrix(rows, vocab)
    return Vocabulary(**{**vocab.__dict__, "active": tuple(bool(v) for v in full.var(axis=0) > 0)})


def design_matrix(rows: list[Row], vocab: Vocabulary) -> np.ndarray:
    full = _full_matrix(rows, vocab)
    return full[:, list(vocab.active)] if vocab.active else full


def _full_matrix(rows: list[Row], vocab: Vocabulary) -> np.ndarray:
    tag_index = {t: i for i, t in enumerate(vocab.tags)}
    n_fixed = 2 + len(PRICE_BANDS) + len(BATCH_BUCKETS) + len(KEYWORDS)
    X = np.zeros((len(rows), n_fixed + len(vocab.tags)))
    for i, r in enumerate(rows):
        X[i, 0] = (math.log(max(r.price, 0.01)) - vocab.log_price_mean) / vocab.log_price_std
        X[i, 1] = (math.log1p(r.batch_size) - vocab.log_batch_mean) / vocab.log_batch_std
        pb, bb = price_band_index(r.price), batch_bucket_index(r.batch_size)
        if pb > 0:
            X[i, 2 + pb - 1] = 1.0
        if bb > 0:
            X[i, 2 + len(PRICE_BANDS) + bb - 1] = 1.0
        base = 2 + len(PRICE_BANDS) + len(BATCH_BUCKETS)
        for k, (name, rx) in enumerate(KEYWORDS.items()):
            if rx.search(r.title):
                X[i, base + k] = 1.0
        for t in r.tags:
            j = tag_index.get(t)
            if j is not None:
                X[i, n_fixed + j] = 1.0
    return X
