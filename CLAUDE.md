# sell-through -- working notes

Read the README first; it is the source of truth for the protocol and the numbers.
This file is what a session needs that the README doesn't say. Scope and milestone
plan: `~/.claude/plans/sell-through-scope.md`.

## Rules that protect the numbers

- **Every number in the README is generated** by `sellthrough describe --update-readme`
  between HTML-comment markers. Never hand-edit inside the markers. CI regenerates and
  runs `git diff --exit-code` on README.md and results/describe.json, so commit both
  together after any change that moves a number.
- **The protocol lives in `protocol.py`.** Split dates and the horizon are quoted by the
  README tables; changing them is a deliberate protocol edit, never a side effect.
- **Validation selects, test is scored once** (milestone 2 onward).
- **Owner emails are a CLI flag at build time**, never a constant, never committed.

## Things not obvious from the code

- The cohort is built from basket-recommender's raw pull (`../basket-recommender/data/raw/`),
  which came through Ada's read-only Shopify app. Do not create a new Shopify app or
  pull for this project.
- `days` is calendar-day granularity from listing date to first-sale date; a same-day
  sale is 0 days. Censored rows have `days` = snapshot - listing.
- The naive median days-to-sale over sold items (73) versus the KM median (237) is the
  headline fact; if a change moves the KM median a lot, suspect the change.
- `fit_set` censors at the origin date with a strict inequality: a sale on the origin day
  itself is not visible. `eval_set` accepts a listing with exactly 90 days of follow-up.
- Listings dated after the snapshot (the last order date) are excluded; they used to
  produce negative `days`.

## Running it here

`.venv/bin/sellthrough ...` from the repo root. Rebuild the cohort with
`sellthrough build --products <raw>/products.jsonl --orders <raw>/orders.jsonl
--exclude-emails <the three owner addresses>`; then `describe --update-readme`.
