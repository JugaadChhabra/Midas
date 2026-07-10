from unittest.mock import MagicMock, patch


def _run_tick_with_channel(channel_row):
    """Run tick() with the channel query returning one channel, sync/audit stubbed.
    Returns (shorts_called: bool, audit_called: bool)."""
    import app.autopilot as ap

    sb = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "channels":
            t.select.return_value.or_.return_value.is_.return_value.execute.return_value.data = [channel_row]
        return t
    sb.table.side_effect = table

    with patch("app.autopilot.supabase", return_value=sb), \
         patch("app.autopilot._run_shorts_action") as shorts, \
         patch("app.autopilot._touch_tick"), \
         patch("app.autopilot._needs_full_sync", return_value=False), \
         patch("app.autopilot.sync_channel"), patch("app.autopilot.refresh_stats"), \
         patch("app.autopilot._applies_today", return_value=0), \
         patch("app.autopilot._next_video_for_channel", return_value=None) as nextvid:
        # last_synced_at recent so needs_sync is False and we skip the sync branch
        from datetime import datetime, timezone
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
