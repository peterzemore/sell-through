import numpy as np

from sellthrough.km import kaplan_meier


def test_hand_worked_example():
    # days 1,2,2,3,4 with events at 1, 2 (one of the two), 3
    c = kaplan_meier([1, 2, 2, 3, 4], [1, 1, 0, 1, 0])
    assert c.survival_at(0) == 1.0
    assert abs(c.survival_at(1) - 0.8) < 1e-12
    assert abs(c.survival_at(2.5) - 0.6) < 1e-12
    assert abs(c.survival_at(3) - 0.3) < 1e-12         # at risk at 3: {3, 4} -> 0.6 * (1 - 1/2)
    assert abs(c.survival_at(100) - 0.3) < 1e-12
    assert c.median() == 3


def test_all_censored_is_flat_one():
    c = kaplan_meier([5, 9, 30], [0, 0, 0])
    assert c.survival_at(1000) == 1.0 and c.median() is None and c.n_events == 0


def test_ci_brackets_estimate_and_is_monotone():
    rng = np.random.default_rng(0)
    days = rng.exponential(60, 400).round()
    event = (rng.random(400) < 0.7).astype(int)
    c = kaplan_meier(days, event)
    assert np.all(np.diff(c.surv) <= 1e-12)
    assert np.all(c.lower <= c.surv + 1e-12) and np.all(c.surv <= c.upper + 1e-12)
    assert np.all(c.lower >= 0) and np.all(c.upper <= 1)


def test_tied_censoring_counts_as_at_risk():
    # censored exactly at the event time stays in the risk set
    c = kaplan_meier([5, 5], [1, 0])
    assert abs(c.survival_at(5) - 0.5) < 1e-12
