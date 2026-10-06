"""traffic_poll: channel_traffic_source_a3 → video_traffic_source_daily (B1, #30).

Fakes at the edges only: a fake youtubereporting service, FakeSupabase for the
tables, and the CSV download patched to return a body. Parsing, aggregation,
the latest-wins replace and the health verdict are the real code.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler

import app.reporting_client as rc
import app.reporting_poll as rp
import app.traffic_poll as tp
from app.job_status import JobRunFailed, JobStatusRegistry
from tests.fakes import FakeSupabase
from tests.test_reporting_ingest import CH, MARATHI_JOBS, _handle

TRAFFIC_JOB = "3647f5d8-d935-43dc-8745-38ba143ca5ec"

HEADER = ("date,channel_id,video_id,live_or_on_demand,subscribed_status,country_code,"
          "traffic_source_type,traffic_source_detail,views,engaged_views,watch_time_minutes,"
          "average_view_duration_seconds,average_view_duration_percentage,red_views,"
          "red_watch_time_minutes\n")


def _row(video, stype, detail, views, engaged, minutes, *, country="IN",
         subscribed="not_subscribed", live="on_demand", day="20260929"):
    return (f"{day},{CH},{video},{live},{subscribed},{country},{stype},{detail},"
            f"{views},{engaged},{minutes},30,40.5,0,0\n")


def _csv(*rows):
    return HEADER + "".join(rows)


def _report(rid, day="2026-09-29", created="2026-10-01T10:00:00Z"):
    return {"id": rid, "startTime": f"{day}T07:00:00Z", "createTime": created,
            "downloadUrl": f"https://x/{rid}"}


# ── parse + aggregate ─────────────────────────────────────────────────────

def test_aggregation_sums_across_the_three_dropped_dimensions():
    rows = rc.parse_traffic_csv(_csv(
        _row("v1", 7, "src1", 10, 4, 2.5, country="IN", subscribed="subscribed"),
        _row("v1", 7, "src1", 5, 1, 1.0, country="US", subscribed="not_subscribed"),
        _row("v1", 7, "src1", 1, 0, 0.25, country="IN", live="live"),
        # A different detail, type or video is a different row.
        _row("v1", 7, "src2", 3, 3, 3.0),
        _row("v1", 14, "src1", 2, 2, 2.0),
        _row("v2", 7, "src1", 7, 7, 7.0),
    ))
    by_key = {(r["video_id"], r["source_type"], r["source_detail"]): r for r in rows}
    assert len(rows) == 4
    assert by_key[("v1", 7, "src1")] == {
        "video_id": "v1", "date": "2026-09-29", "source_type": 7, "source_detail": "src1",
        "views": 16, "engaged_views": 5, "watch_time_minutes": 3.75,
    }
    assert by_key[("v1", 7, "src2")]["views"] == 3
    assert by_key[("v1", 14, "src1")]["views"] == 2
    assert by_key[("v2", 7, "src1")]["views"] == 7


def test_source_type_is_stored_as_the_numeric_code_and_empty_detail_as_blank():
    (row,) = rc.parse_traffic_csv(_csv(_row("v1", 5, "", 1, 1, 1.0)))
    assert row["source_type"] == 5 and isinstance(row["source_type"], int)
    assert row["source_detail"] == ""


def test_an_unexpected_header_is_rejected():
    with pytest.raises(ValueError, match="unexpected traffic CSV header"):
        rc.parse_traffic_csv("date,channel_id,video_id\n20260929,c,v\n")


def test_codes_map_to_names():
    # From docs/PHASE_A_FINDINGS.md A1.1, which copied
    # https://developers.google.com/youtube/reporting/v1/reports/dimensions
    assert rc.traffic_source_name(0) == "Direct or unknown"
    assert rc.traffic_source_name(7) == "Suggested videos"
    assert rc.traffic_source_name(14) == "Playlists"
    assert rc.traffic_source_name(24) == "Shorts"
    assert rc.traffic_source_name(32) == "Related video"
    assert rc.traffic_source_name(2) is None
    # Every code A1.1 saw in Marathi's 2026-09-29 reports has a name.
    for code in (14, 7, 24, 4, 3, 8, 5, 9, 0, 18, 20, 26, 32, 27, 17):
        assert rc.traffic_source_name(code), code
    assert len(rc.TRAFFIC_SOURCE_TYPES) == 24


# ── jobs ──────────────────────────────────────────────────────────────────

def test_existing_traffic_job_is_found_not_recreated():
    h = _handle([dict(j) for j in MARATHI_JOBS])
    with patch.object(rc.settings, "DRY_RUN", False):
        assert rc.ensure_traffic_job(h, CH) == TRAFFIC_JOB
    assert h.service.jobs().created == []


def test_missing_traffic_job_is_created_with_the_traffic_name():
    h = _handle([j for j in MARATHI_JOBS if j["reportTypeId"] != "channel_traffic_source_a3"])
    with patch.object(rc.settings, "DRY_RUN", False):
        assert rc.ensure_traffic_job(h, CH) == "new-1"
    assert h.service.jobs().created == [
        {"reportTypeId": "channel_traffic_source_a3", "name": "midas-traffic-source"}]


# ── one channel's poll ────────────────────────────────────────────────────

def _sb(ledger=None, traffic=None):
    return FakeSupabase({
        "reporting_reports_ingested": ledger or [],
        "video_traffic_source_daily": traffic or [],
    })


def _poll(sb, reports, bodies):
    """Run the real _poll_channel with the given listed reports and CSV bodies
    (by report id; an Exception value is raised by the download)."""
    def download(_h, _c, url):
        body = bodies[url.rsplit("/", 1)[1]]
        if isinstance(body, Exception):
            raise body
        return body

    with patch.object(rp, "supabase", return_value=sb), \
         patch.object(tp, "reporting_for_channel", return_value=_handle([dict(j) for j in MARATHI_JOBS])), \
         patch.object(tp, "list_reports", return_value=reports), \
         patch.object(tp, "download_report_csv", side_effect=download):
        return tp._poll_channel(CH)


def test_a_report_lands_aggregated_with_its_report_id_and_is_ledgered():
    sb = _sb()
    counts = _poll(sb, [_report("r1")], {"r1": _csv(
        _row("v1", 7, "src", 2, 1, 1.0, country="IN"),
        _row("v1", 7, "src", 3, 1, 1.0, country="US"),
    )})
    assert counts["reports_new"] == 1 and counts["reports_err"] == 0
    assert counts["rows_ingested"] == 1
    (row,) = sb.rows("video_traffic_source_daily")
    assert (row["video_id"], row["channel_id"], row["date"], row["source_type"],
            row["source_detail"], row["views"], row["report_id"]) == \
        ("v1", CH, "2026-09-29", 7, "src", 5, "r1")
    (ledger,) = sb.rows("reporting_reports_ingested")
    assert ledger == {"report_id": "r1", "job_id": TRAFFIC_JOB, "channel_id": CH,
                      "data_date": "2026-09-29", "row_count": 1,
                      "report_type": "channel_traffic_source_a3"}


def test_a_restated_date_replaces_rather_than_adds():
    sb = _sb()
    _poll(sb, [_report("r1")], {"r1": _csv(
        _row("v1", 7, "a", 10, 1, 1.0), _row("v2", 7, "a", 4, 1, 1.0))})
    # The restatement corrects v1 and no longer lists v2.
    _poll(sb, [_report("r1"), _report("r2", created="2026-10-03T10:00:00Z")],
          {"r2": _csv(_row("v1", 7, "a", 8, 1, 1.0))})

    rows = sb.rows("video_traffic_source_daily")
    assert [(r["video_id"], r["views"], r["report_id"]) for r in rows] == [("v1", 8, "r2")]
    assert sum(r["views"] for r in rows) == 8   # not 10 + 8, not 4 left over


def test_restatement_leaves_other_days_and_other_tables_alone():
    other_day = {"video_id": "v9", "channel_id": CH, "date": "2026-09-28", "source_type": 7,
                 "source_detail": "", "views": 1, "engaged_views": 1,
                 "watch_time_minutes": 1.0, "report_id": "r0"}
    sb = _sb(traffic=[other_day])
    _poll(sb, [_report("r1")], {"r1": _csv(_row("v1", 7, "a", 10, 1, 1.0))})
    _poll(sb, [_report("r2", created="2026-10-03T10:00:00Z")],
          {"r2": _csv(_row("v1", 7, "a", 8, 1, 1.0))})
    assert {(r["date"], r["report_id"]) for r in sb.rows("video_traffic_source_daily")} == \
        {("2026-09-28", "r0"), ("2026-09-29", "r2")}


def test_when_a_day_and_its_restatement_are_both_new_only_the_newest_lands():
    sb = _sb()
    counts = _poll(sb, [
        _report("r2", created="2026-10-03T10:00:00Z"),
        _report("r1", created="2026-10-01T10:00:00Z"),
    ], {"r1": _csv(_row("v1", 7, "a", 10, 1, 1.0)),
        "r2": _csv(_row("v1", 7, "a", 8, 1, 1.0))})
    assert counts["reports_new"] == 1
    assert [r["report_id"] for r in sb.rows("video_traffic_source_daily")] == ["r2"]


def test_an_already_ingested_report_is_skipped():
    sb = _sb(ledger=[{"report_id": "r1", "job_id": TRAFFIC_JOB, "channel_id": CH,
                      "data_date": "2026-09-29", "row_count": 1,
                      "report_type": "channel_traffic_source_a3"}])
    # No body for r1: downloading it would KeyError.
    counts = _poll(sb, [_report("r1")], {})
    assert counts["reports_new"] == 0 and counts["rows_ingested"] == 0
    assert sb.writes == []


def test_a_malformed_report_fails_only_that_report():
    sb = _sb()
    counts = _poll(sb, [_report("bad", day="2026-09-28"), _report("good")], {
        "bad": "date,channel_id\n20260928,x\n",
        "good": _csv(_row("v1", 7, "a", 1, 1, 1.0)),
    })
    assert counts["reports_new"] == 2 and counts["reports_err"] == 1
    assert [r["report_id"] for r in sb.rows("reporting_reports_ingested")] == ["good"]
    assert [r["report_id"] for r in sb.rows("video_traffic_source_daily")] == ["good"]


def test_a_bad_value_mid_report_writes_nothing_for_that_report():
    sb = _sb()
    counts = _poll(sb, [_report("bad")], {"bad": _csv(
        _row("v1", 7, "a", 1, 1, 1.0), _row("v2", 7, "a", "n/a", 1, 1.0))})
    assert counts["reports_err"] == 1
    assert sb.writes == []


def test_dry_run_with_no_job_skips_the_channel():
    sb = _sb()
    with patch.object(tp, "reporting_for_channel", return_value=_handle([])), \
         patch.object(rp, "supabase", return_value=sb), \
         patch.object(rc.settings, "DRY_RUN", True):
        assert tp._poll_channel(CH) == {"job": None, "reports_new": 0, "rows_ingested": 0}


# ── the run: health semantics ─────────────────────────────────────────────

def _run(channel_counts):
    def poll(cid):
        c = channel_counts[cid]
        if isinstance(c, Exception):
            raise c
        return c
    with patch.object(tp.eligibility, "channels_for",
                      return_value=[{"id": c} for c in channel_counts]), \
         patch.object(tp, "_poll_channel", side_effect=poll):
        return tp.poll_traffic()


def test_some_reports_failing_is_degraded_per_item_error_verdict():
    retval = _run({"c": {"reports_new": 4, "reports_err": 1}})
    assert retval == {"partial_errors": {"c": "reports: 1/4 failed"}}
    reg = JobStatusRegistry()
    reg.on_event(JobExecutionEvent(EVENT_JOB_EXECUTED, "traffic_poll", "default",
                                   datetime(2026, 10, 6, tzinfo=timezone.utc), retval=retval))
    assert reg.snapshot()["traffic_poll"]["status"] == "degraded"


def test_every_report_failing_fails_the_channel_and_the_run():
    with pytest.raises(JobRunFailed) as exc_info:
        _run({"stuck": {"reports_new": 2, "reports_err": 2}, "ok": {}})
    assert exc_info.value.failed_channels == {"stuck": "ItemsFailed: reports: all 2 failed"}


def test_a_channel_crash_fails_the_run_after_polling_the_rest():
    ran = []

    def poll(cid):
        ran.append(cid)
        if cid == "bad":
            raise RuntimeError("reports.list 500")
        return {}

    with patch.object(tp.eligibility, "channels_for",
                      return_value=[{"id": "bad"}, {"id": "good"}]), \
         patch.object(tp, "_poll_channel", side_effect=poll), \
         pytest.raises(JobRunFailed) as exc_info:
        tp.poll_traffic()
    assert ran == ["bad", "good"]
    assert exc_info.value.failed_channels == {"bad": "RuntimeError: reports.list 500"}


def test_expected_skips_are_not_failures():
    from app.analytics_client import AnalyticsNotAuthorizedError
    from app.youtube_client import TokenExpiredError
    assert _run({"a": AnalyticsNotAuthorizedError("a"), "b": TokenExpiredError("b")}) is None


def test_no_channels_is_success():
    with patch.object(tp.eligibility, "channels_for", return_value=[]):
        assert tp.poll_traffic() is None


def test_polls_the_traffic_ingest_channels():
    with patch.object(tp.eligibility, "channels_for", return_value=[]) as cf:
        tp.poll_traffic()
    cf.assert_called_once_with(tp.eligibility.Job.TRAFFIC)


# ── scheduling ────────────────────────────────────────────────────────────

def test_traffic_poll_is_registered_at_0630_utc_and_reaches_health_jobs():
    from app import main
    sched = BackgroundScheduler(daemon=True)
    main._register_jobs(sched)
    job = sched.get_job("traffic_poll")
    assert job is not None and job.func is tp.poll_traffic
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "6" and fields["minute"] == "30"
    assert str(job.trigger.timezone) == "UTC"
    assert job.max_instances == 1 and job.coalesce is True

    reg = JobStatusRegistry()
    reg.watch(sched)
    assert reg.snapshot()["traffic_poll"]["status"] == "never_run"


def test_default_ingest_channel_is_marathi():
    from app.config import Settings
    assert Settings.TRAFFIC_INGEST_CHANNELS == {"UCr5-YUqBiW7PUmeAtxUWuRg"}
