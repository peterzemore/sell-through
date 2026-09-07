import datetime as dt

from sellthrough.clearance import MEDIAN_CAP_DAYS, propose, up_to_ending
from sellthrough.cohort import Row
from sellthrough.overdue import Overdue

SNAP = dt.date(2026, 9, 5)


def item(price, cost, age, stock=3):
    r = Row("v", "p", "Thing", (), price, SNAP - dt.timedelta(days=age), None, 0, age, 1, SNAP)
    return Overdue(r, age, 0.9, stock, cost)


def test_price_endings():
    assert up_to_ending(17.50) == 17.99 and up_to_ending(17.99) == 17.99
    assert up_to_ending(17.10) == 17.49 and up_to_ending(17.49) == 17.49 and up_to_ending(18.00) == 18.49


def test_tiers_cap_and_floor():
    # 60 days past median -> 10% tier: 21.99 -> 19.79 -> next ending 19.99 (9.1% off)
    p = propose(item(21.99, 6.45, 260), median=200, max_cut=0.15, min_margin=0.10)
    assert p.reason == "cut" and p.tier_cut == 0.10 and p.new_price == 19.99
    # 120 days past -> 15% tier: 21.99 -> 18.69 -> 18.99 (13.6%)
    p = propose(item(21.99, 6.45, 320), median=200, max_cut=0.15, min_margin=0.10)
    assert p.tier_cut == 0.15 and p.new_price == 18.99
    # 200 days past -> 20% tier, capped at 15%: same as above, and never past the cap
    p = propose(item(21.99, 6.45, 400), median=200, max_cut=0.15, min_margin=0.10)
    assert p.tier_cut == 0.20 and p.cut <= 0.15 + 1e-9 and p.new_price == 18.99
    # the rounding must never breach the cap: 13.99 * 0.85 = 11.89 -> 11.99, not 10.99
    p = propose(item(13.99, 6.90, 700), median=70, max_cut=0.15, min_margin=0.10)
    assert p.new_price == 11.99 and p.cut <= 0.15 + 1e-9
    # margin floor bites: 12.99 with cost 11.00 -> floor 12.22 -> 12.49 is still a cut, floor-limited
    p = propose(item(12.99, 11.00, 400), median=200, max_cut=0.15, min_margin=0.10)
    assert p.reason == "floor-limited" and p.new_price == 12.49
    # already under the floor: 12.49 with cost 11.50 -> floor 12.78 > price
    p = propose(item(12.49, 11.50, 400), median=200, max_cut=0.15, min_margin=0.10)
    assert p.reason == "under-floor" and p.new_price is None


def test_no_cost_not_past_unknown():
    assert propose(item(20.0, None, 400), 200, 0.15, 0.10).reason == "no-cost"
    assert propose(item(20.0, 5.0, 100), 200, 0.15, 0.10).reason == "not-past"
    capped = propose(item(20.0, 5.0, 400), None, 0.15, 0.10)
    assert capped.reason == "cut-median-capped" and capped.median_days == MEDIAN_CAP_DAYS and capped.days_past == 40
    assert propose(item(20.0, 5.0, 300), None, 0.15, 0.10).reason == "not-past"
