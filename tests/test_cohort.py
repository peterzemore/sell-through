import datetime as dt

from sellthrough.cohort import build, read_cohort, write_cohort


def product(pid, vid, created, title="Thing #1", status="ACTIVE", price=12.99, tags=("A",)):
    return {"id": f"gid://shopify/Product/{pid}", "title": title, "tags": list(tags),
            "status": status, "created_at": created,
            "variants": [{"id": f"gid://shopify/ProductVariant/{vid}", "price": price, "created_at": created}]}


def order(created, vid, email=None, qty=1, refunded=0, cancelled=None, test=False):
    return {"id": "gid://shopify/Order/1", "created_at": created, "cancelled_at": cancelled, "test": test,
            "email": email, "line_items": [{"variant_id": f"gid://shopify/ProductVariant/{vid}",
                                            "quantity": qty, "refunded_quantity": refunded}]}


PRODUCTS = [
    product(1, 11, "2024-01-01T00:00:00Z"),                       # before history: left-truncated
    product(2, 22, "2024-09-10T00:00:00Z"),                       # sells day 5
    product(3, 33, "2024-09-10T00:00:00Z"),                       # never sells
    product(4, 44, "2024-09-20T00:00:00Z", title="Tip"),          # not merchandise
    product(5, 55, "2024-09-20T00:00:00Z", status="DRAFT"),       # not for sale
    product(6, 66, "2024-10-01T00:00:00Z"),                       # only "sold" to the owner / refunded
]
ORDERS = [
    order("2024-09-06T12:00:00Z", 11),
    order("2024-09-15T12:00:00Z", 22),
    order("2024-09-12T12:00:00Z", 22, cancelled="2024-09-12T13:00:00Z"),   # earlier but cancelled
    order("2024-10-05T12:00:00Z", 66, email="Owner@Example.com"),
    order("2024-10-06T12:00:00Z", 66, qty=1, refunded=1),
    order("2024-12-31T12:00:00Z", 33, test=True),
    order("2024-12-01T12:00:00Z", 11),
]


def test_build_rules():
    rows, stats = build(PRODUCTS, ORDERS, frozenset({"owner@example.com"}))
    by = {r.variant_id: r for r in rows}
    assert set(by) == {"22", "33", "66"}
    assert stats["variants_left_truncated"] == 1
    assert stats["products_non_merchandise"] == 1 and stats["products_not_active"] == 1
    assert stats["orders_cancelled"] == 1 and stats["orders_owner"] == 1 and stats["orders_test"] == 1
    assert by["22"].event == 1 and by["22"].days == 5 and by["22"].first_sale_at == dt.date(2024, 9, 15)
    snapshot = dt.date(2024, 12, 1)   # last kept order
    assert by["33"].event == 0 and by["33"].days == (snapshot - dt.date(2024, 9, 10)).days
    assert by["66"].event == 0                       # owner + refunded lines are not sales
    assert by["22"].batch_size == 2 and by["66"].batch_size == 1


def test_csv_round_trip(tmp_path):
    rows, _ = build(PRODUCTS, ORDERS, frozenset({"owner@example.com"}))
    p = tmp_path / "cohort.csv"
    write_cohort(rows, p)
    assert read_cohort(p) == rows
