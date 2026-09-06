"""The pre-registered protocol. These constants are the contract; the README quotes
them and CI regenerates every number from them. Changing one is a deliberate edit to
the protocol, never a side effect."""
from __future__ import annotations

import datetime as dt

HORIZON_DAYS = 90

# Rolling-origin splits. For a prediction date d: fit on variants listed before d with
# follow-up administratively censored at d; evaluate on variants listed in
# [d, window_end] that have a full HORIZON_DAYS of follow-up in the snapshot.
VAL_ORIGIN = dt.date(2025, 7, 1)
VAL_WINDOW_END = dt.date(2025, 12, 31)
TEST_ORIGIN = dt.date(2026, 1, 1)
TEST_WINDOW_END = dt.date(2026, 6, 7)

KM_TIMES = (30, 60, 90, 180)
