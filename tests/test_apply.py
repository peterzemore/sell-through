import csv
from pathlib import Path

from sellthrough.apply import CLEARANCE_TAG, Target, apply, decide, revert


class FakeApi:
    """Just enough of ShopifyAdmin.graphql to exercise apply/revert without a store."""
    def __init__(self, variants):
        self.v = variants          # variant_id -> dict(price, compare_at, product_id, tags)
        self.calls = []

    def graphql(self, query, variables=None):
        self.calls.append(query.split("(")[0].strip().split()[-1] if "mutation" in query else "query")
        if "productVariant(" in query:
            vid = variables["id"].rsplit("/", 1)[-1]
            d = self.v.get(vid)
            if d is None:
                return {"productVariant": None}
            return {"productVariant": {"id": variables["id"], "price": f"{d['price']:.2f}",
                                       "compareAtPrice": None if d["compare_at"] is None else f"{d['compare_at']:.2f}",
                                       "product": {"id": f"gid://shopify/Product/{d['product_id']}", "tags": list(d["tags"])}}}
        if "productVariantsBulkUpdate" in query:
            for u in variables["variants"]:
                d = self.v[u["id"].rsplit("/", 1)[-1]]
                d["price"] = float(u["price"]); d["compare_at"] = None if u["compareAtPrice"] is None else float(u["compareAtPrice"])
            return {"productVariantsBulkUpdate": {"productVariants": [], "userErrors": []}}
        if "tagsAdd" in query:
            pid = variables["id"].rsplit("/", 1)[-1]
            for d in self.v.values():
                if d["product_id"] == pid and CLEARANCE_TAG not in d["tags"]:
                    d["tags"].append(CLEARANCE_TAG)
            return {"tagsAdd": {"userErrors": []}}
        if "tagsRemove" in query:
            pid = variables["id"].rsplit("/", 1)[-1]
            for d in self.v.values():
                if d["product_id"] == pid and CLEARANCE_TAG in d["tags"]:
                    d["tags"].remove(CLEARANCE_TAG)
            return {"tagsRemove": {"userErrors": []}}
        raise AssertionError(query)


def test_decide():
    t = Target("1", "p1", "x", 21.99, 17.99)
    assert decide(None, t) == "missing"
    assert decide({"price": 21.99, "compare_at": None, "product_id": "p1", "tags": []}, t) == "apply"
    assert decide({"price": 24.99, "compare_at": None, "product_id": "p1", "tags": []}, t) == "price-changed"
    assert decide({"price": 17.99, "compare_at": 21.99, "product_id": "p1", "tags": []}, t) == "already-applied"
    assert decide({"price": 21.99, "compare_at": 29.99, "product_id": "p1", "tags": []}, t) == "already-on-sale"


def test_apply_dry_run_writes_nothing_then_apply_and_revert(tmp_path):
    api = FakeApi({"1": {"price": 21.99, "compare_at": None, "product_id": "p1", "tags": ["Funko Pops!"]},
                   "2": {"price": 12.99, "compare_at": None, "product_id": "p2", "tags": []},
                   "3": {"price": 30.00, "compare_at": None, "product_id": "p3", "tags": []}})
    targets = [Target("1", "p1", "a", 21.99, 17.99), Target("2", "p2", "b", 12.99, 10.99),
               Target("3", "p3", "c", 25.00, 21.99), Target("9", "p9", "gone", 5.0, 4.49)]
    log = tmp_path / "applied.csv"
    dry = apply(api, targets, log, write=False)
    assert dry == {"would-apply": 2, "price-changed": 1, "missing": 1}
    assert api.v["1"]["price"] == 21.99 and "clearance" not in api.v["1"]["tags"]
    log2 = tmp_path / "applied2.csv"
    real = apply(api, targets, log2, write=True, limit=1)
    assert real == {"applied": 1}
    assert api.v["1"] == {"price": 17.99, "compare_at": 21.99, "product_id": "p1", "tags": ["Funko Pops!", "clearance"]}
    assert api.v["2"]["price"] == 12.99
    rows = list(csv.DictReader(log2.open()))
    assert rows[0]["status"] == "applied" and rows[0]["old_price"] == "21.99" and rows[0]["tag_added"] == "1"
    # second run is idempotent for the applied one
    again = apply(api, targets, tmp_path / "applied3.csv", write=False)
    assert again["already-applied"] == 1
    # a manual edit after apply is left alone by revert; the untouched one is reverted
    api.v["1"]["price"] = 15.99
    assert revert(api, log2, write=True) == {"changed-since": 1}
    api.v["1"]["price"] = 17.99
    assert revert(api, log2, write=True) == {"reverted": 1}
    assert api.v["1"] == {"price": 21.99, "compare_at": None, "product_id": "p1", "tags": ["Funko Pops!"]}
