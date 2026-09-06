from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    """Directory holding data/ and results/. Override with SELLTHROUGH_ROOT when the
    package is installed somewhere other than a checkout."""
    env = os.environ.get("SELLTHROUGH_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def cohort_path() -> Path:
    return root() / "data" / "cohort.csv"


def stats_path() -> Path:
    return root() / "data" / "clean_stats.json"


def results_path() -> Path:
    return root() / "results" / "describe.json"


def readme_path() -> Path:
    return root() / "README.md"
