"""Apply an approved clearance plan to the store, and revert one.

Deliberately narrow and reversible:
  - only rows the plan marked as a cut are touched;
  - each product is re-read first, and skipped if its live price no longer matches the
    plan (someone changed it since), or if the plan is already applied;
  - the old price becomes compareAtPrice (the storefront's strike-through), the new price
    is set, and a `clearance` tag is added -- nothing else on the product changes;
  - every write is logged to a CSV that `revert` reads to put prices back and drop the tag,
    again only where the live price still equals what apply set.
Requires a write-capable Admin API app (write_products); pass its env file explicitly.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from sellthrough.stock import ShopifyAdmin

CLEARANCE_TAG = "clearance"

VARIANT_QUERY = """
query($id: ID!) { productVariant(id: $id) { id price compareAtPrice product { id tags } } }"""
PRICE_MUTATION = """
mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price compareAtPrice }
    userErrors { field message }
  }
}"""
TAG_ADD = """mutation($id: ID!, $tags: [String!]!) { tagsAdd(id: $id, tags: $tags) { userErrors { field message } } }"""
TAG_REMOVE = """mutation($id: ID!, $tags: [String!]!) { tagsRemove(id: $id, tags: $tags) { userErrors { field message } } }"""

APPLY_COLUMNS = ["applied_at", "variant_id", "product_id", "title", "old_price", "old_compare_at",
                 "new_price", "tag_added", "status"]


def vgid(variant_id: str) -> str:
    return f"gid://shopify/ProductVariant/{variant_id}"


def pgid(product_id: str) -> str:
    return f"gid://shopify/Product/{product_id}"


def _money(x) -> float | None:
    return None if x in (None, "") else float(x)


@dataclass
class Target:
    variant_id: str
    product_id: str
    title: str
    plan_price: float      # what the plan believed the current price was
    new_price: float


def read_plan(path: Path) -> list[Target]:
    out = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("new_price"):
                continue
            out.append(Target(r["variant_id"], r["product_id"], r["title"],
                              float(r["current_price"]), float(r["new_price"])))
    return out


def read_variant(api: ShopifyAdmin, variant_id: str) -> dict | None:
    d = api.graphql(VARIANT_QUERY, {"id": vgid(variant_id)})["productVariant"]
    if not d:
        return None
    return {"price": float(d["price"]), "compare_at": _money(d.get("compareAtPrice")),
            "product_id": d["product"]["id"].rsplit("/", 1)[-1], "tags": list(d["product"]["tags"] or [])}


def set_price(api: ShopifyAdmin, product_id: str, variant_id: str, price: float, compare_at: float | None) -> None:
    variables = {"productId": pgid(product_id),
                 "variants": [{"id": vgid(variant_id), "price": f"{price:.2f}",
                               "compareAtPrice": None if compare_at is None else f"{compare_at:.2f}"}]}
    errors = api.graphql(PRICE_MUTATION, variables)["productVariantsBulkUpdate"]["userErrors"]
    if errors:
        raise RuntimeError(f"price update rejected: {errors}")


def add_tag(api: ShopifyAdmin, product_id: str) -> None:
    errors = api.graphql(TAG_ADD, {"id": pgid(product_id), "tags": [CLEARANCE_TAG]})["tagsAdd"]["userErrors"]
    if errors:
        raise RuntimeError(f"tagsAdd rejected: {errors}")


def remove_tag(api: ShopifyAdmin, product_id: str) -> None:
    errors = api.graphql(TAG_REMOVE, {"id": pgid(product_id), "tags": [CLEARANCE_TAG]})["tagsRemove"]["userErrors"]
    if errors:
        raise RuntimeError(f"tagsRemove rejected: {errors}")


def decide(live: dict | None, t: Target) -> str:
    """What apply should do for one target, given the live variant."""
    if live is None:
        return "missing"
    if abs(live["price"] - t.new_price) < 0.005 and live["compare_at"] is not None \
            and abs(live["compare_at"] - t.plan_price) < 0.005:
        return "already-applied"
    if abs(live["price"] - t.plan_price) >= 0.005:
        return "price-changed"
    if live["compare_at"] is not None and live["compare_at"] > t.plan_price + 0.005:
        return "already-on-sale"     # someone set a compare-at above the plan's price; leave it alone
    return "apply"


def apply(api: ShopifyAdmin, targets: list[Target], log_path: Path, write: bool, limit: int | None = None,
          progress=print) -> dict:
    counts: dict[str, int] = {}
    done = 0
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not log_path.exists()
    with log_path.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(APPLY_COLUMNS)
        for t in targets:
            if limit is not None and done >= limit:
                break
            live = read_variant(api, t.variant_id)
            action = decide(live, t)
            status = action
            tag_added = False
            if action == "apply" and write:
                set_price(api, t.product_id, t.variant_id, t.new_price, t.plan_price)
                if CLEARANCE_TAG not in live["tags"]:
                    add_tag(api, t.product_id)
                    tag_added = True
                status = "applied"
                done += 1
            elif action == "apply":
                status = "would-apply"
                done += 1
            counts[status] = counts.get(status, 0) + 1
            if status in ("applied", "would-apply"):
                w.writerow([dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), t.variant_id,
                            t.product_id, t.title, f"{t.plan_price:.2f}",
                            "" if live["compare_at"] is None else f"{live['compare_at']:.2f}",
                            f"{t.new_price:.2f}", int(tag_added), status])
            if (sum(counts.values())) % 100 == 0:
                progress(f"  {sum(counts.values())} checked: {counts}")
    return counts


def revert(api: ShopifyAdmin, log_path: Path, write: bool, progress=print) -> dict:
    counts: dict[str, int] = {}
    with log_path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "applied"]
    for r in rows:
        live = read_variant(api, r["variant_id"])
        if live is None:
            status = "missing"
        elif abs(live["price"] - float(r["new_price"])) >= 0.005:
            status = "changed-since"      # a later manual edit; not ours to undo
        else:
            status = "reverted" if write else "would-revert"
            if write:
                set_price(api, r["product_id"], r["variant_id"], float(r["old_price"]), _money(r["old_compare_at"]))
                if r["tag_added"] == "1":
                    remove_tag(api, r["product_id"])
        counts[status] = counts.get(status, 0) + 1
    return counts
