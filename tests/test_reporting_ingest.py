"""Reporting API jobs and the reach ingester's latest-wins handling.

Fakes sit at the edges only: a fake youtubereporting service for jobs, a
FakeSupabase for the tables, and the CSV download patched to return a body.
The functions under test are the real ones.
"""
from unittest.mock import patch

import pytest

import app.reporting_client as rc
import app.reporting_poll as rp
from tests.fakes import FakeSupabase

CH = "UCr5-YUqBiW7PUmeAtxUWuRg"


# ── a fake youtubereporting service ───────────────────────────────────────

class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Jobs:
    def __init__(self, jobs):
        self.jobs = jobs
        self.created: list[dict] = []

    def list(self, **_kw):
        return _Call({"jobs": list(self.jobs)})

    def create(self, body):
        self.created.append(body)
        job = {"id": f"new-{len(self.created)}", **body}
        self.jobs.append(job)
        return _Call(job)


class _Service:
    def __init__(self, jobs):
        self._jobs = _Jobs(jobs)

    def jobs(self):
        return self._jobs


def _handle(jobs):
    return rc.ReportingHandle(service=_Service(jobs), creds=None)


# Marathi's two traffic jobs as created on 2026-09-29 (docs/PHASE_A_FINDINGS.md
# A1.1), plus a reach job.
MARATHI_JOBS = [
    {"id": "3647f5d8-d935-43dc-8745-38ba143ca5ec",
     "reportTypeId": "channel_traffic_source_a3", "name": "midas-traffic-source"},
    {"id": "381cf084-cbf7-4af1-955d-4d170dd07b56",
     "reportTypeId": "playlist_traffic_source_a2", "name": "midas-playlist-traffic-source"},
    {"id": "reach-1", "reportTypeId": "channel_reach_basic_a1", "name": "midas-reach"},
]


def test_existing_reach_job_is_found_not_recreated():
    h = _handle([dict(j) for j in MARATHI_JOBS])
    with patch.object(rc.settings, "DRY_RUN", False):
        assert rc.ensure_reach_job(h, CH) == "reach-1"
    assert h.service.jobs().created == []


def test_missing_reach_job_is_created_with_the_reach_name():
    h = _handle([])
    with patch.object(rc.settings, "DRY_RUN", False):
        job_id = rc.ensure_reach_job(h, CH)
    assert job_id == "new-1"
    assert h.service.jobs().created == [
        {"reportTypeId": "channel_reach_basic_a1", "name": "midas-reach"}]


def test_missing_reach_job_under_dry_run_is_not_created():
    h = _handle([])
    with patch.object(rc.settings, "DRY_RUN", True):
        assert rc.ensure_reach_job(h, CH) is None
    assert h.service.jobs().created == []


# ── reach ingest: latest wins per data-day ────────────────────────────────

REACH_HEADER = ("date,channel_id,video_id,video_thumbnail_impressions,"
                "video_thumbnail_impressions_ctr\n")


def _report(rid, day="2026-09-29"):
    return {"id": rid, "startTime": f"{day}T07:00:00Z", "downloadUrl": f"https://x/{rid}"}


def _reach_csv(*rows):
    return REACH_HEADER + "".join(f"20260929,{CH},{v},{imp},{ctr}\n" for v, imp, ctr in rows)


def _ingest_reach(sb, report, body):
    with patch.object(rp, "supabase", return_value=sb), \
         patch.object(rp, "download_report_csv", return_value=body):
        return rp._ingest_report(None, CH, "reach-1", report)


def test_reach_reissue_replaces_the_day_and_renulls_overlapping_windows():
    sb = FakeSupabase({
        "video_reach_daily": [],
        "reporting_reports_ingested": [],
        "video_metrics": [{"id": 1, "channel_id": CH, "window_start": "2026-09-23",
                           "window_end": "2026-09-29", "impressions": 99, "ctr": 0.1}],
    })
    assert _ingest_reach(sb, _report("r1"), _reach_csv(("a", 10, 0.1), ("b", 20, 0.2))) == 2
    # The window was filled from r1 before the correction arrived.
    assert sb.rows("video_metrics")[0]["impressions"] == 99

    assert _ingest_reach(sb, _report("r2"), _reach_csv(("a", 12, 0.1))) == 1

    rows = sb.rows("video_reach_daily")
    assert [(r["video_id"], r["impressions"], r["report_id"]) for r in rows] == [("a", 12, "r2")]
    assert sb.rows("video_metrics")[0]["impressions"] is None
    assert {r["report_id"] for r in sb.rows("reporting_reports_ingested")} == {"r1", "r2"}


def test_reach_first_ingest_of_a_day_leaves_windows_alone():
    sb = FakeSupabase({
        "video_reach_daily": [],
        "reporting_reports_ingested": [],
        "video_metrics": [{"id": 1, "channel_id": CH, "window_start": "2026-09-23",
                           "window_end": "2026-09-29", "impressions": 99, "ctr": 0.1}],
    })
    _ingest_reach(sb, _report("r1"), _reach_csv(("a", 10, 0.1)))
    assert sb.rows("video_metrics")[0]["impressions"] == 99
    ledger = sb.rows("reporting_reports_ingested")
    assert [(r["report_id"], r["job_id"], r["data_date"], r["row_count"]) for r in ledger] == \
        [("r1", "reach-1", "2026-09-29", 1)]


# ── the shared ledger: traffic reports must not leak into reach ───────────

TRAFFIC_LEDGER_ROW = {"report_id": "t1", "job_id": "3647f5d8-d935-43dc-8745-38ba143ca5ec",
                      "channel_id": CH, "data_date": "2026-09-29", "row_count": 5,
                      "report_type": "channel_traffic_source_a3"}


def test_reach_ledger_rows_record_their_report_type():
    sb = FakeSupabase({"video_reach_daily": [], "reporting_reports_ingested": [],
                       "video_metrics": []})
    _ingest_reach(sb, _report("r1"), _reach_csv(("a", 10, 0.1)))
    assert sb.rows("reporting_reports_ingested")[0]["report_type"] == "channel_reach_basic_a1"


def test_a_traffic_report_for_the_same_day_is_not_a_reach_reissue():
    sb = FakeSupabase({
        "video_reach_daily": [],
        "reporting_reports_ingested": [dict(TRAFFIC_LEDGER_ROW)],
        "video_metrics": [{"id": 1, "channel_id": CH, "window_start": "2026-09-23",
                           "window_end": "2026-09-29", "impressions": 99, "ctr": 0.1}],
    })
    _ingest_reach(sb, _report("r1"), _reach_csv(("a", 10, 0.1)))
    assert sb.rows("video_metrics")[0]["impressions"] == 99


def test_traffic_reports_do_not_count_as_reach_coverage():
    import app.reach as reach
    sb = FakeSupabase({"reporting_reports_ingested": [
        dict(TRAFFIC_LEDGER_ROW),
        {"report_id": "r1", "job_id": "reach-1", "channel_id": CH,
         "data_date": "2026-09-28", "row_count": 1, "report_type": "channel_reach_basic_a1"},
    ]})
    with patch.object(reach, "supabase", return_value=sb):
        assert reach.coverage(CH) == {"2026-09-28"}
