"""Build the variant-level cohort from a raw Shopify pull (products.jsonl + orders.jsonl).

One row per variant listed on or after the first day of order history. Origin is the
listing time, the event is the first sale, and rows without a sale are censored at the
snapshot date. Nothing customer-shaped survives into the output: no emails, no customer
ids, no order ids.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Iterable

FIELDS = ["variant_id", "product_id", "title", "tags", "price", "listed_at",
          "first_sale_at", "event", "days", "batch_size", "snapshot"]


@dataclass(frozen=True)
class Row:
    variant_id: str
    product_id: str
    title: str
    tags: tuple[str, ...]
    price: float
    listed_at: dt.date
    first_sale_at: dt.date | None
    event: int          # 1 = first sale observed, 0 = censored
    days: int           # days from listing to first sale, or to censoring
    batch_size: int     # variants listed the same calendar day (bulk-listing flag)
    snapshot: dt.date


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def gid_tail(gid: str) -> str:
    return gid.rsplit("/", 1)[-1]


def is_non_merchandise(title: str) -> bool:
    t = title.strip().lower()
    return t == "tip" or "gift card" in t


def build(products: Iterable[dict], orders: Iterable[dict],
          exclude_emails: frozenset[str] = frozenset()) -> tuple[list[Row], dict]:
    stats: collections.Counter = collections.Counter()
    kept: list[tuple[dict, dt.datetime]] = []
    for o in orders:
        if o.get("test"):
            stats["orders_test"] += 1
            continue
        if o.get("cancelled_at"):
            stats["orders_cancelled"] += 1
            continue
        if (o.get("email") or "").lower() in exclude_emails:
            stats["orders_owner"] += 1
            continue
        kept.append((o, parse_ts(o["created_at"])))
    if not kept:
        raise ValueError("no usable orders")
    history_start = min(t for _, t in kept).date()
    snapshot = max(t for _, t in kept).date()

    first_sale: dict[str, dt.date] = {}
    for o, t in kept:
        for li in o.get("line_items", []):
            v = li.get("variant_id")
            if not v:
                stats["lines_no_variant"] += 1
                continue
            if li.get("quantity", 0) - li.get("refunded_quantity", 0) <= 0:
                stats["lines_fully_refunded"] += 1
                continue
            d = t.date()
            if v not in first_sale or d < first_sale[v]:
                first_sale[v] = d

    per_day: collections.Counter = collections.Counter()
    candidates: list[tuple[dict, dict, dt.date]] = []
    for p in products:
        if p.get("status", "ACTIVE") != "ACTIVE":
            stats["products_not_active"] += 1
            continue
        if is_non_merchandise(p["title"]):
            stats["products_non_merchandise"] += 1
            continue
        for v in p["variants"]:
            listed = parse_ts(v["created_at"]).date()
            if listed < history_start:
                stats["variants_left_truncated"] += 1
                continue
            if listed > snapshot:
                stats["variants_listed_after_snapshot"] += 1
                continue
            per_day[listed] += 1
            candidates.append((p, v, listed))

    rows: list[Row] = []
    for p, v, listed in candidates:
        fs = first_sale.get(v["id"])
        if fs is not None and fs < listed:
            stats["variants_sold_before_listed"] += 1
            continue
        event = int(fs is not None)
        days = (fs - listed).days if fs is not None else (snapshot - listed).days
        rows.append(Row(
            variant_id=gid_tail(v["id"]), product_id=gid_tail(p["id"]), title=p["title"],
            tags=tuple(p.get("tags") or ()), price=float(v["price"]), listed_at=listed,
            first_sale_at=fs, event=event, days=days, batch_size=per_day[listed],
            snapshot=snapshot,
        ))
    rows.sort(key=lambda r: (r.listed_at, r.variant_id))
    out = dict(stats)
    out.update({
        "history_start": history_start.isoformat(), "snapshot": snapshot.isoformat(),
        "orders_kept": len(kept), "cohort_variants": len(rows),
        "cohort_events": sum(r.event for r in rows),
    })
    return rows, dict(sorted(out.items()))


def write_cohort(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow([r.variant_id, r.product_id, r.title, "|".join(r.tags), f"{r.price:.2f}",
                        r.listed_at.isoformat(), r.first_sale_at.isoformat() if r.first_sale_at else "",
                        r.event, r.days, r.batch_size, r.snapshot.isoformat()])


def read_cohort(path: Path) -> list[Row]:
    rows: list[Row] = []
    with path.open(newline="") as f:
        rd = csv.DictReader(f)
        if rd.fieldnames != FIELDS:
            raise ValueError(f"unexpected columns in {path}: {rd.fieldnames}")
        for d in rd:
            rows.append(Row(
                variant_id=d["variant_id"], product_id=d["product_id"], title=d["title"],
                tags=tuple(t for t in d["tags"].split("|") if t), price=float(d["price"]),
                listed_at=dt.date.fromisoformat(d["listed_at"]),
                first_sale_at=dt.date.fromisoformat(d["first_sale_at"]) if d["first_sale_at"] else None,
                event=int(d["event"]), days=int(d["days"]), batch_size=int(d["batch_size"]),
                snapshot=dt.date.fromisoformat(d["snapshot"]),
            ))
    return rows


__all__ = ["FIELDS", "Row", "build", "write_cohort", "read_cohort", "replace", "fields"]
