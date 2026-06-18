from datetime import datetime, timezone, timedelta


def test_needs_full_sync_when_never_run():
    from app.autopilot import _needs_full_sync
    assert _needs_full_sync({}) is True
    assert _needs_full_sync({"last_full_synced_at": None}) is True


def test_needs_full_sync_when_stale():
    from app.autopilot import _needs_full_sync, FULL_SYNC_INTERVAL
    old = (datetime.now(timezone.utc) - FULL_SYNC_INTERVAL - timedelta(hours=1)).isoformat()
    assert _needs_full_sync({"last_full_synced_at": old}) is True


def test_no_full_sync_when_recent():
    from app.autopilot import _needs_full_sync
    recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    assert _needs_full_sync({"last_full_synced_at": recent}) is False


def test_needs_full_sync_on_unparseable_timestamp():
    from app.autopilot import _needs_full_sync
    assert _needs_full_sync({"last_full_synced_at": "not-a-date"}) is True


def test_full_sync_interval_is_three_days():
    from app.autopilot import FULL_SYNC_INTERVAL
    assert FULL_SYNC_INTERVAL == timedelta(days=3)
