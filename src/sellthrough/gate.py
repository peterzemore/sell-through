"""Fail CI when the test numbers fall below gates.toml, when the protocol drifted, or
when a fresh run no longer reproduces the committed point estimates."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from sellthrough.protocol import HORIZON_DAYS, TEST_ORIGIN, TEST_WINDOW_END

DRIFT_TOL = 1e-9
POINT_KEYS = ("brier", "brier_skill", "auc", "concordance", "mean_predicted")


def check(test: dict, gates: dict, committed: dict | None = None) -> list[str]:
    fails: list[str] = []
    p = gates["protocol"]
    if (p["horizon_days"] != HORIZON_DAYS or p["test_origin"] != TEST_ORIGIN.isoformat()
            or p["test_window_end"] != TEST_WINDOW_END.isoformat()):
        fails.append("protocol in gates.toml does not match protocol.py")
    if test["eval_n"] < p["min_test_listings"]:
        fails.append(f"only {test['eval_n']} test listings, gate needs {p['min_test_listings']}")
    t = gates["thresholds"]
    best = max(test["results"], key=lambda r: r["brier_skill"])
    for key, gate in (("brier_skill", "brier_skill_min"), ("auc", "auc_min"), ("concordance", "concordance_min")):
        if best[key] < t[gate]:
            fails.append(f"{best['model']}: {key} {best[key]:.4f} < {t[gate]}")
    for r in test["results"]:
        gap = abs(r["mean_predicted"] - r["observed_rate"])
        if gap > t["calibration_gap_max"]:
            fails.append(f"{r['model']}: mean predicted off observed rate by {gap:.3f} > {t['calibration_gap_max']}")
    if committed is not None:
        old = {r["model"]: r for r in committed["results"]}
        for r in test["results"]:
            if r["model"] not in old:
                fails.append(f"drift: {r['model']} is not in the committed results")
                continue
            for k in POINT_KEYS:
                if abs(r[k] - old[r["model"]][k]) > DRIFT_TOL:
                    fails.append(f"drift: {r['model']} {k} {r[k]!r} != committed {old[r['model']][k]!r}")
    return fails


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def load_gates(path: Path) -> dict:
    return tomllib.loads(path.read_text())
