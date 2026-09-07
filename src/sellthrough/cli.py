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
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
