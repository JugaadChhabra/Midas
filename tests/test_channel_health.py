"""app/channel_health.py: which channels have quietly stopped being watched
(the 2026-10-16 sign-in outage was a week of `success` in /health/jobs)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app import channel_health as ch_health
from app.job_status import JobRunFailed

NOW = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)


def _days(*isos):
    return set(isos)


def _status(ch, *, reach=None, traffic=None, reach_ids=(), traffic_ids=()):
    def coverage(channel_id, *, report_type="channel_reach_basic_a1"):
        return (traffic if report_type != "channel_reach_basic_a1" else reach) or set()
    with patch.object(ch_health.reach, "coverage", side_effect=coverage):
        return ch_health.channel_status(ch, reach_ids=set(reach_ids),
                                        traffic_ids=set(traffic_ids), now=NOW)


def test_a_fresh_channel_has_no_problems():
    ch = {"id": "A", "last_synced_at": (NOW - timedelta(hours=6)).isoformat()}
    s = _status(ch, reach=_days("2026-10-21"), traffic=_days("2026-10-23"),
                reach_ids={"A"}, traffic_ids={"A"})
    assert s["problems"] == []
    assert (s["reach_days_behind"], s["traffic_days_behind"]) == (4, 2)


def test_the_outage_shape_is_flagged():
    """Sync stale and traffic stuck at 10-14: what Hindi looked like on 10-24."""
    ch = {"id": "H", "last_synced_at": (NOW - timedelta(days=9)).isoformat(),
          "autopilot_paused_reason": "token_expired"}
    s = _status(ch, reach=_days("2026-10-14"), traffic=_days("2026-10-14"),
                reach_ids={"H"}, traffic_ids={"H"})
    assert s["problems"] == [
        "sync: last synced 216 h ago",
        "reach: frontier 2026-10-14 is 11 days behind",
        "traffic: frontier 2026-10-14 is 11 days behind",
        "autopilot paused: token_expired",
    ]


def test_never_synced_and_never_ingested_are_problems():
    s = _status({"id": "K", "last_synced_at": None}, reach_ids={"K"})
    assert s["problems"] == ["sync: never synced", "reach: nothing ingested yet"]


def test_a_channel_outside_a_feed_is_not_judged_on_it():
    ch = {"id": "R", "last_synced_at": NOW.isoformat()}
    assert _status(ch)["problems"] == []


@pytest.mark.parametrize("hours,stale", [(ch_health.SYNC_STALE_HOURS, False),
                                         (ch_health.SYNC_STALE_HOURS + 1, True)])
def test_sync_threshold(hours, stale):
    ch = {"id": "A", "last_synced_at": (NOW - timedelta(hours=hours)).isoformat()}
    assert bool(_status(ch)["problems"]) is stale


def test_check_lists_problems_first_and_counts_them():
    rows = [{"id": "ok", "name": "A", "last_synced_at": NOW.isoformat()},
            {"id": "bad", "name": "B", "last_synced_at": None}]
    with patch.object(ch_health.eligibility, "channel_ids_for", return_value=[]), \
         patch.object(ch_health.eligibility, "channels_for", return_value=rows):
        out = ch_health.check(now=NOW)
    assert out["with_problems"] == 1
    assert [c["id"] for c in out["channels"]] == ["bad", "ok"]


def test_the_daily_job_fails_naming_each_channel_with_a_problem():
    report = {"channels": [{"id": "bad", "problems": ["sync: never synced", "x"]},
                           {"id": "ok", "problems": []}]}
    with patch.object(ch_health, "check", return_value=report), \
         pytest.raises(JobRunFailed) as exc:
        ch_health.run_daily()
    assert exc.value.failed_channels == {"bad": "sync: never synced; x"}


def test_the_daily_job_passes_when_every_channel_is_fresh():
    with patch.object(ch_health, "check", return_value={"channels": [{"id": "ok", "problems": []}]}):
        ch_health.run_daily()
