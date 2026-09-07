import numpy as np

from sellthrough.overdue import fit_level, recent_window, render, score_unsold, sold_by_with_offset
from sellthrough.models import DiscreteHazard
from tests.test_models import make_rows


def test_level_correction_hits_the_observed_rate_and_is_monotone():
    rows = make_rows(600)
    model = DiscreteHazard(l2=1.0).fit(rows)
    window = recent_window(rows, days=10000)  # synthetic rows share one listing date
    level = fit_level(model, window)
    assert abs(level.predicted_after - level.observed) < 1e-3
    p_lo = sold_by_with_offset(model, rows[:20], 90, -1.0)
    p_hi = sold_by_with_offset(model, rows[:20], 90, +1.0)
    assert np.all(p_lo < p_hi)


def test_unsold_scores_rise_with_age_and_render():
    rows = make_rows(600)
    items, level, model = score_unsold(rows, stock=None, min_days=1)
    assert all(o.row.event == 0 for o in items)
    assert items == sorted(items, key=lambda o: (-o.p_sold_by_now, -o.age_days))
    same = [o for o in items if o.row.price < 15]
    young = min(same, key=lambda o: o.age_days); old = max(same, key=lambda o: o.age_days)
    assert old.p_sold_by_now >= young.p_sold_by_now
    text = render(items, level, rows[0].snapshot, top=5, stock_known=False)
    assert "Overdue listings" in text and "unknown" in text
    # a variant absent from the stock map counts as zero on hand (deleted or gone), so
    # the test map must cover every listing to mean "these three are gone, the rest are not"
    stock = {r.variant_id: 4 for r in rows}
    stock.update({o.row.variant_id: 0 for o in items[:3]})
    with_stock = score_unsold(rows, stock=stock, min_days=1)[0]
    text2 = render(with_stock, level, rows[0].snapshot, top=5, stock_known=True)
    assert "Gone without a recorded sale (3)" in text2


def test_cost_columns_and_capital_summary():
    rows = make_rows(300)
    stock = {r.variant_id: 2 for r in rows}
    cost = {r.variant_id: round(r.price * 0.4, 2) for r in rows}
    items, level, _ = score_unsold(rows, stock=stock, min_days=1, cost=cost)
    o = items[0]
    assert o.cost is not None and abs(o.margin - (o.row.price - o.cost)) < 1e-9
    assert abs(o.margin_pct - 0.6) < 0.02
    text = render(items, level, rows[0].snapshot, top=5, stock_known=True)
    assert "What is sitting there" in text and "| Cost | Margin |" in text
    # without cost the columns are absent and nothing breaks
    items2, level2, _ = score_unsold(rows, stock=stock, min_days=1)
    assert "| Cost |" not in render(items2, level2, rows[0].snapshot, top=5, stock_known=True)
