from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sellthrough import paths
from sellthrough.cohort import build, read_cohort, write_cohort
from sellthrough.report import describe, dump, update_readme


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
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
