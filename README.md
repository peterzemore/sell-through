# sell-through

> **Write-up:** [The number the store would have used was wrong by a factor of three.](docs/writeup.md)

How long does a newly listed item take to sell? For a real retail store, treated as
what it is: right-censored time-to-event data, with a protocol stated before any model
was written.

The store is a Funko Pop shop with about a hundred orders a month. The data is its
actual listings and order history, reduced to one customer-free row per listing and
committed to this repo, so everything here runs from a clean clone with no credentials.
Every number in this README is computed from that file by `sellthrough describe`; CI
regenerates them on every push and fails if the committed text drifts.

**Status: complete (3 of 3).** Cohort, protocol, Kaplan-Meier baselines, two model
families evaluated on a pre-registered rolling-origin split with a regression gate in CI,
and a store-facing overdue-listings report with a serving-time level correction and live
stock.

## The question

For a variant listed today, what is the probability it sells within 90 days, and which
items on the shelf are now past the point where they should have sold? The first is a
survival curve; the second is the same curve read backwards against each item's time on
the shelf. The store uses the answer for markdowns and for pricing walk-in collection
buys.

## The data

<!-- data-table:start -->
| | |
|---|---|
| Order history | 2024-09-06 to 2026-09-05 (2,878 orders kept) |
| Listings excluded | 6,102 variants listed before the order history begins (left-truncated); 5 listed after the snapshot |
| Cohort | 2,060 variants listed inside the history window, on 191 distinct days |
| Ever sold by the snapshot | 997 (48.4%); the rest are censored, not failures |
| Sold within 90 days, crude | 32.3% of the 1,588 variants with a full 90 days of follow-up |
| Sold within 90 days, Kaplan-Meier | 31.1% [29.0, 33.3], using every listing |
| Bulk listing days | 7 days with 40+ listings carry 22.6% of the cohort |
| Cleaning | cancelled 76, test 0, owner 4 orders; 71 fully refunded lines; 10 draft products; 1 tip/gift-card products |
<!-- data-table:end -->

Three things about this data decided the design:

- **A naive "median days to first sale" is badly wrong here.** Averaging over the items
  that sold gives 73 days. Counting the items that have *not* sold yet as what they are,
  censored observations rather than missing ones, the Kaplan-Meier median is over three
  times longer. Half of what the store lists has still not sold at eight months. This is
  the whole reason to use survival methods rather than a filter on sold items.
- **The event is the first sale, so stock is not a confound.** A just-listed item is in
  stock by construction. The companion recommender project could not see whether an
  item was on the shelf when it was not bought; this project does not have that problem
  for the first sale, and deliberately does not ask the second question ("when does it
  sell out?") because there is no stock history to answer it.
- **Listings arrive in bulk.** Seven days account for over a fifth of the cohort, which
  is what buying a private collection or receiving a shipment looks like. The size of an
  item's listing day is kept as a column so a model can use it and a reader can see it.

## Protocol, fixed before modelling

- **Unit:** a variant. **Origin:** its Shopify listing time. **Event:** the first
  non-cancelled, non-test order containing it with quantity greater than the refunded
  quantity, with the owner's own orders excluded. **Censoring:** at the last order date
  in the snapshot. Listings dated before the order history begins are excluded as
  left-truncated (their early sales are unobservable); listings dated after the snapshot
  have no follow-up and are excluded too.
- **Horizon:** 90 days.
- **Splits are rolling-origin, because that is how the model would be used.** At a
  prediction date you know everything before it and nothing after it. So the fit set is
  every listing before the prediction date, with its follow-up administratively censored
  *at* that date, and the evaluation set is the listings that came after it and have had
  the full 90 days to sell. Validation is used for model selection; test is scored once.

<!-- split-table:start -->
| Split | Prediction date | Listings scored | Fit set (censored at the prediction date) | Scored listings | Sold within horizon |
|---|---|---|---:|---:|---:|
| validation | 2025-07-01 | listed 2025-07-01 to 2025-12-31 | 673 (311 sales visible) | 596 | 161 (27.0%) |
| test | 2026-01-01 | listed 2026-01-01 to 2026-06-07 | 1,269 (567 sales visible) | 319 | 123 (38.6%) |
<!-- split-table:end -->

- **Metrics (milestone 2):** the primary metric is the Brier score at 90 days against
  the Kaplan-Meier null (a constant probability for every item), reported as skill,
  1 - Brier / Brier<sub>KM</sub>. Also the AUC at 90 days, Harrell's concordance over the
  full follow-up, and calibration by predicted-risk decile. Confidence intervals are a
  1000-draw bootstrap over listings. Baselines to beat: Kaplan-Meier overall and
  Kaplan-Meier by price band.

## Kaplan-Meier baselines

Probability of having sold by each day, with 95% log-log intervals. These are the
numbers any model has to improve on.

<!-- km-table:start -->
| Stratum | Listings | Sold | KM median days to first sale | Sold by day 30 | Sold by day 60 | Sold by day 90 | Sold by day 180 |
|---|---:|---:|---:|---:|---:|---:|---:|
| All listings | 2,060 | 997 | 237 | 15.3% [13.7, 16.9] | 23.8% [21.9, 25.9] | 31.1% [29.0, 33.3] | 44.0% [41.6, 46.4] |
| price band: <$15 | 919 | 502 | 207 | 19.1% [16.6, 21.8] | 27.2% [24.3, 30.3] | 33.8% [30.7, 37.2] | 47.1% [43.7, 50.7] |
| price band: $15-25 | 383 | 213 | 182 | 16.8% [13.3, 21.0] | 27.4% [23.1, 32.4] | 35.4% [30.5, 40.7] | 49.6% [44.3, 55.3] |
| price band: $25-50 | 443 | 156 | 267 | 10.0% [7.5, 13.4] | 18.9% [15.0, 23.7] | 28.2% [23.3, 33.8] | 41.3% [35.5, 47.7] |
| price band: $50+ | 315 | 126 | 375 | 9.0% [6.2, 13.0] | 15.9% [12.1, 20.8] | 21.9% [17.4, 27.3] | 31.3% [26.0, 37.3] |
| listing-day batch: 1-9 listed that day | 485 | 290 | 157 | 18.7% [15.5, 22.5] | 30.6% [26.6, 35.1] | 37.2% [32.9, 41.9] | 52.7% [47.9, 57.7] |
| listing-day batch: 10-39 listed that day | 1,109 | 562 | 267 | 15.9% [13.8, 18.3] | 23.6% [21.1, 26.4] | 31.0% [28.2, 34.0] | 42.5% [39.4, 45.8] |
| listing-day batch: 40+ listed that day | 466 | 145 | 251 | 10.6% [8.0, 13.9] | 16.4% [12.8, 20.8] | 23.6% [19.2, 28.9] | 38.1% [32.5, 44.3] |
| title: no rarity word | 1,820 | 884 | 231 | 15.1% [13.5, 16.9] | 24.2% [22.1, 26.4] | 31.2% [28.9, 33.6] | 44.4% [41.9, 47.0] |
| title: rarity word in title | 240 | 113 | 330 | 16.0% [11.9, 21.4] | 21.5% [16.7, 27.4] | 30.4% [24.8, 37.0] | 41.2% [34.9, 48.3] |
<!-- km-table:end -->

## Models

Milestone 2. Two model families are fit on the same design matrix: the listing's price
(log, plus band), the size of its listing day (log, plus bucket), rarity words parsed from
the title, and every tag carried by at least thirty listings in the fit set. Columns that
do not vary in the fit set are dropped there, so the evaluation listings never influence
the features.

- **Cox proportional hazards** (lifelines), L2 penalised; penalty chosen on validation.
- **Discrete-time hazard**: follow-up cut into ten-day periods, one logistic regression
  over listing-periods with a free intercept per period, fit by penalised IRLS in numpy.
  It makes no proportional-hazards assumption, and it is the model milestone 3 serves.

Both are judged against three Kaplan-Meier baselines: one curve for everyone (the null
that defines skill), one per price band, and one per price band and batch bucket.

<!-- results:start -->
**Validation** (fit on listings before 2025-07-01, censored there; scored on 596 listings from 2025-07-01 to 2025-12-31, 27.0% sold within 90 days). Selection metric is Brier skill.

| Model | Brier skill @90 | AUC @90 | Concordance | Mean predicted |
|---|---:|---:|---:|---:|
| `km_null` | +0.000 | 0.500 | 0.500 | 33.8% |
| `km_by_price_band` | +0.006 | 0.544 | 0.544 | 33.3% |
| `km_by_price_x_batch` | +0.020 | 0.594 | 0.561 | 33.1% |
| `cox(penalizer=0.05)` | +0.023 | 0.586 | 0.549 | 29.9% |
| `cox(penalizer=0.2)` **(chosen)** | +0.031 | 0.592 | 0.553 | 31.6% |
| `cox(penalizer=1.0)` | +0.029 | 0.595 | 0.555 | 33.0% |
| `dthazard(l2=0.1, bin=10d)` | +0.012 | 0.586 | 0.551 | 28.0% |
| `dthazard(l2=1.0, bin=10d)` | +0.018 | 0.583 | 0.547 | 28.0% |
| `dthazard(l2=10.0, bin=10d)` **(chosen)** | +0.024 | 0.574 | 0.538 | 28.7% |

**Test** (fit on listings before 2026-01-01, censored there; scored once on 319 listings from 2026-01-01 to 2026-06-07, 38.6% sold within 90 days; 1,000-draw bootstrap over listings).

| Model | Brier @90 | Brier skill @90 [95% CI] | AUC @90 [95% CI] | Concordance | Mean predicted |
|---|---:|---:|---:|---:|---:|
| `km_null` | 0.2428 | +0.000 [+0.000, +0.000] | 0.500 [0.500, 0.500] | 0.500 | 30.9% |
| `km_by_price_band` | 0.2439 | -0.004 [-0.025, +0.015] | 0.488 [0.425, 0.552] | 0.501 | 31.6% |
| `km_by_price_x_batch` | 0.2438 | -0.004 [-0.040, +0.033] | 0.528 [0.463, 0.595] | 0.542 | 31.6% |
| `cox(penalizer=0.2)` | 0.2294 | +0.055 [+0.022, +0.092] | 0.647 [0.586, 0.711] | 0.611 | 31.1% |
| `dthazard(l2=10.0, bin=10d)` | 0.2305 | +0.051 [+0.019, +0.088] | 0.648 [0.589, 0.713] | 0.613 | 30.3% |

**Calibration of `cox(penalizer=0.2)` on test**, by decile of predicted probability (observed = share that sold within 90 days):

| Decile | n | Predicted | Observed |
|---:|---:|---:|---:|
| 1 | 32 | 19.3% | 18.8% |
| 2 | 32 | 23.8% | 28.1% |
| 3 | 32 | 25.6% | 18.8% |
| 4 | 32 | 27.1% | 34.4% |
| 5 | 32 | 29.2% | 34.4% |
| 6 | 32 | 31.3% | 50.0% |
| 7 | 32 | 33.7% | 65.6% |
| 8 | 32 | 36.4% | 25.0% |
| 9 | 32 | 39.0% | 43.8% |
| 10 | 31 | 45.9% | 67.7% |
<!-- results:end -->

<!-- results-prose:start -->
### What the models say

- **Listing attributes predict a little, and it is real.** On test, Cox reaches a Brier
  skill of +0.055 [+0.022, +0.092] against the Kaplan-Meier null and an AUC of 0.647
  [0.586, 0.711]; the discrete-time hazard model is indistinguishable from it (+0.051,
  0.648). Both intervals exclude zero. A skill of five percent is small: most of *when* an
  item first sells is not in its price, its tags, or its listing day. The ranking is the
  usable part, and an AUC of 0.65 is enough to triage markdowns, not to forecast a date.
- **The stratified baselines did not survive the move from validation to test.** Price
  band and batch bucket together earned +0.020 on validation and -0.004 on test. Five or
  six Kaplan-Meier curves fit on a few hundred listings each carry the noise of their
  window; the penalised models, which share strength across every feature, did not fall.
- **Every model carries the old level, and the level moved.** Listings in the test window
  sold within 90 days 38.6% of the time; the null fit on the earlier listings predicted
  30.9%, and so, near enough, did every other model. Discrimination transferred and
  calibration did not. That is what a market shift looks like from inside a rolling-origin
  split, and it is why milestone 3 recomputes the current base rate at serving time rather
  than trusting the fitted level.
- **The calibration table is noisy by construction.** Thirty-two listings per decile puts a
  sixteen-point interval on each observed rate, so read the trend (roughly monotone, with
  the top deciles under-predicted) and not any single row.
- **Proportional hazards is not the limit.** The discrete-time model drops that assumption
  and lands on the same numbers, so the ceiling here is the information in the features,
  not the functional form. It is the model served in milestone 3 because it produces a
  survival curve at any day in plain numpy.

Selection used validation only; the two chosen configurations were scored on test once.
Gates in `gates.toml` sit just under these numbers and CI re-runs the whole evaluation on
every push, failing on a regression or on drift from the committed `results/test.json`.
<!-- results-prose:end -->

## The store report: overdue listings

Milestone 3. `sellthrough overdue` answers the question the store actually asks: *which
of the things on the shelf should have sold by now?*

- The discrete-time hazard model is fit on the whole cohort, then its **level is corrected
  to the most recent 180 days of listings that have had a full 90 days to sell**, because
  the evaluation showed discrimination transfers across windows and the level does not.
  On the September 2026 snapshot the recent window sold 39.8% within 90 days against a
  fitted 32.8%, a logit offset of +0.26.
- For every listing with no recorded sale, the score is the corrected probability that a
  listing with its price, tags, and listing-day size would have sold by its current age.
  A high probability on an unsold item is what "overdue" means; the list is sorted by it.
- With `--env-file` pointing at a read-only Admin API app, the same call brings back each
  variant's **cost per item** where the store has set it (96% of the catalog), so the table
  shows cost and margin at the current ticket price, and the report opens with what is
  sitting there: units, retail value, and cost tied up. Cost is the floor a markdown can go
  to and still return the money. Live on-hand quantities also split the list in two: **on the shelf and overdue**, which is the markdown candidate list, and
  **gone without a recorded sale**, which is zero on hand and no sale in the history:
  sold outside the system, returned, moved, or shrink. On the current snapshot that second
  list holds 203 variants, a quarter of everything unsold, and it is not a markdown list.

The committed [`results/overdue.md`](results/overdue.md) is one run against live stock.
It is a report, not a protocol artifact: it changes whenever stock or the cohort does, and
CI does not regenerate it.

## What this data cannot say

- **Survivorship.** Products deleted from the store are not in the pull. If deletion
  correlates with never selling, every sale rate above is biased upward.
- **First sale is not sell-through.** The store buys six to twelve pieces of a release.
  When the last one sells is the more valuable question, and it needs stock history that
  does not exist yet.
- **Listing time is the Shopify record, not the shelf.** Items may reach the shelf
  before or after the record is created. Bulk days are flagged, not corrected.
- **New releases and used-collection buys are indistinguishable** in the data, and they
  are different products commercially.

## Running it

```
pip install -e ".[dev]"
pytest -q
sellthrough describe --update-readme        # cohort tables, from the committed cohort
sellthrough evaluate --bootstrap 1000 --seed 0 --update-readme   # models; ~2 s
sellthrough gate --committed results/test.json                   # what CI runs
sellthrough overdue --env-file shopify.env --top 40              # store report; omit --env-file for no stock
sellthrough build --products products.jsonl --orders orders.jsonl \
    --exclude-emails owner@example.com      # rebuild the cohort from a raw pull
```

`build` reads the raw product and order export produced by the companion
[basket-recommender](https://github.com/peterzemore/basket-recommender) pipeline and
writes `data/cohort.csv`, `data/clean_stats.json`. Owner emails are a build-time flag
and are never written anywhere.

## Layout

```
src/sellthrough/
  protocol.py   the horizon, split dates, KM report times -- the contract
  cohort.py     raw pull -> one row per listing (event, days, censoring, batch size)
  km.py         Kaplan-Meier with Greenwood variance and log-log limits, numpy only
  splits.py     rolling-origin fit / eval sets
  features.py   design matrix; vocabulary learned from the fit set only
  models.py     KM null and strata, Cox PH (lifelines), discrete-time hazard (numpy)
  metrics.py    Brier, skill, AUC, Harrell's C, calibration, bootstrap
  evaluate.py   validation sweep, selection, single test scoring
  gate.py       thresholds, protocol check, drift check
  overdue.py    the store report: level correction, overdue scores
  stock.py      read-only live inventory, standard library only
  report.py     everything the README quotes
data/cohort.csv        the public dataset, customer-free
results/describe.json  cohort numbers, regenerated in CI
results/val.json       validation sweep (selection only)
results/test.json      the test numbers CI checks a fresh run against
results/overdue.md     one run of the store report against live stock (not regenerated by CI)
```

MIT licensed.
