"""Everything the README quotes, computed from the committed cohort."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from sellthrough.cohort import Row
from sellthrough.km import KMCurve, kaplan_meier
from sellthrough.protocol import (HORIZON_DAYS, KM_TIMES, TEST_ORIGIN, TEST_WINDOW_END,
                                  VAL_ORIGIN, VAL_WINDOW_END)
from sellthrough.splits import eval_set, fit_set, label

RARITY = re.compile(r"exclusive|\bchase\b|vault|limited|\b(sdcc|nycc|eccc|comic[- ]?con)\b", re.I)


def price_band(p: float) -> str:
    return "<$15" if p < 15 else "$15-25" if p < 25 else "$25-50" if p < 50 else "$50+"


def batch_bucket(n: int) -> str:
    return "1-9 listed that day" if n < 10 else "10-39 listed that day" if n < 40 else "40+ listed that day"


def rarity_flag(title: str) -> str:
    return "rarity word in title" if RARITY.search(title) else "no rarity word"


STRATA = {"price band": lambda r: price_band(r.price),
          "listing-day batch": lambda r: batch_bucket(r.batch_size),
          "title": lambda r: rarity_flag(r.title)}
STRATA_ORDER = {"price band": ["<$15", "$15-25", "$25-50", "$50+"],
                "listing-day batch": ["1-9 listed that day", "10-39 listed that day", "40+ listed that day"],
                "title": ["no rarity word", "rarity word in title"]}


def km_summary(rows: list[Row]) -> dict:
    c = kaplan_meier([r.days for r in rows], [r.event for r in rows])
    out = {"n": c.n, "events": c.n_events, "median_days": c.median()}
    for t in KM_TIMES:
        lo, hi = c.ci_at(t)
        out[f"sold_by_{t}"] = 1.0 - c.survival_at(t)
        out[f"sold_by_{t}_ci"] = [1.0 - hi, 1.0 - lo]
    return out


def describe(rows: list[Row], stats: dict) -> dict:
    n = len(rows)
    with_fu = [r for r in rows if (r.snapshot - r.listed_at).days >= HORIZON_DAYS]
    crude = sum(label(r) for r in with_fu) / len(with_fu)
    days = collections.Counter(r.listed_at for r in rows)
    bulk_days = sorted(d.isoformat() for d, k in days.items() if k >= 40)
    strata = {}
    for name, fn in STRATA.items():
        groups = collections.defaultdict(list)
        for r in rows:
            groups[fn(r)].append(r)
        strata[name] = {k: km_summary(groups[k]) for k in STRATA_ORDER[name] if k in groups}
    splits = {}
    for nm, origin, end in (("validation", VAL_ORIGIN, VAL_WINDOW_END), ("test", TEST_ORIGIN, TEST_WINDOW_END)):
        fit, ev = fit_set(rows, origin), eval_set(rows, origin, end)
        splits[nm] = {"origin": origin.isoformat(), "window_end": end.isoformat(),
                      "fit_n": len(fit), "fit_events": sum(r.event for r in fit),
                      "eval_n": len(ev), "eval_sold_within_horizon": sum(label(r) for r in ev)}
    return {
        "horizon_days": HORIZON_DAYS,
        "history_start": stats["history_start"], "snapshot": stats["snapshot"],
        "cohort_variants": n, "ever_sold": sum(r.event for r in rows),
        "left_truncated_excluded": stats.get("variants_left_truncated", 0),
        "with_full_horizon": len(with_fu), "crude_sold_within_horizon": crude,
        "listing_days": len(days), "bulk_listing_days": bulk_days,
        "bulk_share": sum(days[d] for d in days if days[d] >= 40) / n,
        "overall": km_summary(rows), "strata": strata, "splits": splits,
        "clean_stats": stats,
    }


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def ci(v: list[float]) -> str:
    return f"[{100 * v[0]:.1f}, {100 * v[1]:.1f}]"


def _km_row(name: str, s: dict) -> str:
    med = "not reached" if s["median_days"] is None else f"{s['median_days']:.0f}"
    cells = " | ".join(f"{pct(s[f'sold_by_{t}'])} {ci(s[f'sold_by_{t}_ci'])}" for t in KM_TIMES)
    return f"| {name} | {s['n']:,} | {s['events']:,} | {med} | {cells} |"


def render_data_table(d: dict) -> str:
    cs = d["clean_stats"]
    return "\n".join([
        "| | |", "|---|---|",
        f"| Order history | {d['history_start']} to {d['snapshot']} ({cs['orders_kept']:,} orders kept) |",
        f"| Listings excluded | {d['left_truncated_excluded']:,} variants listed before the order history begins (left-truncated); {cs.get('variants_listed_after_snapshot', 0)} listed after the snapshot |",
        f"| Cohort | {d['cohort_variants']:,} variants listed inside the history window, on {d['listing_days']} distinct days |",
        f"| Ever sold by the snapshot | {d['ever_sold']:,} ({pct(d['ever_sold'] / d['cohort_variants'])}); the rest are censored, not failures |",
        f"| Sold within {d['horizon_days']} days, crude | {pct(d['crude_sold_within_horizon'])} of the {d['with_full_horizon']:,} variants with a full {d['horizon_days']} days of follow-up |",
        f"| Sold within {d['horizon_days']} days, Kaplan-Meier | {pct(d['overall'][f'sold_by_{d['horizon_days']}'])} {ci(d['overall'][f'sold_by_{d['horizon_days']}_ci'])}, using every listing |",
        f"| Bulk listing days | {len(d['bulk_listing_days'])} days with 40+ listings carry {pct(d['bulk_share'])} of the cohort |",
        f"| Cleaning | cancelled {cs.get('orders_cancelled', 0)}, test {cs.get('orders_test', 0)}, owner {cs.get('orders_owner', 0)} orders; {cs.get('lines_fully_refunded', 0)} fully refunded lines; {cs.get('products_not_active', 0)} draft products; {cs.get('products_non_merchandise', 0)} tip/gift-card products |",
    ])


def render_km_table(d: dict) -> str:
    head = "| Stratum | Listings | Sold | KM median days to first sale | " + " | ".join(f"Sold by day {t}" for t in KM_TIMES) + " |"
    sep = "|---|---:|---:|---:|" + "---:|" * len(KM_TIMES)
    lines = [head, sep, _km_row("All listings", d["overall"])]
    for name, groups in d["strata"].items():
        for k, s in groups.items():
            lines.append(_km_row(f"{name}: {k}", s))
    return "\n".join(lines)


def render_split_table(d: dict) -> str:
    lines = ["| Split | Prediction date | Listings scored | Fit set (censored at the prediction date) | Scored listings | Sold within horizon |",
             "|---|---|---|---:|---:|---:|"]
    for nm, s in d["splits"].items():
        lines.append(f"| {nm} | {s['origin']} | listed {s['origin']} to {s['window_end']} | "
                     f"{s['fit_n']:,} ({s['fit_events']:,} sales visible) | {s['eval_n']:,} | "
                     f"{s['eval_sold_within_horizon']:,} ({pct(s['eval_sold_within_horizon'] / s['eval_n'])}) |")
    return "\n".join(lines)


def update_block(text: str, name: str, body: str) -> str:
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if start not in text or end not in text:
        raise ValueError(f"README is missing the {name} markers")
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    return f"{pre}{start}\n{body}\n{end}{post}"


def update_readme(path: Path, d: dict) -> None:
    text = path.read_text()
    text = update_block(text, "data-table", render_data_table(d))
    text = update_block(text, "km-table", render_km_table(d))
    text = update_block(text, "split-table", render_split_table(d))
    path.write_text(text)


def dump(d: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
