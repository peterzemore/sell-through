import numpy as np

from sellthrough.metrics import auc, brier, brier_skill, calibration_table, concordance


def test_brier_and_skill():
    y = np.array([1, 0, 1, 0])
    assert brier(np.array([1, 0, 1, 0]), y) == 0.0
    assert abs(brier(np.array([0.5] * 4), y) - 0.25) < 1e-12
    assert abs(brier_skill(np.array([0.9, 0.1, 0.9, 0.1]), y, 0.5) - (1 - 0.01 / 0.25)) < 1e-12
    assert brier_skill(np.array([0.5] * 4), y, 0.5) == 0.0


def test_auc_hand_examples():
    assert auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]) == 0.5
    assert abs(auc([0.9, 0.3, 0.5, 0.1], [1, 0, 1, 0]) - 1.0) < 1e-12
    assert np.isnan(auc([0.1, 0.2], [1, 1]))


def test_concordance_hand_example():
    # listing A sold day 5, B sold day 20, C censored day 50
    days, event = [5, 20, 50], [1, 1, 0]
    assert concordance([0.9, 0.5, 0.1], days, event) == 1.0     # earlier sale, higher risk
    assert concordance([0.1, 0.5, 0.9], days, event) == 0.0
    assert concordance([0.5, 0.5, 0.5], days, event) == 0.5
    # a censored listing is never the earlier member of a comparable pair
    assert np.isnan(concordance([1, 2], [10, 20], [0, 0]))


def test_calibration_table_shapes():
    p = np.linspace(0, 1, 100)
    t = calibration_table(p, (p > 0.5).astype(float), bins=10)
    assert len(t) == 10 and sum(c["n"] for c in t) == 100
    assert t[0]["observed"] == 0.0 and t[-1]["observed"] == 1.0
