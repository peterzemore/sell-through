# The number my store would have used was wrong by a factor of three
*Draft for a pinned GitHub Discussion on peterzemore/sell-through. About 750 words.*

How long does a newly listed item take to sell? For a retailer that is a markdown
question, a buying question, and a cash question. My store's answer, had anyone asked
the spreadsheet, would have been 73 days: the median time from listing to first sale
across everything that has sold.

The right answer is 237 days. Half of what the store lists has not sold at eight months.

## Where the 73 came from

The spreadsheet answer averages over items that sold. It ignores the items that have not
sold yet, which at the moment of the snapshot is 52% of everything listed since the
order history begins. Those items are not missing data. They are observations that say
"longer than this," and throwing them away keeps only the fast sellers. That is survival
analysis's founding problem, and the fix is to count a listing that has not sold as
censored at the snapshot date rather than absent.

Do that, with a Kaplan-Meier estimator written in numpy so the arithmetic is on the
page, and the median moves from 73 days to 237. The probability of a first sale within
90 days is 31.1%, with a 95% interval of 29.0 to 33.3.

## Why the first sale is the right event

Most retail time-to-event questions are confounded by stock: an item that did not sell
may simply not have been on the shelf. The first sale sidesteps that, because a
just-listed item is in stock by construction. The companion recommender project could
not see the shelf at all and had to treat stock as a serving-time filter. This project
picks the one event where the shelf is not in question, and deliberately does not ask
the second question, "when does it sell out," because there is no stock history to
answer it.

## The protocol, fixed before any model

The unit is a variant, the origin is its listing time, the event is its first
non-cancelled sale with the owner's own orders excluded, and censoring is at the last
order date. Listings dated before the order history begins are excluded as
left-truncated, since their early sales are unobservable. That removes 6,102 older
listings and leaves a cohort of 2,060.

The splits are rolling-origin, because that is how a model would be used. At a
prediction date you know everything before it and nothing after it, so the fit set is
every listing before that date with its follow-up censored at that date, and the
evaluation set is the listings that came after and have had a full 90 days to sell.
Validation predicts from July 2025, test from January 2026, and test is scored once. The
metric the next milestone will be judged on is already written down: Brier score at 90
days against the Kaplan-Meier null, reported as skill, with concordance and calibration
beside it.

## What the baselines already say

Two things move the curve a lot and one does not.

Price does: items under $15 have a 33.8% chance of selling within 90 days, items at $50
and up 21.9%, and the medians run from 207 days to 375. Listing-day batch size does too:
an item listed alone or with a few others sells within 90 days 37.2% of the time, an
item listed on a day with 40 or more others 23.6%. Seven such days carry 22% of the
cohort, and they look like what buying a private collection looks like.

Rarity words in the title, "exclusive", "chase", "vault", do nothing. 30.4% against
31.2%. In the recommender project those same words carried real signal for what sells
together. For how fast a thing sells, they are noise.

## What this data cannot say

Products deleted from the store are not in the pull, and if deletion correlates with
never selling, every rate above is biased upward. The first sale is not sell-through,
and with six to twelve pieces per release the second question is the more valuable one.
The listing timestamp is the Shopify record, which can lead or lag the shelf. And new
releases are indistinguishable from used-collection buys in the data, though they are
different products commercially. All four caveats are in the README above the results,
not below them.

## The lesson

The 73-day figure is not a rounding error. It is the number a store would put on a
markdown policy, and it would tell you to discount at roughly the point where most
items are still on their normal path to selling. The censored observations were always
in the data. The only thing that changed was refusing to drop them.

Repo: github.com/peterzemore/sell-through
