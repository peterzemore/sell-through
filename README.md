# sell-through

How long does a newly listed item take to sell? For a real retail store, treated as
what it is: right-censored time-to-event data, with a protocol stated before any model
was written.

The store is a Funko Pop shop with about a hundred orders a month. The data is its
actual listings and order history, reduced to one customer-free row per listing and
committed to this repo, so everything here runs from a clean clone with no credentials.
Every number in this README is computed from that file by `sellthrough describe`; CI
regenerates them on every push and fails if the committed text drifts.

**Status: milestone 1 of 3.** Cohort, protocol, and Kaplan-Meier baselines are done
and are what this README reports. Models (milestone 2) and the store-facing "overdue
listings" report (milestone 3) come next; the split and the metrics they will be judged
on are already fixed below.

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
sellthrough describe --update-readme        # from the committed cohort, no credentials
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
  report.py     everything the README quotes
data/cohort.csv        the public dataset, customer-free
results/describe.json  the numbers, regenerated in CI
```

MIT licensed.
