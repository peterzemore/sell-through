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
- **Validation selects, test is scored once.** `evaluate` sweeps the model grids on the
  validation split, picks the best Cox and the best discrete-hazard config by Brier skill,
  and scores only those plus the baselines on test. Don't re-run the sweep because a test
  number looks improvable.
- **Regenerate models with** `sellthrough evaluate --bootstrap 1000 --seed 0 --update-readme`
  **and commit results/ + README together.** CI re-runs the identical command (1000 draws, seed 0;
  it takes about two seconds), checks gates.toml, compares point estimates to the committed
  results/test.json to 1e-9, and `git diff`s README.md and both results files. Timing
  fields are deliberately absent from the outputs so the diff can be exact.
- **Gates sit just under today's numbers** (skill 0.03, AUC 0.60, C 0.57, calibration gap
  0.15). Raise one only after the model already clears it.
- **Owner emails are a CLI flag at build time**, never a constant, never committed.

## Things not obvious from the code

- The design matrix drops one level per one-hot group and every column with zero variance
  in the fit set (`Vocabulary.active`). Without that, lifelines' Cox fitter divides by a
  zero standard deviation and dies on the first Newton step with "delta contains nan".
- Cox durations are `days + 0.5` because a same-day sale is day 0 and lifelines wants
  positive durations; the shift is applied to prediction times too, so S(90) is honest.
- The test window sold ~8 points faster than any earlier window and every model carried
  the old level (mean predicted 31% vs 38.6% observed). Milestone 3 must recompute the
  current base rate at serving time; do not "fix" this by refitting on test.

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

## The store report

- `sellthrough overdue --env-file <recommender's shopify.env>` uses the same read-only
  Admin app as basket-recommender; never create a new Shopify app for this. Without
  `--env-file` it runs with stock unknown.
- The level correction is a bisection on a logit offset so the model's mean 90-day
  probability on the recent window matches what happened there. If the recent 180-day
  window has fewer than 50 listings it widens to all listings with a full horizon.
- `results/overdue.md` is a report, not a protocol artifact. CI does not check it. It carries
  on-hand counts (the storefront shows availability anyway) and **never cost**: wholesale
  prices are private (Peter, 2026-09-07). The costed copy goes to `private/`, gitignored.
  Cost appeared in the public file for a few hours on 2026-09-07; history was rewritten.
- Cost comes from Shopify's `inventoryItem.unitCost` (cost per item), fetched in the same
  inventory query. VaultBooks was checked as an alternative and does not link its inventory
  items to Shopify variant ids (0 of 4,013), and its lot costs were seeded from Shopify in
  the first place, so Shopify is the source of truth for cost.
- "Gone without a recorded sale" (zero on hand, no sale) was 203 variants on the first
  run -- a quarter of unsold listings. That is a data-quality finding for the store, not a
  modelling target; do not fold it into the overdue list.

## Clearance plans

- Peter's rule (2026-09-07): 10% past the product's model median, 15% at 91-180 days past,
  20% beyond; **first run capped at 15%**; **never under 10% margin over cost**. Prices go UP
  to the next .49/.99 ending above max(tier target, cap floor, margin floor), so a rounded
  price can undershoot the tier but never breach the cap or the floor. A product whose
  corrected median lies beyond 360 days is treated as median 360 (`cut-median-capped`).
- Output goes to `private/` (gitignored) because it carries per-product cost. Applying a plan
  to the store is NOT built; when it is, it must use bundle-tools' write-capable app, run from
  Peter's machine, set compare_at_price = old price and tag `clearance`, and have a revert.

## Running it here

`.venv/bin/sellthrough ...` from the repo root. Rebuild the cohort with
`sellthrough build --products <raw>/products.jsonl --orders <raw>/orders.jsonl
--exclude-emails <the three owner addresses>`; then `describe --update-readme`.
