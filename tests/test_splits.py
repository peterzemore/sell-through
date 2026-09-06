import datetime as dt

from sellthrough.cohort import Row
from sellthrough.splits import eval_set, fit_set, label

SNAP = dt.date(2026, 9, 5)


def row(listed, event, days, vid="1"):
    return Row(vid, "p", "t", (), 9.99, listed, listed + dt.timedelta(days=days) if event else None,
               event, days, 1, SNAP)


def test_fit_set_cannot_see_past_the_origin():
    origin = dt.date(2026, 1, 1)
    early_sale = row(dt.date(2025, 12, 1), 1, 10)      # sold 12-11: visible
    late_sale = row(dt.date(2025, 12, 1), 1, 60)       # sold 01-30: after origin, must be censored
    after = row(dt.date(2026, 1, 1), 1, 3)              # listed on the origin day: not in fit set
    fit = fit_set([early_sale, late_sale, after], origin)
    assert len(fit) == 2
    assert fit[0].event == 1 and fit[0].days == 10
    assert fit[1].event == 0 and fit[1].days == 31 and fit[1].first_sale_at is None


def test_eval_set_needs_full_horizon_and_window():
    origin, end = dt.date(2026, 1, 1), dt.date(2026, 6, 7)
    inside = row(dt.date(2026, 3, 1), 1, 100)
    too_late = row(dt.date(2026, 6, 8), 1, 1)
    too_fresh = row(dt.date(2026, 6, 7), 0, 90)          # exactly 90 days of follow-up: allowed
    before = row(dt.date(2025, 12, 31), 1, 1)
    ev = eval_set([inside, too_late, too_fresh, before], origin, end)
    assert ev == [inside, too_fresh]
    assert label(inside) == 0 and label(row(dt.date(2026, 3, 1), 1, 90)) == 1
