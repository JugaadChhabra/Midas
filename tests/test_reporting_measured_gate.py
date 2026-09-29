"""reporting_poll skips non-measurement channels (video_reach_daily bloat fix).

The rule itself now lives in app.eligibility (Job.REACH) — see
tests/test_eligibility.py. What this file still asserts is that the POLLER
honours it end to end, which is the behaviour that mattered when the flag was
introduced and is worth keeping independent of where the predicate lives.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent

import app.eligibility as el
import app.reporting_poll as rp
from app.analytics_client import AnalyticsNotAuthorizedError
from app.job_status import JobRunFailed, JobStatusRegistry
from app.youtube_client import TokenExpiredError


def _sb():
    sb = MagicMock()
    # eligibility pages via all_rows: .select().eq()[.or_()].order().range().execute()
    first_eq = sb.table.return_value.select.return_value.eq.return_value
    first_eq.order.return_value.range.return_value.execute.return_value.data = []
    first_eq.or_.return_value.order.return_value.range.return_value \
        .execute.return_value.data = []
    return sb, first_eq


def test_gates_on_the_measurement_optin_when_flag_on():
    """Either flag opts a channel in: measurement_enabled channels consume the
    reach/ctr backfill, and reach_warmup channels are accruing the coverage
    needed to certify CTR *before* measurement is switched on."""
    sb, first_eq = _sb()
    with patch.object(el.settings, "REPORTING_MEASURED_CHANNELS_ONLY", True), \
         patch.object(el, "supabase", return_value=sb):
        rp.poll_reporting()
    first_eq.or_.assert_called_once_with(
        "measurement_enabled.eq.true,reach_warmup.eq.true")


def test_polls_all_authorized_when_flag_off():
    sb, first_eq = _sb()
    with patch.object(el.settings, "REPORTING_MEASURED_CHANNELS_ONLY", False), \
         patch.object(el, "supabase", return_value=sb):
        rp.poll_reporting()
    first_eq.or_.assert_not_called()   # no opt-in filter


# ── failure reporting (A8 finish, #23) ────────────────────────────────────
#
# Same shape as metrics_poll: per-channel isolation, but a crash now fails the
# run (JobRunFailed) once every channel has been polled.

def _poll_with(channel_ids, poll_channel, ran):
    def _one(cid):
        ran.append(cid)
        return poll_channel(cid)

    with patch.object(rp.eligibility, "channels_for",
                      return_value=[{"id": c} for c in channel_ids]), \
         patch.object(rp, "_poll_channel", side_effect=_one):
        rp.poll_reporting()


def test_one_crash_still_polls_the_rest_then_fails_the_run():
    def poll(cid):
        if cid == "bad":
            raise RuntimeError("reports.list 500")
        return {}

    ran = []
    with pytest.raises(JobRunFailed) as exc_info:
        _poll_with(["bad", "good"], poll, ran)

    assert ran == ["bad", "good"]
    assert exc_info.value.failed_channels == {"bad": "RuntimeError: reports.list 500"}

    reg = JobStatusRegistry()
    reg.on_event(JobExecutionEvent(EVENT_JOB_ERROR, "reporting_poll", "default",
                                   datetime(2026, 9, 29, tzinfo=timezone.utc),
                                   exception=exc_info.value))
    entry = reg.snapshot()["reporting_poll"]
    assert entry["status"] == "failed"
    assert entry["failed_channels"] == {"bad": "RuntimeError: reports.list 500"}


def test_all_channels_succeeding_is_success():
    ran = []
    _poll_with(["a", "b"], lambda cid: {}, ran)
    assert ran == ["a", "b"]


def test_expected_skips_are_not_failures():
    def poll(cid):
        if cid == "unauthorized":
            raise AnalyticsNotAuthorizedError(cid)
        raise TokenExpiredError(cid)

    ran = []
    _poll_with(["unauthorized", "expired"], poll, ran)
    assert ran == ["unauthorized", "expired"]


def test_no_channels_is_success():
    with patch.object(rp.eligibility, "channels_for", return_value=[]):
        assert rp.poll_reporting() is None
