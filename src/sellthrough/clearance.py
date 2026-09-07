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
LONG_STALE_DAYS = 400      # no sale within this many days: the full 20% regardless of the run cap
LONG_STALE_CUT = 0.20


@dataclass
class Proposal:
    item: Overdue
    median_days: int | None      # None: half never sell within the model's horizon
    days_past: int | None
    tier_cut: float
    cut: float                   # after the cap and the margin floor
    new_price: float | None
    reason: str                  # cut | cut-median-capped | cut-long-stale | floor-limited | under-floor | no-cost | not-past
    group: str = ""              # which part of the store the product comes from
    clock: str = "since listing" # what item.age_days measures: "since listing" or "since last sale"


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


def propose(item: Overdue, median: int | None, max_cut: float, min_margin: float,
            group: str = "", clock: str = "since listing") -> Proposal:
    price = item.row.price
    median_capped = median is None
    if median is None:
        median = MEDIAN_CAP_DAYS
    past = item.age_days - median
    long_stale = item.age_days >= LONG_STALE_DAYS
    if past <= 0 and not long_stale:
        return Proposal(item, median, past, 0.0, 0.0, None, "not-past", group, clock)
    if long_stale:
        tier_cut = cut = LONG_STALE_CUT          # the owner's rule: 400 days with no sale, full 20%
    else:
        tier_cut = next(c for limit, c in TIERS if past <= limit)
        cut = min(tier_cut, max_cut)
    if item.cost is None:
        return Proposal(item, median, past, tier_cut, cut, None, "no-cost", group, clock)
    margin_floor = item.cost / (1.0 - min_margin)
    cap_floor = price * (1.0 - cut)              # the rounding may never cut deeper than the rule says
    if price < margin_floor - 1e-9:
        return Proposal(item, median, past, tier_cut, 0.0, None, "under-floor", group, clock)
    # the rule's target, then the first .49/.99 ending that respects BOTH floors
    target = max(price * (1.0 - cut), margin_floor, cap_floor)
    new_price = up_to_ending(target)
    reason = "floor-limited" if margin_floor > price * (1.0 - cut) + 1e-9 else "cut"
    if reason == "cut" and long_stale:
        reason = "cut-long-stale"
    elif reason == "cut" and median_capped:
        reason = "cut-median-capped"
    if new_price >= price - 1e-9:
        return Proposal(item, median, past, tier_cut, 0.0, None, "under-floor", group, clock)
    return Proposal(item, median, past, tier_cut, (price - new_price) / price, round(new_price, 2), reason, group, clock)


GROUPS = {
    ("old", False): "listed before the order history, never sold since",
    ("old", True): "listed before the order history, sold at least once since",
    ("new", False): "listed inside the order history, never sold",
    ("new", True): "listed inside the order history, sold at least once",
}


def store_items(products: list[dict], orders: list[dict], qty: dict[str, int], cost: dict[str, float],
                snapshot: dt.date, history_start: dt.date, exclude_emails: frozenset[str] = frozenset()
                ) -> list[tuple[Overdue, str, str]]:
    """Every active product with stock on hand, with the clock the rule needs:
    days since listing for a product that has never sold, days since its last sale
    otherwise. Returns (item, group, clock)."""
    from sellthrough.cohort import Row, gid_tail, is_non_merchandise, parse_ts
    last_sale: dict[str, dt.date] = {}
    for o in orders:
        if o.get("test") or o.get("cancelled_at") or (o.get("email") or "").lower() in exclude_emails:
            continue
        d = parse_ts(o["created_at"]).date()
        for li in o.get("line_items", []):
            v = li.get("variant_id")
            if v and li.get("quantity", 0) - li.get("refunded_quantity", 0) > 0:
                last_sale[gid_tail(v)] = max(last_sale.get(gid_tail(v), d), d)
    per_day: dict[dt.date, int] = {}
    for p in products:
        for v in p["variants"]:
            d = parse_ts(v["created_at"]).date()
            per_day[d] = per_day.get(d, 0) + 1
    out = []
    for p in products:
        if p.get("status", "ACTIVE") != "ACTIVE" or is_non_merchandise(p["title"]):
            continue
        for v in p["variants"]:
            vid = gid_tail(v["id"])
            q = qty.get(vid, 0)
            if q <= 0:
                continue
            listed = parse_ts(v["created_at"]).date()
            sold = vid in last_sale
            clock_days = (snapshot - (last_sale[vid] if sold else listed)).days
            era = "old" if listed < history_start else "new"
            row = Row(vid, gid_tail(p["id"]), p["title"], tuple(p.get("tags") or ()), float(v["price"]),
                      listed, None, 0, max(clock_days, 0), per_day.get(listed, 1), snapshot)
            out.append((Overdue(row, max(clock_days, 0), float("nan"), q, cost.get(vid)),
                        GROUPS[(era, sold)], "since last sale" if sold else "since listing"))
    return out


def plan(items: list, model: DiscreteHazard, level: LevelCorrection,
         max_cut: float, min_margin: float) -> list[Proposal]:
    """items: Overdue objects, or (Overdue, group, clock) triples from store_items()."""
    out = []
    for entry in items:
        it, group, clock = entry if isinstance(entry, tuple) else (entry, "", "since listing")
        if it.stock is not None and it.stock <= 0:
            continue
        out.append(propose(it, model_median(model, it, level.offset), max_cut, min_margin, group, clock))
    order = {"cut": 0, "cut-long-stale": 0, "cut-median-capped": 0, "floor-limited": 1,
             "under-floor": 2, "no-cost": 3, "not-past": 4}
    out.sort(key=lambda p: (order[p.reason], -(p.days_past or 0)))
    return out


def write_csv(props: list[Proposal], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant_id", "product_id", "title", "group", "clock", "clock_days", "median_days",
                    "days_past_median", "on_hand", "cost", "current_price", "rule_cut", "applied_cut",
                    "new_price", "margin_after", "decision"])
        for p in props:
            it = p.item
            margin_after = "" if p.new_price is None or it.cost is None else f"{(p.new_price - it.cost) / p.new_price:.3f}"
            w.writerow([it.row.variant_id, it.row.product_id, it.row.title, p.group, p.clock, it.age_days,
                        "" if p.median_days is None else p.median_days, "" if p.days_past is None else p.days_past,
                        "" if it.stock is None else it.stock, "" if it.cost is None else f"{it.cost:.2f}",
                        f"{it.row.price:.2f}", f"{p.tier_cut:.2f}", f"{p.cut:.3f}",
                        "" if p.new_price is None else f"{p.new_price:.2f}", margin_after, p.reason])


def summary(props: list[Proposal], snapshot: dt.date, max_cut: float, min_margin: float) -> str:
    by = {}
    for p in props:
        by.setdefault(p.reason, []).append(p)
    cuts = by.get("cut", []) + by.get("cut-long-stale", []) + by.get("cut-median-capped", []) + by.get("floor-limited", [])
    cuts.sort(key=lambda p: -(p.days_past or 0))
    units = sum(p.item.stock or 0 for p in cuts)
    before = sum(p.item.row.price * (p.item.stock or 0) for p in cuts)
    after = sum((p.new_price or 0) * (p.item.stock or 0) for p in cuts)
    lines = [f"# Clearance plan, {snapshot.isoformat()} snapshot", "",
             f"Rule: 10% past the product's median selling time, 15% at 91-180 days past, 20% beyond, "
             f"capped at {100 * max_cut:.0f}% this run; any product with no sale in {LONG_STALE_DAYS} days gets "
             f"the full {100 * LONG_STALE_CUT:.0f}% regardless of the cap; never under {100 * min_margin:.0f}% "
             f"margin over cost. The clock is days since listing for a product that has never sold and days "
             f"since its last sale otherwise. Nothing here has been applied.", "",
             "| Decision | Products | Meaning |", "|---|---:|---|",
             f"| cut | {len(by.get('cut', [])):,} | tier cut applied (rounded up to a .49/.99 ending, never past the cap) |",
             f"| cut-long-stale | {len(by.get('cut-long-stale', [])):,} | no sale in {LONG_STALE_DAYS}+ days: the full {100 * LONG_STALE_CUT:.0f}% |",
             f"| cut-median-capped | {len(by.get('cut-median-capped', [])):,} | same as cut, for products whose median is beyond {MEDIAN_CAP_DAYS} days (treated as {MEDIAN_CAP_DAYS}) |",
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
    lines += ["| Rule cut | Products |", "|---|---:|"] + [f"| {100 * k:.0f}% | {v:,} |" for k, v in sorted(tiers.items())]
    groups = {}
    for p in props:
        g = groups.setdefault(p.group or "(cohort)", {"n": 0, "cut": 0, "units": 0})
        g["n"] += 1
        if p.new_price is not None:
            g["cut"] += 1; g["units"] += p.item.stock or 0
    lines += ["", "| Part of the store | Products | Proposed cuts | Units cut |", "|---|---:|---:|---:|"]
    lines += [f"| {k} | {v['n']:,} | {v['cut']:,} | {v['units']:,} |" for k, v in groups.items()]
    lines += ["", "## First 40 proposed cuts", "",
              "| Title | Clock | Days | Median | Cost | Now | Proposed | Cut | On hand |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for p in cuts[:40]:
        it = p.item
        lines.append(f"| {it.row.title[:55]} | {p.clock} | {it.age_days} | {p.median_days} | ${it.cost:.2f} | "
                     f"${it.row.price:.2f} | ${p.new_price:.2f} | {100 * p.cut:.0f}% | {it.stock} |")
    return "\n".join(lines) + "\n"
