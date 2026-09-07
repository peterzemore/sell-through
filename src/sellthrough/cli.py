from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sellthrough import paths
from sellthrough.cohort import build, read_cohort, write_cohort
from sellthrough.report import describe, dump, update_block, update_readme


def _jsonl(p: Path):
    with p.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def cmd_build(a: argparse.Namespace) -> int:
    emails = frozenset(e.strip().lower() for e in (a.exclude_emails or "").split(",") if e.strip())
    rows, stats = build(_jsonl(Path(a.products)), _jsonl(Path(a.orders)), emails)
    write_cohort(rows, paths.cohort_path())
    paths.stats_path().write_text(json.dumps(stats, indent=2) + "\n")
    print(f"cohort: {len(rows):,} variants, {stats['cohort_events']:,} sold -> {paths.cohort_path()}")
    return 0


def cmd_describe(a: argparse.Namespace) -> int:
    rows = read_cohort(paths.cohort_path())
    stats = json.loads(paths.stats_path().read_text())
    d = describe(rows, stats)
    dump(d, paths.results_path())
    o = d["overall"]
    print(f"{d['cohort_variants']:,} listings, {d['ever_sold']:,} sold; "
          f"KM sold by day {d['horizon_days']}: {100 * o[f'sold_by_{d['horizon_days']}']:.1f}%")
    if a.update_readme:
        update_readme(paths.readme_path(), d)
        print(f"README updated: {paths.readme_path()}")
    return 0


def cmd_evaluate(a: argparse.Namespace) -> int:
    from sellthrough.evaluate import evaluate, render_results
    rows = read_cohort(paths.cohort_path())
    val, test = evaluate(rows, draws=a.bootstrap, seed=a.seed, out_dir=paths.root() / "results")
    best = max(test["results"], key=lambda r: r["brier_skill"])
    print(f"val chose {val['chosen']}; test best: {best['model']} skill {best['brier_skill']:+.3f} auc {best['auc']:.3f}")
    if a.update_readme:
        text = paths.readme_path().read_text()
        paths.readme_path().write_text(update_block(text, "results", render_results(val, test)))
        print(f"README updated: {paths.readme_path()}")
    return 0


def cmd_gate(a: argparse.Namespace) -> int:
    from sellthrough.gate import check, load, load_gates
    test = load(paths.root() / "results" / "test.json")
    committed = load(Path(a.committed)) if a.committed else None
    fails = check(test, load_gates(paths.root() / "gates.toml"), committed)
    for f in fails:
        print(f"GATE FAIL: {f}")
    print("gates: " + ("FAIL" if fails else "pass"))
    return 1 if fails else 0


def cmd_overdue(a: argparse.Namespace) -> int:
    from sellthrough.overdue import Overdue, render, score_unsold
    from sellthrough.stock import ShopifyAdmin, fetch_inventory, read_env_file
    rows = read_cohort(paths.cohort_path())
    stock = cost = None
    if a.env_file:
        api = ShopifyAdmin.from_env(read_env_file(Path(a.env_file)))
        stock, cost = fetch_inventory(api)
        print(f"live stock: {len(stock):,} variants, cost per item on {len(cost):,}")
    items, level, _ = score_unsold(rows, stock, min_days=a.min_days, cost=cost)
    # The committed report never carries cost: wholesale prices are private. The costed
    # version, when cost is available, goes to private/ (gitignored).
    public = [Overdue(o.row, o.age_days, o.p_sold_by_now, o.stock, None) for o in items]
    out = Path(a.out) if a.out else paths.root() / "results" / "overdue.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(public, level, rows[0].snapshot, a.top, stock is not None))
    if cost:
        priv = paths.root() / "private" / "overdue_with_cost.md"
        priv.parent.mkdir(parents=True, exist_ok=True)
        priv.write_text(render(items, level, rows[0].snapshot, a.top, True))
        print(f"costed report (private): {priv}")
    print(f"level: observed {100 * level.observed:.1f}% vs model {100 * level.predicted_before:.1f}% -> offset {level.offset:+.3f}")
    print(f"{len(items):,} unsold listings scored -> {out}")
    return 0


def cmd_clearance(a: argparse.Namespace) -> int:
    from sellthrough.clearance import plan, summary, write_csv
    from sellthrough.overdue import score_unsold
    from sellthrough.stock import ShopifyAdmin, fetch_inventory, read_env_file
    rows = read_cohort(paths.cohort_path())
    api = ShopifyAdmin.from_env(read_env_file(Path(a.env_file)))
    stock, cost = fetch_inventory(api)
    items, level, model = score_unsold(rows, stock, min_days=a.min_days, cost=cost)
    props = plan(items, model, level, max_cut=a.max_cut, min_margin=a.min_margin)
    out_dir = Path(a.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(props, out_dir / "clearance_plan.csv")
    (out_dir / "clearance_plan.md").write_text(summary(props, rows[0].snapshot, a.max_cut, a.min_margin))
    n_cut = sum(1 for p in props if p.new_price is not None)
    print(f"{len(props):,} on-shelf products considered, {n_cut:,} proposed cuts -> {out_dir}/clearance_plan.{{csv,md}}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sellthrough")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build data/cohort.csv from a raw Shopify pull")
    b.add_argument("--products", required=True)
    b.add_argument("--orders", required=True)
    b.add_argument("--exclude-emails", help="comma-separated owner/staff emails whose orders are not demand")
    b.set_defaults(fn=cmd_build)
    d = sub.add_parser("describe", help="Kaplan-Meier tables and split sizes from the committed cohort")
    d.add_argument("--update-readme", action="store_true")
    d.set_defaults(fn=cmd_describe)
    e = sub.add_parser("evaluate", help="validation sweep, selection, single test scoring")
    e.add_argument("--bootstrap", type=int, default=1000)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--update-readme", action="store_true")
    e.set_defaults(fn=cmd_evaluate)
    g = sub.add_parser("gate", help="check results/test.json against gates.toml (and a committed copy for drift)")
    g.add_argument("--committed", help="path to the committed test.json to compare point estimates against")
    g.set_defaults(fn=cmd_gate)
    o = sub.add_parser("overdue", help="rank unsold listings by how overdue they are; live stock with --env-file")
    o.add_argument("--env-file", help="SHOPIFY_STORE / SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET (read-only app)")
    o.add_argument("--top", type=int, default=40)
    o.add_argument("--min-days", type=int, default=30)
    o.add_argument("--out", help="default results/overdue.md")
    o.set_defaults(fn=cmd_overdue)
    c = sub.add_parser("clearance", help="write a clearance price plan (no store writes)")
    c.add_argument("--env-file", required=True)
    c.add_argument("--max-cut", type=float, default=0.15)
    c.add_argument("--min-margin", type=float, default=0.10)
    c.add_argument("--min-days", type=int, default=30)
    c.add_argument("--out-dir", default="private", help="kept out of git by default")
    c.set_defaults(fn=cmd_clearance)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
