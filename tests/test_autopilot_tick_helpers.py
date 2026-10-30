"""Unit tests for the helpers extracted out of autopilot.tick().

Before the split these lived inline in a ~225-line function and could only be
exercised by running the whole tick with heavy mocking. Now each is its own
small, directly-testable surface.
"""
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from tests.fakes import FakeSupabase

import app.autopilot as ap
from app.apply_outcome import ApplyError, ApplyOutcome


def test_record_failure_pauses_only_at_threshold():
    with patch("app.autopilot._pause") as pause:
        ap._failure_counts.clear()
        ap._record_failure("UC1")
        ap._record_failure("UC1")
        assert pause.call_count == 0                       # two failures — not yet
        ap._record_failure("UC1")
        pause.assert_called_once_with("UC1", "repeated_failures")   # third trips it
    ap._failure_counts.clear()


def test_quota_dormant_transitions():
    ap._yt_quota_exhausted_until = None
    assert ap._quota_dormant() is False                    # no window → run

    ap._yt_quota_exhausted_until = datetime.now(timezone.utc) + timedelta(hours=1)
    assert ap._quota_dormant() is True                     # still exhausted → idle

    ap._yt_quota_exhausted_until = datetime.now(timezone.utc) - timedelta(hours=1)
    assert ap._quota_dormant() is False                    # window passed → run…
    assert ap._yt_quota_exhausted_until is None            # …and it self-clears


@contextmanager
def _fleet(rows):
    """One store standing in for both modules the picker reads through.

    _pick_next_channel spans two: eligibility selects the channels, and
    autopilot's _clear_expired_pauses writes to the same table. An earlier version
    of this fixture patched only one of them, so every offline run issued a live
    UPDATE against the production channels table — silently, because the update's
    result is not asserted. tests/fakes.py raises on an unstubbed table instead.
    """
    sb = FakeSupabase({"channels": rows})
    with patch("app.eligibility.supabase", return_value=sb), \
         patch("app.autopilot.supabase", return_value=sb):
        yield sb


def test_pick_next_channel_never_ticked_first_then_oldest():
    with _fleet([
        {"id": "B", "autopilot_enabled": True, "default_language": "hi", "autopilot_last_tick_at": "2026-01-02T00:00:00Z"},
        {"id": "A", "autopilot_enabled": True, "default_language": "hi", "autopilot_last_tick_at": None},   # never ticked → highest priority
        {"id": "C", "autopilot_enabled": True, "default_language": "hi", "autopilot_last_tick_at": "2026-01-01T00:00:00Z"},
    ]):
        assert ap._pick_next_channel()["id"] == "A"


def test_pick_next_channel_none_when_no_eligible():
    with _fleet([]):
        assert ap._pick_next_channel() is None


def test_pick_next_channel_skips_a_paused_channel_without_writing_to_it():
    """The pause clearing runs first and must not disturb a live pause that has
    not aged out."""
    with _fleet([
        {"id": "P", "autopilot_enabled": True, "default_language": "hi",
         "autopilot_paused_reason": "token_expired",
         "autopilot_paused_at": "2099-01-01T00:00:00Z", "autopilot_last_tick_at": None},
    ]) as sb:
        assert ap._pick_next_channel() is None
        assert sb.rows("channels")[0]["autopilot_paused_reason"] == "token_expired"


def test_resync_skips_when_fresh():
    ch = {"id": "UC1", "last_synced_at": datetime.now(timezone.utc).isoformat()}
    with patch("app.autopilot.sync_channel") as sync, \
         patch("app.autopilot.refresh_stats"):
        assert ap._resync_if_stale(ch) is True
        sync.assert_not_called()                           # fresh → no sync


def test_resync_stops_tick_on_token_expiry():
    ch = {"id": "UC1", "last_synced_at": "2020-01-01T00:00:00Z"}   # stale
    with patch("app.autopilot._needs_full_sync", return_value=False), \
         patch("app.autopilot.sync_channel", side_effect=ap.TokenExpiredError("x")), \
         patch("app.autopilot.refresh_stats"), \
         patch("app.autopilot._pause") as pause:
        assert ap._resync_if_stale(ch) is False            # token expiry → stop tick
        pause.assert_called_once_with("UC1", "token_expired")


# ── _react_to_apply_error: react to the TYPED outcome (was a string switch) ──
#
# The agent path's reaction to a failed write. It returned the house-format
# path's reaction too until that path left the tick (S3.6).

def test_apply_error_quota_sets_dormant_window():
    ap._yt_quota_exhausted_until = None
    ap._react_to_apply_error(ApplyError(ApplyOutcome.QUOTA_EXCEEDED), "UC1")
    assert ap._yt_quota_exhausted_until is not None        # autopilot goes dormant
    ap._yt_quota_exhausted_until = None


def test_apply_error_token_expired_pauses_channel():
    with patch("app.autopilot._pause") as pause:
        ap._react_to_apply_error(ApplyError(ApplyOutcome.TOKEN_EXPIRED), "UC1")
    pause.assert_called_once_with("UC1", "token_expired")


def test_apply_error_failed_records_failure():
    with patch("app.autopilot._record_failure") as rec:
        ap._react_to_apply_error(ApplyError(ApplyOutcome.FAILED), "UC1")
    rec.assert_called_once_with("UC1")


@pytest.mark.parametrize("outcome", [ApplyOutcome.TEST_AND_COMPARE,
                                     ApplyOutcome.QUOTA_INSUFFICIENT,
                                     ApplyOutcome.APPLY_DISABLED])
def test_a_refusal_before_anything_was_sent_has_no_side_effects(outcome):
    ap._yt_quota_exhausted_until = None
    with patch("app.autopilot._pause") as pause, \
         patch("app.autopilot._record_failure") as rec:
        ap._react_to_apply_error(ApplyError(outcome), "UC1")
    pause.assert_not_called()
    rec.assert_not_called()
    assert ap._yt_quota_exhausted_until is None            # not treated as quota/failure


# ── the outcome it returns is what tick() reports as tick.outcome ──────────────
#
# It absorbs four ApplyErrors and returns normally from every one, so "did not
# raise" is not the same question as "applied". A caller that conflated them
# reported a quota exhaustion, a channel pause and a YouTube rejection as
# successful applies.

@pytest.mark.parametrize("outcome,expected", [
    (ApplyOutcome.TEST_AND_COMPARE, "blocked_test_and_compare"),
    (ApplyOutcome.QUOTA_EXCEEDED, "youtube_quota_exceeded"),
    (ApplyOutcome.TOKEN_EXPIRED, "token_expired"),
    (ApplyOutcome.FAILED, "failed"),
])
def test_apply_error_returns_the_absorbed_outcome(outcome, expected):
    ap._yt_quota_exhausted_until = None
    with patch("app.autopilot._pause"), \
         patch("app.autopilot._record_failure"):
        assert ap._react_to_apply_error(ApplyError(outcome), "UC1") == expected
    ap._yt_quota_exhausted_until = None


# ── A10: pre-write quota gate ──────────────────────────────────────────────────
#
# The ledger already knows when a write can't be afforded. Autopilot used to find
# out only from YouTube's quotaExceeded, which puts the whole fleet dormant; a
# gate that trips on the ledger must skip the tick and nothing more. Since S3.6
# the agent path is the tick's only write path, so the gate is driven through it.

@contextmanager
def _tick_on(channel, can_afford):
    """Run one tick against a single ready agent channel with the ledger
    answering `can_afford`. Yields (store, patches) so tests can assert on both."""
    sb = FakeSupabase({"channels": [channel]})
    with patch("app.eligibility.supabase", return_value=sb), \
         patch("app.autopilot.supabase", return_value=sb), \
         patch("app.autopilot.eligibility.can_run_agent", return_value=True), \
         patch.object(ap.settings, "BACKLINK_APPLY_ENABLED", True), \
         patch.dict(ap.backlinks.HEADINGS, {"hi": "Watch more"}, clear=True), \
         patch("app.autopilot.quota.can_afford", side_effect=can_afford) as afford, \
         patch("app.autopilot.quota.units_remaining", return_value=12), \
         patch("app.autopilot._applies_today", return_value=0), \
         patch("app.autopilot.agent_tick.run", return_value="measuring") as run, \
         patch("app.autopilot.tracing.span") as span:
        rec = MagicMock()
        span.return_value.__enter__.return_value = rec
        yield sb, {"afford": afford, "run": run, "rec": rec}


def _ready_channel():
    return {"id": "UC1", "autopilot_enabled": True, "agent_enabled": True,
            "default_language": "hi",
            "autopilot_paused_reason": None, "autopilot_last_tick_at": None,
            "last_synced_at": datetime.now(timezone.utc).isoformat()}


def test_tick_that_cannot_afford_the_apply_makes_no_youtube_call_and_pauses_nothing(caplog):
    ap._yt_quota_exhausted_until = None
    ap._failure_counts.clear()
    with caplog.at_level("INFO", logger="midas.autopilot"), \
         _tick_on(_ready_channel(), can_afford=lambda *a, **k: False) as (sb, p):
        ap.tick()
    p["run"].assert_not_called()                            # no pick, no LLM, no write
    p["afford"].assert_any_call(ap.quota.cost_of(*ap.quota.APPLY),
                                reserve=ap.settings.YT_QUOTA_COLLECTION_RESERVE)
    p["rec"].set.assert_any_call(**{"tick.outcome": "quota_insufficient"})
    assert sb.rows("channels")[0]["autopilot_paused_reason"] is None   # not paused
    assert not any(op == "update" and payload.get("autopilot_paused_reason")
                   for _, op, payload in sb.writes)             # no write sets a pause
    assert ap._yt_quota_exhausted_until is None             # not fleet-dormant
    assert ap._failure_counts.get("UC1", 0) == 0            # not a failure
    assert "quota_insufficient" in caplog.text


def test_tick_that_can_afford_the_apply_applies():
    ap._yt_quota_exhausted_until = None
    ap._failure_counts.clear()
    with _tick_on(_ready_channel(), can_afford=lambda *a, **k: True) as (_, p):
        ap.tick()
    p["run"].assert_called_once()
    p["rec"].set.assert_any_call(**{"tick.outcome": "measuring"})
    ap._failure_counts.clear()


def test_quota_exceeded_log_says_it_is_fleet_wide(caplog):
    ap._yt_quota_exhausted_until = None
    with caplog.at_level("WARNING", logger="midas.autopilot"):
        ap._react_to_apply_error(ApplyError(ApplyOutcome.QUOTA_EXCEEDED), "UC1")
    assert "project-wide" in caplog.text and "fleet-wide" in caplog.text
    ap._yt_quota_exhausted_until = None


def test_the_apply_gate_keeps_the_collection_reserve():
    """Fleet readiness (2026-10-25): applies stop YT_QUOTA_COLLECTION_RESERVE
    short of the ceiling, so video_sync and the polls late in the quota day
    still have units."""
    from app import autopilot, quota
    cost = quota.cost_of(*quota.APPLY)
    for left, ok in ((cost - 1, False), (cost, True)):
        with patch.multiple(autopilot.settings, YT_DAILY_QUOTA=10_000, YT_QUOTA_SAFETY_BUFFER=300,
                            YT_QUOTA_COLLECTION_RESERVE=3000), \
             patch.object(quota, "units_used_today", return_value=10_000 - 300 - 3000 - left):
            assert autopilot._can_afford_apply("UC1") is ok
