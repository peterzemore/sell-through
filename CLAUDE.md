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

- Peter's rule (2026-09-07): **whole store**, every in-stock product; clock = days since
  listing (never sold) or days since last sale (sold before); 10% past the product's model
  median, 15% at 91-180 days past, 20% beyond; **first run capped at 15%**; **no sale in 400
  days = the full 20% regardless of the cap**; **never under 10% margin over cost**. Products
  listed before the order history are included (the left-truncation exclusion is a modelling
  concern, not a clearance one); `store_items()` builds them from the raw pull. Prices go UP
  to the next .49/.99 ending above max(tier target, cap floor, margin floor), so a rounded
  price can undershoot the tier but never breach the cap or the floor. A product whose
  corrected median lies beyond 360 days is treated as median 360 (`cut-median-capped`).
- Output goes to `private/` (gitignored) because it carries per-product cost.
- `apply` uses **bundle-tools' write-capable app** (`~/Projects/business/PeteZ PopZ/bundle-tools/.env`,
  `write_products`). Since 2026-09-09 it also runs weekly from **Otto** (`~/Projects/business/PeteZ PopZ/Otto`,
  `otto.timer`, Mondays 05:00): pull -> clearance -> dry run -> apply if under a hold threshold -> #otto-updates.
  Peter asked for that ("semi-continuous pricing"); the earlier "never from a service" rule is retired. Dry run by default;
  `--yes` writes; `--limit N` for a pilot batch. Each product is re-read first: `price-changed`
  (live price != plan) and `already-on-sale` (a compare-at above the plan price) are skipped, so
  a plan can be applied days after it was written without clobbering manual edits. Logs land in
  `private/applied-<stamp>.csv`; `revert --log` undoes only rows whose live price still equals
  what apply set. Reading 2,219 products one by one takes ~12 minutes; that is deliberate
  (per-product safety check) -- do not batch it away.
- Shopify admin side (manual, once): Products > Collections > Create > Automated, condition
  "Product tag is equal to clearance"; then Online Store > Navigation > add the collection to
  the main menu. The theme already renders compare-at strike-through prices.

## Running it here

`.venv/bin/sellthrough ...` from the repo root. Rebuild the cohort with
`sellthrough build --products <raw>/products.jsonl --orders <raw>/orders.jsonl
--exclude-emails <the three owner addresses>`; then `describe --update-readme`.

## State of the live store (as of 2026-09-07 night)

- Clearance plan v2 APPLIED: pilot of 25 (`private/applied-20260907-174245.csv`) then the rest
  (`private/applied-20260907-200844.csv`, 2,186). 7 skipped as price-changed, 1 already-on-sale.
  Four products reverted at Peter's request via `revert --title-contains` (Clark Griswold #242,
  Cousin Eddie, Derpy with Sussie, Courage the Cowardly Dog #1070). Net ~2,207 tagged `clearance`.
- Collection: title **ON-SALE**, handle `on-sale` (renamed from Clearance), automated on tag
  `clearance`, published to Online Store by Peter, menu link added. The TAG stays `clearance`.
- Next pass: after the next inventory count; Peter intends to lift the 15% cap then. Re-run
  `clearance` -> read `private/clearance_plan.md` -> `apply --limit` pilot -> `apply`.
- `apply --yes` over the whole plan was blocked by the assistant's permission layer; Peter ran it
  himself with the `!` prefix. Expect the same next time.

## Loungefly ceilings (Peter, 2026-09-08)

- **Loungefly bags/wallets never go past 12% off; the horror/Halloween lines (Pennywise, Nightmare
  Before Christmas, Hocus Pocus, Chucky, Coraline, Beetlejuice, Disney Villains, Halloween-themed
  Mickey/Pooh, ...) never past 10%.** Hard ceilings in `clearance.py` (`product_max_cut()`,
  `LOUNGEFLY_HORROR_RE`) that beat the tier, the run cap AND the 400-day long-stale rule.
  Matched on title; the regex is deliberately broad on Halloween words - if a non-horror bag gets
  the 10% cap that's the safe direction.
- The 2026-09-07 run had already cut 60 Loungefly items past those caps (most at the 20% long-stale
  cut). `private/reprice_loungefly_caps.py --apply` raised them back to the ceiling the same day;
  log in `private/applied-loungefly-caps-20260908-110444.csv`. Compare-at and the `clearance` tag
  were left alone. **`revert` will skip those 60** (their live price no longer equals the original
  applied CSV's `new_price`) - to revert them use the loungefly-caps CSV's `old_price`.
- **Same day, second pass:** the Pennywise Raincoat backpack showed the title-only match was too
  narrow - 50 more applied cuts were Loungefly-line bags listed without the brand word. `LOUNGEFLY_RE`
  now also matches the product-line words (mini-backpack, crossbody, crossbuddies, zip-around,
  cosplay/bifold wallet, figural/double-strap/convertible backpack) and `OTHER_BAG_BRANDS_RE`
  excludes Danielle Nicole / WondaPOP / Our Universe etc. unless "Loungefly" is in the text. 45 more
  re-priced (`private/applied-loungefly-caps-20260908-113128.csv`). Every product the rule matches now
  carries the tag `loungefly`; the storefront collection **Loungefly Sale** (`loungefly-sale`) is
  automated on tag=clearance AND tag=loungefly. New Loungefly listings need that tag to show up there.

## Weekly runs: original price, deepening, opt-out (found on Otto's first dry run, 2026-09-09)

- The plan works from the **original price**: `fetch_inventory` now returns compare-at prices too, and
  `store_items(..., compare_at=)` uses compare-at as the rule's price when it is above the live price. Before this,
  a second run started from the already-reduced price and proposed another 20% on top (10.49 -> 8.49); only
  apply's "already-on-sale" guard stood in the way, and the same guard blocked legitimate deeper tiers.
- `apply.decide()` compares against that original price: `already-applied` when live price == plan and the
  compare-at is the original; **`apply` also when a product sits at a shallower markdown from the same original**
  (the tier deepened as it aged); `price-changed` when the original moved or someone cut deeper by hand;
  `already-on-sale` when a higher compare-at was set by hand. A hand-RAISED sale price with the compare-at left in
  place will be re-cut by the next run - use the tag below for products that must not move.
- **Tag `no-clearance`** on a product keeps it out of every plan (`clearance.EXCLUDE_TAG`). Applied 2026-09-09 to
  the four products Peter had reverted on 09-07 (Clark Griswold #242, Cousin Eddie, Derpy with Sussie, Courage
  #1070) - the first Otto dry run would have re-cut them.
- The plan CSV's `current_price` column is therefore the original price, not the live one.
