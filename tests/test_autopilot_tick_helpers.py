"""Unit tests for the helpers extracted out of autopilot.tick().

Before the split these lived inline in a ~225-line function and could only be
exercised by running the whole tick with heavy mocking. Now each is its own
small, directly-testable surface.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

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


def _channels_returning(rows):
    sb = MagicMock()
    sb.table.return_value.select.return_value.or_.return_value.is_.return_value \
        .execute.return_value.data = rows
    return sb


def test_pick_next_channel_never_ticked_first_then_oldest():
    sb = _channels_returning([
        {"id": "B", "autopilot_last_tick_at": "2026-01-02T00:00:00Z"},
        {"id": "A", "autopilot_last_tick_at": None},        # never ticked → highest priority
        {"id": "C", "autopilot_last_tick_at": "2026-01-01T00:00:00Z"},
    ])
    with patch("app.autopilot.supabase", return_value=sb):
        assert ap._pick_next_channel()["id"] == "A"


def test_pick_next_channel_none_when_no_eligible():
    sb = _channels_returning([])
    with patch("app.autopilot.supabase", return_value=sb):
        assert ap._pick_next_channel() is None


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
    embed.assert_called_once_with("v")
    ap._failure_counts.clear()
