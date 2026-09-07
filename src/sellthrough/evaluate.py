"""Validation sweep, selection, and the single test scoring.

Fit sets are censored at the split origin (splits.fit_set); evaluation rows are the
listings after the origin with a full horizon of follow-up. Selection metric on
validation is Brier skill at the horizon against the Kaplan-Meier null fit on the same
fit set. Test is scored once for the baselines and the validation winner of each family."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from sellthrough.cohort import Row
from sellthrough.metrics import auc, bootstrap_ci, brier, brier_skill, calibration_table, concordance
from sellthrough.models import KMNull, baselines, cox_grid, hazard_grid
from sellthrough.protocol import (HORIZON_DAYS, TEST_ORIGIN, TEST_WINDOW_END, VAL_ORIGIN,
                                  VAL_WINDOW_END)
from sellthrough.splits import eval_set, fit_set, label


def score(model, fit: list[Row], ev: list[Row], null_p: np.ndarray, draws: int, seed: int,
          with_calibration: bool = False) -> dict:
    model.fit(fit)
    p = np.clip(model.sold_by(ev, HORIZON_DAYS), 1e-6, 1 - 1e-6)
    y = np.array([label(r) for r in ev], float)
    days = np.array([r.days for r in ev], float)
    event = np.array([r.event for r in ev], int)
    out = {
        "model": model.name,
        "brier": brier(p, y),
        "brier_skill": brier_skill(p, y, null_p),
        "auc": auc(p, y),
        "concordance": concordance(p, days, event),
        "mean_predicted": float(p.mean()),
        "observed_rate": float(y.mean()),
        "n": int(len(ev)),
    }
    if draws:
        out["brier_skill_ci"] = bootstrap_ci(lambda ix: brier_skill(p[ix], y[ix], null_p[ix]), len(ev), draws, seed)
        out["auc_ci"] = bootstrap_ci(lambda ix: auc(p[ix], y[ix]), len(ev), draws, seed + 1)
    if with_calibration:
        out["calibration"] = calibration_table(p, y)
    return out


def run_split(rows: list[Row], origin, window_end, models: list, draws: int, seed: int,
              calibrate_best: bool = False) -> dict:
    fit, ev = fit_set(rows, origin), eval_set(rows, origin, window_end)
    null = KMNull().fit(fit)
    null_p = null.sold_by(ev, HORIZON_DAYS)
    results = [score(m, fit, ev, null_p, draws, seed) for m in models]
    if calibrate_best:
        best = max(results, key=lambda r: r["brier_skill"])
        for m in models:
            if m.name == best["model"]:
                best["calibration"] = calibration_table(
                    np.clip(m.sold_by(ev, HORIZON_DAYS), 1e-6, 1 - 1e-6), np.array([label(r) for r in ev], float))
    return {"origin": origin.isoformat(), "window_end": window_end.isoformat(), "horizon_days": HORIZON_DAYS,
            "fit_n": len(fit), "eval_n": len(ev), "eval_sold": int(sum(label(r) for r in ev)),
            "bootstrap_draws": draws, "seed": seed, "results": results}


def _pick(results: list[dict], prefix: str) -> str:
    cands = [r for r in results if r["model"].startswith(prefix)]
    return max(cands, key=lambda r: r["brier_skill"])["model"]


def evaluate(rows: list[Row], draws: int, seed: int, out_dir: Path) -> tuple[dict, dict]:
    sweep = baselines() + cox_grid() + hazard_grid()
    val = run_split(rows, VAL_ORIGIN, VAL_WINDOW_END, sweep, draws=0, seed=seed)
    chosen = {_pick(val["results"], "cox"), _pick(val["results"], "dthazard")}
    val["chosen"] = sorted(chosen)
    test_models = baselines() + [m for m in cox_grid() + hazard_grid() if m.name in chosen]
    test = run_split(rows, TEST_ORIGIN, TEST_WINDOW_END, test_models, draws=draws, seed=seed, calibrate_best=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "val.json").write_text(json.dumps(val, indent=2) + "\n")
    (out_dir / "test.json").write_text(json.dumps(test, indent=2) + "\n")
    return val, test


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_results(val: dict, test: dict) -> str:
    lines = [f"**Validation** (fit on listings before {val['origin']}, censored there; scored on {val['eval_n']:,} "
             f"listings from {val['origin']} to {val['window_end']}, {pct(val['eval_sold'] / val['eval_n'])} sold within "
             f"{val['horizon_days']} days). Selection metric is Brier skill.", "",
             "| Model | Brier skill @90 | AUC @90 | Concordance | Mean predicted |",
             "|---|---:|---:|---:|---:|"]
    for r in val["results"]:
        mark = " **(chosen)**" if r["model"] in val.get("chosen", []) else ""
        lines.append(f"| `{r['model']}`{mark} | {r['brier_skill']:+.3f} | {r['auc']:.3f} | {r['concordance']:.3f} | "
                     f"{pct(r['mean_predicted'])} |")
    lines += ["", f"**Test** (fit on listings before {test['origin']}, censored there; scored once on {test['eval_n']:,} "
              f"listings from {test['origin']} to {test['window_end']}, {pct(test['eval_sold'] / test['eval_n'])} sold within "
              f"{test['horizon_days']} days; {test['bootstrap_draws']:,}-draw bootstrap over listings).", "",
              "| Model | Brier @90 | Brier skill @90 [95% CI] | AUC @90 [95% CI] | Concordance | Mean predicted |",
              "|---|---:|---:|---:|---:|---:|"]
    for r in test["results"]:
        sk = f"{r['brier_skill']:+.3f} [{r['brier_skill_ci'][0]:+.3f}, {r['brier_skill_ci'][1]:+.3f}]"
        au = f"{r['auc']:.3f} [{r['auc_ci'][0]:.3f}, {r['auc_ci'][1]:.3f}]"
        lines.append(f"| `{r['model']}` | {r['brier']:.4f} | {sk} | {au} | {r['concordance']:.3f} | {pct(r['mean_predicted'])} |")
    best = max(test["results"], key=lambda r: r["brier_skill"])
    if "calibration" in best:
        lines += ["", f"**Calibration of `{best['model']}` on test**, by decile of predicted probability "
                  f"(observed = share that sold within {test['horizon_days']} days):", "",
                  "| Decile | n | Predicted | Observed |", "|---:|---:|---:|---:|"]
        for i, c in enumerate(best["calibration"], 1):
            lines.append(f"| {i} | {c['n']} | {pct(c['predicted'])} | {pct(c['observed'])} |")
    return "\n".join(lines)
