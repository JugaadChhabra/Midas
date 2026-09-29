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


# ── _apply_audit_and_handle: react to the TYPED outcome (was a string switch) ──

def test_apply_handle_quota_sets_dormant_window():
    ap._yt_quota_exhausted_until = None
    with patch("app.autopilot.apply_audit_internal", side_effect=ApplyError(ApplyOutcome.QUOTA_EXCEEDED)):
        ap._apply_audit_and_handle({"id": 1}, {"id": "v", "is_short": False}, "UC1")
    assert ap._yt_quota_exhausted_until is not None        # autopilot goes dormant
    ap._yt_quota_exhausted_until = None


def test_apply_handle_token_expired_pauses_channel():
    with patch("app.autopilot.apply_audit_internal", side_effect=ApplyError(ApplyOutcome.TOKEN_EXPIRED)), \
         patch("app.autopilot._pause") as pause:
        ap._apply_audit_and_handle({"id": 1}, {"id": "v"}, "UC1")
    pause.assert_called_once_with("UC1", "token_expired")


def test_apply_handle_failed_records_failure():
    with patch("app.autopilot.apply_audit_internal", side_effect=ApplyError(ApplyOutcome.FAILED)), \
         patch("app.autopilot._record_failure") as rec:
        ap._apply_audit_and_handle({"id": 1}, {"id": "v"}, "UC1")
    rec.assert_called_once_with("UC1")


def test_apply_handle_test_and_compare_has_no_side_effects():
    ap._yt_quota_exhausted_until = None
    with patch("app.autopilot.apply_audit_internal", side_effect=ApplyError(ApplyOutcome.TEST_AND_COMPARE)), \
         patch("app.autopilot._pause") as pause, \
         patch("app.autopilot._record_failure") as rec:
        ap._apply_audit_and_handle({"id": 1}, {"id": "v"}, "UC1")
    pause.assert_not_called()
    rec.assert_not_called()
    assert ap._yt_quota_exhausted_until is None            # not treated as quota/failure


def test_apply_handle_success_resets_failures_and_embeds():
    ap._failure_counts["UC1"] = 2
    with patch("app.autopilot.apply_audit_internal", return_value={"status": "applied"}), \
         patch("app.autopilot.embed_video") as embed:
        ap._apply_audit_and_handle({"id": 1}, {"id": "v", "is_short": False}, "UC1")
    assert ap._failure_counts["UC1"] == 0
    # force=True: the apply just rewrote the title, so the stored vector is
    # stale by construction and the default short-circuit would keep it.
    embed.assert_called_once_with("v", force=True)
    ap._failure_counts.clear()


# ── the outcome it returns is what tick() reports as tick.outcome ──────────────
#
# This function absorbs four ApplyErrors and returns normally from every one, so
# "did not raise" is not the same question as "applied". A caller that conflated
# them reported a quota exhaustion, a channel pause and a YouTube rejection as
# successful applies.

@pytest.mark.parametrize("outcome,expected", [
    (ApplyOutcome.TEST_AND_COMPARE, "blocked_test_and_compare"),
    (ApplyOutcome.QUOTA_EXCEEDED, "youtube_quota_exceeded"),
    (ApplyOutcome.TOKEN_EXPIRED, "token_expired"),
    (ApplyOutcome.FAILED, "failed"),
])
def test_apply_handle_returns_the_absorbed_outcome(outcome, expected):
    ap._yt_quota_exhausted_until = None
    with patch("app.autopilot.apply_audit_internal", side_effect=ApplyError(outcome)), \
         patch("app.autopilot._pause"), \
         patch("app.autopilot._record_failure"):
        assert ap._apply_audit_and_handle({"id": 1}, {"id": "v"}, "UC1") == expected
    ap._yt_quota_exhausted_until = None


def test_apply_handle_returns_applied_on_success():
    with patch("app.autopilot.apply_audit_internal", return_value={"status": "applied"}), \
         patch("app.autopilot.embed_video"):
        assert ap._apply_audit_and_handle({"id": 1}, {"id": "v", "is_short": True}, "UC1") == "applied"
    ap._failure_counts.clear()


def test_apply_handle_distinguishes_a_dry_run_from_a_real_write():
    """A DRY_RUN deploy writes nothing to YouTube; reporting it as `applied`
    makes a rehearsal indistinguishable from a month of live changes."""
    with patch("app.autopilot.apply_audit_internal", return_value={"status": "dry_run"}), \
         patch("app.autopilot.embed_video"):
        assert ap._apply_audit_and_handle({"id": 1}, {"id": "v", "is_short": True}, "UC1") == "dry_run"
    ap._failure_counts.clear()


def test_apply_handle_separates_an_unclassified_crash_from_a_youtube_failure():
    with patch("app.autopilot.apply_audit_internal", side_effect=RuntimeError("db write blew up")), \
         patch("app.autopilot._record_failure") as rec:
        assert ap._apply_audit_and_handle({"id": 1}, {"id": "v"}, "UC1") == ap.APPLY_UNCLASSIFIED
    rec.assert_called_once_with("UC1")
    assert ap.APPLY_UNCLASSIFIED != ApplyOutcome.FAILED.value


# ── A10: pre-write quota gate ──────────────────────────────────────────────────
#
# The ledger already knows when a write can't be afforded. Autopilot used to find
# out only from YouTube's quotaExceeded, which puts the whole fleet dormant; a
# gate that trips on the ledger must skip the tick and nothing more.

@contextmanager
def _tick_on(channel, can_afford):
    """Run one tick against a single ready channel with the ledger answering
    `can_afford`. Yields (store, patches) so tests can assert on both."""
    sb = FakeSupabase({"channels": [channel]})
    video = {"id": "v1", "is_short": False}
    with patch("app.eligibility.supabase", return_value=sb), \
         patch("app.autopilot.supabase", return_value=sb), \
         patch("app.autopilot.quota.can_afford", side_effect=can_afford) as afford, \
         patch("app.autopilot.quota.units_remaining", return_value=12), \
         patch("app.autopilot._applies_today", return_value=0), \
         patch("app.autopilot._next_video_for_channel", return_value=video), \
         patch("app.autopilot.audit_video", return_value={"id": 7}) as audit, \
         patch("app.autopilot.validate_audit", return_value=(True, "")), \
         patch("app.autopilot.apply_audit_internal") as apply_, \
         patch("app.autopilot.embed_video"), \
         patch("app.autopilot.tracing.span") as span:
        rec = MagicMock()
        span.return_value.__enter__.return_value = rec
        yield sb, {"afford": afford, "audit": audit, "apply": apply_, "rec": rec}


def _ready_channel():
    return {"id": "UC1", "autopilot_enabled": True, "default_language": "hi",
            "autopilot_paused_reason": None, "autopilot_last_tick_at": None,
            "last_synced_at": datetime.now(timezone.utc).isoformat()}


def test_tick_that_cannot_afford_the_apply_makes_no_youtube_call_and_pauses_nothing(caplog):
    ap._yt_quota_exhausted_until = None
    ap._failure_counts.clear()
    with caplog.at_level("INFO", logger="midas.autopilot"), \
         _tick_on(_ready_channel(), can_afford=lambda *a, **k: False) as (sb, p):
        ap.tick()
    p["apply"].assert_not_called()                          # no videos.update
    p["audit"].assert_not_called()                          # no LLM spend on a write we can't make
    p["afford"].assert_any_call(ap.quota.cost_of(*ap.quota.APPLY))
    p["rec"].set.assert_any_call(**{"tick.outcome": "quota_insufficient"})
    assert sb.rows("channels")[0]["autopilot_paused_reason"] is None   # not paused
    assert not any(op == "update" and payload.get("autopilot_paused_reason")
                   for _, op, payload in sb.writes)             # no write sets a pause
    assert ap._yt_quota_exhausted_until is None             # not fleet-dormant
    assert ap._failure_counts.get("UC1", 0) == 0            # not a failure
    assert "quota_insufficient" in caplog.text


def test_tick_rechecks_quota_after_the_audit_spent_some():
    """The audit itself can spend quota (the captions fallback is 250u), so the
    gate runs again immediately before the write."""
    answers = iter([True, False])
    ap._yt_quota_exhausted_until = None
    with _tick_on(_ready_channel(), can_afford=lambda *a, **k: next(answers)) as (sb, p):
        ap.tick()
    p["audit"].assert_called_once()
    p["apply"].assert_not_called()
    p["rec"].set.assert_any_call(**{"tick.outcome": "quota_insufficient"})
    assert sb.rows("channels")[0]["autopilot_paused_reason"] is None
    assert ap._yt_quota_exhausted_until is None


def test_tick_that_can_afford_the_apply_applies():
    ap._yt_quota_exhausted_until = None
    ap._failure_counts.clear()
    with _tick_on(_ready_channel(), can_afford=lambda *a, **k: True) as (_, p):
        p["apply"].return_value = {"status": "applied"}
        ap.tick()
    p["apply"].assert_called_once_with(7)
    ap._failure_counts.clear()


def test_quota_exceeded_log_says_it_is_fleet_wide(caplog):
    ap._yt_quota_exhausted_until = None
    with caplog.at_level("WARNING", logger="midas.autopilot"), \
         patch("app.autopilot.apply_audit_internal", side_effect=ApplyError(ApplyOutcome.QUOTA_EXCEEDED)):
        ap._apply_audit_and_handle({"id": 1}, {"id": "v"}, "UC1")
    assert "project-wide" in caplog.text and "fleet-wide" in caplog.text
    ap._yt_quota_exhausted_until = None
