import datetime as dt

import numpy as np

from sellthrough.cohort import Row
from sellthrough.features import design_matrix, fit_vocabulary
from sellthrough.models import CoxPH, DiscreteHazard, KMNull, KMStrata, _stratum_price

SNAP = dt.date(2026, 9, 5)


def make_rows(n=400, seed=0):
    """Cheap items sell faster: a synthetic cohort with a known direction."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        price = float(rng.choice([9.99, 12.99, 29.99, 79.99]))
        scale = 40 if price < 15 else 160
        t = int(rng.exponential(scale))
        censor = int(rng.integers(60, 400))
        event = int(t <= censor)
        days = t if event else censor
        tags = ("Funko Pops!",) if price < 15 else ("Loungefly", "Backpack")
        rows.append(Row(str(i), "p", "Thing exclusive" if i % 3 == 0 else "Thing", tags, price,
                        dt.date(2025, 1, 1), None, event, days, 5 + (i % 3) * 20, SNAP))
    return rows


def test_vocabulary_comes_from_fit_rows_only():
    fit = make_rows(200)
    v = fit_vocabulary(fit, min_tag_count=30)
    assert all(t in ("Funko Pops!", "Loungefly", "Backpack") for t in v.tags)
    X = design_matrix(fit, v)
    assert X.shape[0] == 200 and X.shape[1] == len(v.names)
    assert np.all(X.var(axis=0) > 0)                     # dead columns are dropped
    other = [r for r in make_rows(50, seed=1)]
    assert design_matrix(other, v).shape[1] == X.shape[1]  # same columns for new rows


def test_models_recover_the_price_direction():
    rows = make_rows()
    cheap = [r for r in rows if r.price < 15][:20]
    dear = [r for r in rows if r.price >= 50][:20]
    for m in (KMStrata("price", _stratum_price), CoxPH(0.2), DiscreteHazard(l2=1.0)):
        m.fit(rows)
        assert m.sold_by(cheap, 90).mean() > m.sold_by(dear, 90).mean(), m.name


def test_null_is_constant_and_probabilities_are_monotone_in_t():
    rows = make_rows()
    null = KMNull().fit(rows)
    p = null.sold_by(rows[:5], 90)
    assert np.allclose(p, p[0]) and 0 < p[0] < 1
    dh = DiscreteHazard(l2=1.0).fit(rows)
    a, b, c = (dh.sold_by(rows[:10], t) for t in (30, 90, 180))
    assert np.all(a <= b + 1e-12) and np.all(b <= c + 1e-12)
    assert np.all(dh.sold_by(rows[:10], 0) >= 0)
