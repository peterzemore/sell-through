import copy

from sellthrough.gate import check
from sellthrough.protocol import HORIZON_DAYS, TEST_ORIGIN, TEST_WINDOW_END

GATES = {"protocol": {"horizon_days": HORIZON_DAYS, "test_origin": TEST_ORIGIN.isoformat(),
                      "test_window_end": TEST_WINDOW_END.isoformat(), "min_test_listings": 300},
         "thresholds": {"brier_skill_min": 0.03, "auc_min": 0.60, "concordance_min": 0.57,
                        "calibration_gap_max": 0.15}}
TEST = {"eval_n": 319, "results": [
    {"model": "km_null", "brier": 0.24, "brier_skill": 0.0, "auc": 0.5, "concordance": 0.5,
     "mean_predicted": 0.31, "observed_rate": 0.386},
    {"model": "cox", "brier": 0.22, "brier_skill": 0.055, "auc": 0.647, "concordance": 0.611,
     "mean_predicted": 0.311, "observed_rate": 0.386}]}


def test_passes_today():
    assert check(TEST, GATES, copy.deepcopy(TEST)) == []


def test_catches_a_regression_and_drift():
    worse = copy.deepcopy(TEST); worse["results"][1]["brier_skill"] = 0.01
    assert any("brier_skill" in f for f in check(worse, GATES))
    drifted = copy.deepcopy(TEST); drifted["results"][1]["auc"] += 1e-6
    assert any(f.startswith("drift") for f in check(drifted, GATES, TEST))
    short = copy.deepcopy(TEST); short["eval_n"] = 100
    assert any("test listings" in f for f in check(short, GATES))
    off = copy.deepcopy(GATES); off["protocol"]["test_origin"] = "2025-01-01"
    assert any("protocol" in f for f in check(TEST, off))
    miscal = copy.deepcopy(TEST); miscal["results"][1]["mean_predicted"] = 0.9
    assert any("calibrat" in f.lower() or "observed rate" in f for f in check(miscal, GATES))
