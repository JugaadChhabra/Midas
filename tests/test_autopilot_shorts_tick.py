from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


def _run_tick_with_channel(channel_row):
    """Run tick() with the channel query returning one channel, sync/audit stubbed.
    Returns (shorts_called: bool, audit_called: bool)."""
    import app.autopilot as ap

    sb = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "channels":
            # _pick_next_channel -> eligibility.channels_for: it pages, so the
            # chain is select("*").or_().order().range().execute()
            t.select.return_value.or_.return_value.order.return_value \
                .range.return_value.execute.return_value.data = [channel_row]
            # _clear_expired_pauses: update(...).eq(...).lt(...).execute() -> nothing expired
            t.update.return_value.eq.return_value.lt.return_value.execute.return_value.data = []
        return t
    sb.table.side_effect = table

    with patch("app.autopilot.supabase", return_value=sb), \
         patch("app.eligibility.supabase", return_value=sb), \
         patch("app.autopilot._run_shorts_action") as shorts, \
         patch("app.autopilot._touch_tick"), \
         patch("app.autopilot._needs_full_sync", return_value=False), \
         patch("app.autopilot.sync_channel"), patch("app.autopilot.refresh_stats"), \
         patch("app.autopilot._applies_today", return_value=0), \
         patch("app.autopilot._next_video_for_channel", return_value=None) as nextvid:
        # last_synced_at recent so needs_sync is False and we skip the sync branch
        channel_row.setdefault("last_synced_at", datetime.now(timezone.utc).isoformat())
        ap.tick()
        # audit path "entered" == _next_video_for_channel was consulted
        return shorts.called, nextvid.called


def test_shorts_only_channel_runs_shorts_not_audit():
    shorts_called, audit_called = _run_tick_with_channel(
        {"id": "UC1", "autopilot_enabled": False, "autopilot_shorts_enabled": True})
    assert shorts_called is True
    assert audit_called is False   # audit path skipped for shorts-only channel


def test_audit_only_channel_runs_audit_not_shorts():
    shorts_called, audit_called = _run_tick_with_channel(
        {"id": "UC1", "autopilot_enabled": True, "autopilot_shorts_enabled": False})
    assert shorts_called is False
    assert audit_called is True


def test_both_enabled_runs_both():
    shorts_called, audit_called = _run_tick_with_channel(
        {"id": "UC1", "autopilot_enabled": True, "autopilot_shorts_enabled": True})
    assert shorts_called is True
    assert audit_called is True


def test_audit_pause_does_not_silence_shorts():
    """The decoupling fix: a channel paused on the audit side (repeated_failures)
    must STILL cut shorts — the audit path is the only thing the pause gates."""
    shorts_called, audit_called = _run_tick_with_channel({
        "id": "UC1", "autopilot_enabled": True, "autopilot_shorts_enabled": True,
        "autopilot_paused_reason": "repeated_failures",
    })
    assert shorts_called is True     # shorts run despite the pause
    assert audit_called is False     # audit path stays gated by the pause


def test_shorts_only_channel_runs_even_when_paused():
    """The exact stuck-channel case: shorts-only + repeated_failures still cuts."""
    shorts_called, audit_called = _run_tick_with_channel({
        "id": "UC1", "autopilot_enabled": False, "autopilot_shorts_enabled": True,
        "autopilot_paused_reason": "repeated_failures",
    })
    assert shorts_called is True
    assert audit_called is False


def test_clear_expired_pauses_clears_repeated_failures_and_resets_counter():
    import app.autopilot as ap

    cleared_row = {"id": "UC1"}
    sb = MagicMock()
    chain = sb.table.return_value.update.return_value.eq.return_value.lt.return_value
    chain.execute.return_value.data = [cleared_row]

    ap._failure_counts["UC1"] = 3
    with patch("app.autopilot.supabase", return_value=sb), \
         patch("app.eligibility.supabase", return_value=sb), \
         patch.object(ap.settings, "AUTOPILOT_PAUSE_COOLDOWN_MINUTES", 60):
        ap._clear_expired_pauses()

    # counter reset so the channel gets a fresh 3-strike budget
    assert ap._failure_counts["UC1"] == 0
    # cleared by flipping reason + paused_at to NULL, filtered to repeated_failures
    sb.table.return_value.update.assert_called_with(
        {"autopilot_paused_reason": None, "autopilot_paused_at": None})
    sb.table.return_value.update.return_value.eq.assert_called_with(
        "autopilot_paused_reason", "repeated_failures")


def test_clear_expired_pauses_disabled_when_cooldown_zero():
    import app.autopilot as ap
    sb = MagicMock()
    with patch("app.autopilot.supabase", return_value=sb), \
         patch("app.eligibility.supabase", return_value=sb), \
         patch.object(ap.settings, "AUTOPILOT_PAUSE_COOLDOWN_MINUTES", 0):
        ap._clear_expired_pauses()
    sb.table.assert_not_called()   # no DB work when auto-unpause is off
