"""Clearance planning: turn the overdue list into a proposed price per product, under
the store's own rule, and write it down for a human to read before anything changes.

Rule (set by the owner, 2026-09-07):
  - a product's "average selling time" is the corrected model's median time to first
    sale for a listing with its attributes;
  - past that median by up to 90 days: 10% off; 91-180 days: 15%; more than 180: 20%;
  - never below a 10% margin over cost; the cut shrinks to the floor if it has to;
  - a per-run cap on the cut (15% for the first run);
  - no cost on file, or already under the margin floor: listed, not cut.
Prices land on a .99 ending. This module never writes to the store.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path

from sellthrough.overdue import LevelCorrection, Overdue, sold_by_with_offset
from sellthrough.models import DiscreteHazard

TIERS = ((90, 0.10), (180, 0.15), (math.inf, 0.20))   # (days past median, cut)


@dataclass
class Proposal:
    item: Overdue
    median_days: int | None      # None: half never sell within the model's horizon
    days_past: int | None
    tier_cut: float
    cut: float                   # after the cap and the margin floor
    new_price: float | None
    reason: str                  # cut | cut-median-capped | floor-limited | under-floor | no-cost | not-past


def model_median(model: DiscreteHazard, item: Overdue, offset: float) -> int | None:
    """First day at which the corrected probability of a sale reaches one half."""
    for t in range(1, model.max_days, 5):
        if sold_by_with_offset(model, [item.row], t, offset)[0] >= 0.5:
            return t
    return None


def up_to_ending(x: float) -> float:
    """Smallest price ending in .49 or .99 that is >= x (to the cent)."""
    x = round(x, 2)
    whole = math.floor(x)
    for cand in (whole - 0.51, whole - 0.01, whole + 0.49, whole + 0.99):
        if cand >= x - 1e-9 and cand > 0:
            return round(cand, 2)
    return round(whole + 0.99, 2)


MEDIAN_CAP_DAYS = 360   # a product whose median lies beyond the model's horizon is treated as this


def propose(item: Overdue, median: int | None, max_cut: float, min_margin: float) -> Proposal:
    price = item.row.price
    median_capped = median is None
    if median is None:
        median = MEDIAN_CAP_DAYS
    past = item.age_days - median
    if past <= 0:
        return Proposal(item, median, past, 0.0, 0.0, None, "not-past")
    tier_cut = next(cut for limit, cut in TIERS if past <= limit)
    cut = min(tier_cut, max_cut)
    if item.cost is None:
        return Proposal(item, median, past, tier_cut, cut, None, "no-cost")
    margin_floor = item.cost / (1.0 - min_margin)
    cap_floor = price * (1.0 - max_cut)
    if price < margin_floor - 1e-9:
        return Proposal(item, median, past, tier_cut, 0.0, None, "under-floor")
    # the tier's target, then the first .49/.99 ending that respects BOTH floors
    target = max(price * (1.0 - cut), margin_floor, cap_floor)
    new_price = up_to_ending(target)
    reason = "floor-limited" if margin_floor > price * (1.0 - cut) + 1e-9 else "cut"
    if median_capped and reason == "cut":
        reason = "cut-median-capped"
    if new_price >= price - 1e-9:
        return Proposal(item, median, past, tier_cut, 0.0, None, "under-floor")
    return Proposal(item, median, past, tier_cut, (price - new_price) / price, round(new_price, 2), reason)


def plan(items: list[Overdue], model: DiscreteHazard, level: LevelCorrection,
         max_cut: float, min_margin: float) -> list[Proposal]:
    out = []
    for it in items:
        if it.stock is not None and it.stock <= 0:
            continue
        out.append(propose(it, model_median(model, it, level.offset), max_cut, min_margin))
    order = {"cut": 0, "cut-median-capped": 0, "floor-limited": 1, "under-floor": 2, "no-cost": 3, "not-past": 4}
    out.sort(key=lambda p: (order[p.reason], -(p.days_past or 0)))
    return out


def write_csv(props: list[Proposal], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant_id", "product_id", "title", "days_listed", "median_days", "days_past_median",
                    "on_hand", "cost", "current_price", "tier_cut", "applied_cut", "new_price",
                    "margin_after", "decision"])
        for p in props:
            it = p.item
            margin_after = "" if p.new_price is None or it.cost is None else f"{(p.new_price - it.cost) / p.new_price:.3f}"
            w.writerow([it.row.variant_id, it.row.product_id, it.row.title, it.age_days,
                        "" if p.median_days is None else p.median_days, "" if p.days_past is None else p.days_past,
                        "" if it.stock is None else it.stock, "" if it.cost is None else f"{it.cost:.2f}",
                        f"{it.row.price:.2f}", f"{p.tier_cut:.2f}", f"{p.cut:.3f}",
                        "" if p.new_price is None else f"{p.new_price:.2f}", margin_after, p.reason])


def summary(props: list[Proposal], snapshot: dt.date, max_cut: float, min_margin: float) -> str:
    by = {}
    for p in props:
        by.setdefault(p.reason, []).append(p)
    cuts = by.get("cut", []) + by.get("cut-median-capped", []) + by.get("floor-limited", [])
    cuts.sort(key=lambda p: -(p.days_past or 0))
    units = sum(p.item.stock or 0 for p in cuts)
    before = sum(p.item.row.price * (p.item.stock or 0) for p in cuts)
    after = sum((p.new_price or 0) * (p.item.stock or 0) for p in cuts)
    lines = [f"# Clearance plan, {snapshot.isoformat()} snapshot", "",
             f"Rule: 10% past the product's median selling time, 15% at 91-180 days past, 20% beyond; "
             f"capped at {100 * max_cut:.0f}% this run; never under {100 * min_margin:.0f}% margin over cost. "
             f"Nothing here has been applied.", "",
             "| Decision | Products | Meaning |", "|---|---:|---|",
             f"| cut | {len(by.get('cut', [])):,} | tier cut applied (rounded up to a .49/.99 ending, never past the cap) |",
             f"| cut-median-capped | {len(by.get('cut-median-capped', [])):,} | same, for products whose median is beyond {MEDIAN_CAP_DAYS} days (treated as {MEDIAN_CAP_DAYS}) |",
             f"| floor-limited | {len(by.get('floor-limited', [])):,} | cut shrunk to keep {100 * min_margin:.0f}% margin |",
             f"| under-floor | {len(by.get('under-floor', [])):,} | already at or under the margin floor; not cut |",
             f"| no-cost | {len(by.get('no-cost', [])):,} | no cost per item on file; not cut |",
             f"| not-past | {len(by.get('not-past', [])):,} | younger than its median; leave alone |",
             "", f"**Proposed cuts:** {len(cuts):,} products, {units:,} units. At ticket {before:,.2f}; after the cuts "
             f"{after:,.2f}; the markdown is {before - after:,.2f} ({100 * (1 - after / before) if before else 0:.1f}%) "
             f"if every unit sold at the new price.", ""]
    tiers = {}
    for p in cuts:
        tiers[p.tier_cut] = tiers.get(p.tier_cut, 0) + 1
    lines += ["| Tier | Products |", "|---|---:|"] + [f"| {100 * k:.0f}% tier | {v:,} |" for k, v in sorted(tiers.items())]
    lines += ["", "## First 40 proposed cuts", "",
              "| Title | Days listed | Median | Past by | Cost | Now | Proposed | Cut | On hand |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p in cuts[:40]:
        it = p.item
        lines.append(f"| {it.row.title[:55]} | {it.age_days} | {p.median_days} | {p.days_past} | ${it.cost:.2f} | "
                     f"${it.row.price:.2f} | ${p.new_price:.2f} | {100 * p.cut:.0f}% | {it.stock} |")
    return "\n".join(lines) + "\n"
