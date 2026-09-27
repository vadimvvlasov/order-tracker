The bug is fixed and redeployed, and `/api/orders/express-1002` returns 200 again. Nothing is committed; the diff is ready for review.

**Root cause:** `order_detail` (`app/main.py:60`) worked out the express delivery estimate by changing the day of the month: `placed_at.replace(day=placed_at.day + 2)`. That fails for any express order placed in the last two days of a month. The seeded order `express-1002` is placed on the last day of the previous month, so every request for it failed with a 500.

**Fix:** I changed that line to `placed_at + timedelta(days=2)`, which rolls over into the next month correctly.

**Regression tests** (in `tests/test_api.py`):
- `test_express_order_placed_at_month_end` uses a fixed date of 2026-08-31 and expects an estimate of 2026-09-02. It fails without the fix whatever today's date is.
- `test_seeded_express_order` checks that `/api/orders/express-1002` returns 200 with an estimated delivery date.

INCIDENT: 20260927T025225Z-order-tracker-5xx-responses
ROOT CAUSE: order_detail computed express delivery with placed_at.replace(day=placed_at.day + 2), which raises ValueError for orders placed in the last two days of a month (seeded express-1002 is dated at the previous month's end).
FIX: app/main.py - use placed_at + timedelta(days=2); tests/test_api.py - added month-end express regression test and seeded express-1002 endpoint test
VERIFICATION: uv run --frozen pytest -q -> 28 passed; incident-response/runbooks/redeploy.sh -> container healthy; incident-response/runbooks/verify-recovery.sh /api/orders/express-1002 -> 3/3 200, RECOVERED
ACTION: fixed
RESULT: Fixed month-end date overflow in express delivery estimate; GET /api/orders/{order_id} recovered, diff awaiting human review.
