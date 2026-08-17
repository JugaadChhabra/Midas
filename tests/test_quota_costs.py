"""Quota owns what an operation costs, and charges it where it is spent.

The prices used to live as literals inside each youtube_client wrapper, written
to the ledger but never read, while every gate re-invented the number it needed:
APPLY_COST = 51 in audits, 1 + 50 in autopilot, 51 * n and 1 + 2 * ceil(n/50) in
the preview endpoint, PAGE_COST = 1 in playlists_sync. Five copies of arithmetic
derived from a table nobody could consult.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import quota
from app.quota import JobBudget, Op


@pytest.fixture(autouse=True)
def _no_ledger_io():
    """charge() writes a quota_log row; nothing here wants the round-trip."""
    with patch.object(quota, "supabase", return_value=MagicMock()):
        yield


# ── the price table ───────────────────────────────────────────────────────

def test_every_operation_has_a_price():
    ops = {v for k, v in vars(Op).items() if not k.startswith("_") and isinstance(v, str)}
    assert ops == set(quota.UNIT_COST), "an Op without a price charges nothing"


def test_cost_scales_with_calls():
    assert quota.cost(Op.PLAYLIST_ITEMS_LIST) == 1
    assert quota.cost(Op.PLAYLIST_ITEMS_LIST, 9) == 9
    assert quota.cost(Op.VIDEOS_UPDATE) == 50


def test_an_unpriced_operation_raises_rather_than_charging_zero():
    """Silently charging 0 is how a spender escapes its budget."""
    with pytest.raises(KeyError):
        quota.cost("videos.rate")


def test_apply_is_a_stats_read_plus_an_update():
    assert quota.cost_of(*quota.APPLY) == 51
    assert quota.APPLY == (Op.VIDEOS_LIST, Op.VIDEOS_UPDATE)


def test_calls_for_batches_at_the_api_limit():
    assert quota.calls_for(0) == 1        # a bulk action on nothing still calls once
    assert quota.calls_for(1) == 1
    assert quota.calls_for(50) == 1
    assert quota.calls_for(51) == 2
    assert quota.calls_for(500) == 10


# ── charging ──────────────────────────────────────────────────────────────

def test_charge_writes_the_priced_units_to_the_ledger():
    sb = MagicMock()
    with patch.object(quota, "supabase", return_value=sb):
        assert quota.charge("c1", Op.VIDEOS_UPDATE, True) == 50
    row = sb.table.return_value.insert.call_args[0][0]
    assert row == {"channel_id": "c1", "operation": "videos.update",
                   "units": 50, "success": True}


def test_a_broken_ledger_write_does_not_break_the_call_it_measured():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("postgrest is down")
    with patch.object(quota, "supabase", return_value=sb):
        assert quota.charge("c1", Op.VIDEOS_UPDATE, True) == 50


def test_charging_advances_the_active_budget_without_being_asked():
    """The bug this seam removes: sync_playlists asked permission before each
    membership page but never counted the inventory pages it read first, so the
    nightly walk under-reported its own spend."""
    with patch("app.quota.units_used_today", return_value=0):
        budget = JobBudget("t", budget=100)
    with quota.spending(budget):
        quota.charge("c1", Op.PLAYLISTS_LIST, True)
        quota.charge("c1", Op.PLAYLIST_ITEMS_LIST, True, 3)
    assert budget.spent == 4


def test_charging_outside_a_spending_block_touches_no_budget():
    with patch("app.quota.units_used_today", return_value=0):
        budget = JobBudget("t", budget=100)
    quota.charge("c1", Op.VIDEOS_UPDATE, True)
    assert budget.spent == 0


def test_spending_blocks_nest_and_restore():
    with patch("app.quota.units_used_today", return_value=0):
        outer, inner = JobBudget("outer", 100), JobBudget("inner", 100)
    with quota.spending(outer):
        quota.charge("c1", Op.PLAYLIST_ITEMS_LIST, True)
        with quota.spending(inner):
            quota.charge("c1", Op.PLAYLIST_ITEMS_LIST, True)
        quota.charge("c1", Op.PLAYLIST_ITEMS_LIST, True)
    assert (outer.spent, inner.spent) == (2, 1)


def test_a_failed_call_is_still_charged():
    """YouTube bills the attempt, so the ledger must record it."""
    with patch("app.quota.units_used_today", return_value=0):
        budget = JobBudget("t", budget=100)
    with quota.spending(budget):
        quota.charge("c1", Op.SEARCH_LIST, False)
    assert budget.spent == 100


# ── the quota day ─────────────────────────────────────────────────────────
#
# YouTube resets at midnight Pacific. The meter used to sum the ledger from
# midnight UTC and call it "close enough", which it was not: between 00:00 UTC
# and the real boundary, Google's current day had already been running for up to
# 17 hours, and every unit spent in it was excluded from used_today. The nightly
# playlist walk — the heaviest spender there is — lands squarely in that window,
# so the dashboard reported a whole night's spend as free quota every morning
# while the API returned quotaExceeded.

def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_the_quota_day_starts_at_midnight_pacific_not_midnight_utc():
    """03:00 UTC is still yesterday in California, so the day began at 07:00
    UTC *yesterday* — the 17 hours of spend that midnight-UTC threw away."""
    assert quota.quota_day_start(_utc(2026, 8, 17, 3)) == _utc(2026, 8, 16, 7)


def test_the_quota_day_rolls_over_at_the_pacific_boundary_not_before():
    # 06:59 UTC: still the previous quota day.
    assert quota.quota_day_start(_utc(2026, 8, 17, 6, 59)) == _utc(2026, 8, 16, 7)
    # 07:00 UTC: the counter has reset.
    assert quota.quota_day_start(_utc(2026, 8, 17, 7)) == _utc(2026, 8, 17, 7)


def test_the_boundary_follows_pacific_daylight_saving():
    """A hardcoded UTC hour is wrong for four months of the year: PDT resets at
    07:00 UTC, PST at 08:00."""
    assert quota.quota_day_start(_utc(2026, 8, 17, 12)).hour == 7   # PDT
    assert quota.quota_day_start(_utc(2026, 1, 17, 12)).hour == 8   # PST


def test_units_used_today_counts_from_the_pacific_boundary():
    """The filter the meter actually sends — the bug lived here, not in a
    helper nobody called."""
    sb = MagicMock()
    with patch.object(quota, "supabase", return_value=sb), \
         patch.object(quota, "all_rows", return_value=[]), \
         patch.object(quota, "_now", return_value=_utc(2026, 8, 17, 3)):
        quota.units_used_today()
    field, since = sb.table.return_value.select.return_value.gte.call_args[0]
    assert field == "occurred_at"
    assert datetime.fromisoformat(since) == _utc(2026, 8, 16, 7)


def test_the_countdown_and_the_meter_share_one_boundary():
    """They disagreed for months: dashboard.py counted down to 07:00 UTC while
    quota.py summed from 00:00 UTC, in the same response payload."""
    now = _utc(2026, 8, 17, 3)
    reset = now + timedelta(seconds=quota.seconds_until_reset(now))
    assert reset == quota.quota_day_start(_utc(2026, 8, 17, 7))
    assert quota.seconds_until_reset(now) == 4 * 3600


def test_the_reset_is_always_in_the_future():
    for hour in range(24):
        assert quota.seconds_until_reset(_utc(2026, 8, 17, hour)) > 0


# ── nobody re-solves it ───────────────────────────────────────────────────

APP = Path(__file__).resolve().parents[1] / "app"

#: A module declaring a unit price of its own: APPLY_COST = 51, PAGE_COST = 1,
#: COST_VIDEO_UPDATE = 50. Verified to match all three historical copies — an
#: earlier version of this guard looked for a literal inside can_afford() and
#: would have caught none of them, because the literal always hid in a constant.
_OWN_COST_CONST = re.compile(r"^\s*[A-Z_]*COST[A-Z_]*\s*=\s*\d+", re.M)
#: A module deriving the daily ceiling itself instead of asking units_remaining.
_OWN_REMAINING = re.compile(
    r"settings\.YT_DAILY_QUOTA\s*-\s*settings\.YT_QUOTA_SAFETY_BUFFER\s*-")
#: A module fixing the reset hour itself: QUOTA_RESET_HOUR_UTC = 7 in
#: dashboard.py, which was both a second copy of the boundary and wrong from
#: November to March. Ask quota.seconds_until_reset / quota_day_start.
_OWN_RESET_HOUR = re.compile(r"^\s*[A-Z_]*RESET_HOUR[A-Z_]*\s*=", re.M)


def _app_sources():
    for p in sorted(APP.rglob("*.py")):
        if p.name == "quota.py":
            continue
        yield p


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_declares_its_own_unit_price(path):
    hits = [h.strip() for h in _OWN_COST_CONST.findall(path.read_text())]
    assert not hits, (
        f"{path.name} declares its own unit price {hits} — price it with "
        "app.quota.cost/cost_of so the number has one owner"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_computes_the_remaining_ceiling_itself(path):
    assert not _OWN_REMAINING.search(path.read_text()), (
        f"{path.name} derives the daily ceiling itself — call "
        "app.quota.units_remaining()"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_fixes_the_quota_reset_hour_itself(path):
    assert not _OWN_RESET_HOUR.search(path.read_text()), (
        f"{path.name} hardcodes the quota reset hour — call "
        "app.quota.seconds_until_reset(); the UTC hour moves with Pacific DST"
    )
