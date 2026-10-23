"""Slice 1 · S1.6a (#67): pair measurement per backlinks intervention.

The real measure_channel, reach.coverage and rows paging run against
FakeSupabase; nothing else is faked.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import lever_measurement as lm
from app import reach
from app.config import settings
from tests.fakes import FakeSupabase

CH, SIB, OFF = "UCmarathi1", "UChindi001", "UCnotingest"
SRC, T1, T2, T3 = "srcVideo001", "tgtVideo001", "tgtVideo002", "hinVideo001"
TRAFFIC = "channel_traffic_source_a3"
D0 = date(2026, 10, 1)
TODAY = date(2026, 10, 20)


def day(n: int) -> str:
    """D0 + n, as an ISO data-day."""
    return (D0 + timedelta(days=n)).isoformat()


def ledger(channel: str, through: int, start: int = -10) -> list[dict]:
    return [{"report_id": f"{channel}-{n}", "channel_id": channel, "report_type": TRAFFIC,
             "data_date": day(n)} for n in range(start, through + 1)]


def traffic(video: str, n: int, views: int, source_type: int = 7, detail: str = SRC,
            channel: str = CH) -> dict:
    return {"video_id": video, "channel_id": channel, "date": day(n),
            "source_type": source_type, "source_detail": detail, "views": views}


def source_daily(views_per_day: int, days=range(1, 15)) -> list[dict]:
    """The source's own views (any type), so the floor can be met or missed."""
    return [traffic(SRC, n, views_per_day, source_type=3, detail="") for n in days]


def treated(id_=1, targets=((T1, CH), (T2, CH)), **kw) -> dict:
    return {"id": id_, "video_id": SRC, "channel_id": CH, "lever": "backlinks",
            "origin": "midas", "arm": "treated", "status": "measuring",
            "payload": {"targets": [{"video_id": t, "channel_id": c, "title": t}
                                    for t, c in targets]},
            "applied_at": f"{D0.isoformat()}T10:00:00+00:00",
            "created_at": f"{D0.isoformat()}T09:59:59+00:00",
            "detected_at": None, "measurement_status": None, "measurement_result": None, **kw}


def holdout(id_=2, **kw) -> dict:
    return treated(id_, **{"arm": "holdout", "status": "holdout", "applied_at": None,
                           "created_at": f"{D0.isoformat()}T23:30:00+00:00", **kw})


def human(id_=3, target=T1, channel=CH, **kw) -> dict:
    return {**treated(id_), "origin": "human", "arm": "n/a", "status": "applied",
            "channel_id": channel, "applied_at": None,
            "created_at": f"{D0.isoformat()}T04:00:00+00:00",
            "detected_at": f"{D0.isoformat()}T04:00:00+00:00",
            "payload": {"source_video_id": SRC, "target_video_id": target}, **kw}


VIDEOS = [{"id": v, "channel_id": c} for v, c in
          ((SRC, CH), (T1, CH), (T2, CH), (T3, SIB))]


@contextmanager
def db(interventions, rows, ingested):
    sb = FakeSupabase({"interventions": interventions, "video_traffic_source_daily": rows,
                       "reporting_reports_ingested": ingested, "videos": VIDEOS})
    with patch.object(lm, "supabase", return_value=sb), \
         patch.object(reach, "supabase", return_value=sb), \
         patch.object(settings, "TRAFFIC_INGEST_CHANNELS", {CH, SIB}), \
         patch.object(settings, "LEVER_MIN_SOURCE_VIEWS", 100):
        yield sb


def stored(sb, id_=1) -> dict:
    return next(r for r in sb.rows("interventions") if r["id"] == id_)


# ── pair views ───────────────────────────────────────────────────────────

def test_pair_views_select_exactly_type_7_from_the_source_summed_over_the_targets():
    rows = [
        traffic(T1, 2, 5), traffic(T2, 3, 7),            # counted: 12
        traffic(T1, 2, 100, detail="otherVideo1"),       # another source
        traffic(T1, 2, 100, source_type=3),              # browse, detail = A
        traffic(T1, 2, 100, detail=""),                  # the folded blank bucket
        traffic(T3, 2, 100),                             # not a target
        traffic(T1, 9, 100),                             # outside the window
    ]
    with db([], rows, []):
        assert lm.pair_views(SRC, [T1, T2], (day(1), day(7))) == 12


# ── windows and d0 ───────────────────────────────────────────────────────

def test_pre_and_post_windows_exclude_d0():
    assert lm.windows(D0) == ((day(-7), day(-1)), (day(1), day(7)))
    assert lm.windows(D0, 14) == ((day(-7), day(-1)), (day(1), day(14)))


@pytest.mark.parametrize("row", [
    treated(applied_at="2026-10-01T23:00:00-05:00"),       # 2026-10-02 in UTC
    holdout(created_at="2026-10-02T00:30:00+00:00"),
    human(detected_at="2026-10-02T12:00:00Z"),
], ids=["treated: applied_at", "holdout: created_at", "human: detected_at"])
def test_d0_per_kind_and_the_windows_measured_around_it(row):
    d0 = date(2026, 10, 2)
    assert lm.as_of(row) == d0
    rows = source_daily(50, range(1, 9)) + [
        traffic(T1, -6, 1),        # d0-7: the first pre day
        traffic(T1, 0, 2),         # d0-2
        traffic(T1, 1, 40),        # d0 itself: in neither window
        traffic(T1, 2, 3),         # d0+1: the first post day
        traffic(T1, 8, 4),         # d0+7: the last post day
        traffic(T1, 9, 500),       # d0+8: outside
    ]
    with db([row], rows, ledger(CH, 9)) as sb:
        lm.measure_channel(CH, today=TODAY)
    got = stored(sb, row["id"])
    assert got["status"] == "judged"
    result = got["measurement_result"]
    assert result["window"] == {"d0": "2026-10-02", "pre": ["2026-09-25", "2026-10-01"],
                                "post": ["2026-10-03", "2026-10-09"], "post_days": 7,
                                "extended": False}
    assert (result["pre"], result["post"], result["delta"]) == (3, 7, 4)


def test_a_judged_row_carries_pre_post_delta_source_views_and_window():
    rows = source_daily(20, range(1, 8)) + [traffic(T1, -3, 2), traffic(T1, 3, 6),
                                            traffic(T2, 4, 1)]
    with db([treated()], rows, ledger(CH, 7)) as sb:
        counts = lm.measure_channel(CH, today=TODAY)
    got = stored(sb)
    assert got["status"] == "judged"
    assert got["measurement_status"] == "done"
    r = got["measurement_result"]
    assert (r["pre"], r["post"], r["delta"], r["source_views"]) == (2, 7, 5, 140)
    assert r["judged_at"] == r["computed_at"]
    assert counts["judged"] == 1 and counts["attempted"] == 1 and counts["errored"] == 0


# ── completeness ─────────────────────────────────────────────────────────

def test_completeness_waits_for_a_lagging_target_channel():
    row = treated(targets=((T1, CH), (T3, SIB)))
    rows = source_daily(50) + [traffic(T3, 2, 4, channel=SIB)]
    ingested = ledger(CH, 12) + ledger(SIB, 6)          # Hindi one day short of d0+7
    with db([row], rows, ingested) as sb:
        counts = lm.measure_channel(CH, today=TODAY)
        assert stored(sb)["status"] == "measuring"
        assert stored(sb)["measurement_status"] == "awaiting_window"
        assert counts["awaiting_window"] == 1

        sb._tables["reporting_reports_ingested"].extend(ledger(SIB, 7, start=7))
        lm.measure_channel(CH, today=TODAY)
    assert stored(sb)["status"] == "judged"
    assert stored(sb)["measurement_result"]["post"] == 4


def test_completeness_also_needs_the_source_channels_own_report():
    """The source's views come from its own channel's report."""
    row = treated(targets=((T3, SIB),))
    with db([row], source_daily(50), ledger(CH, 5) + ledger(SIB, 10)) as sb:
        lm.measure_channel(CH, today=TODAY)
    assert stored(sb)["measurement_status"] == "awaiting_window"


def test_a_human_targets_channel_is_read_from_videos():
    row = human(target=T3)
    with db([row], source_daily(50), ledger(CH, 10) + ledger(SIB, 6)) as sb:
        lm.measure_channel(CH, today=TODAY)
        assert stored(sb, 3)["status"] == "applied"
        assert stored(sb, 3)["measurement_status"] == "awaiting_window"
        sb._tables["reporting_reports_ingested"].extend(ledger(SIB, 7, start=7))
        lm.measure_channel(CH, today=TODAY)
    assert stored(sb, 3)["status"] == "judged"


# ── the floor and the one extension ──────────────────────────────────────

def test_under_the_floor_the_post_window_extends_once_then_insufficient_data():
    # 5 views a day: 35 at 7 days, 70 at 14, under the floor of 100 both times.
    rows = source_daily(5) + [traffic(T1, 2, 1)]
    with db([treated()], rows, ledger(CH, 10)) as sb:
        lm.measure_channel(CH, today=TODAY)
        assert stored(sb)["status"] == "measuring"
        assert stored(sb)["measurement_status"] == "extended"

        sb._tables["reporting_reports_ingested"].extend(ledger(CH, 14, start=11))
        counts = lm.measure_channel(CH, today=TODAY)
    got = stored(sb)
    assert got["status"] == "insufficient_data"
    assert got["measurement_status"] == "done"
    assert got["measurement_result"]["source_views"] == 70
    assert got["measurement_result"]["window"]["post"] == [day(1), day(14)]
    assert counts["insufficient_data"] == 1


def test_reaching_the_floor_in_the_extension_is_judged_on_14_days_per_week():
    rows = source_daily(8) + [traffic(T1, -2, 3), traffic(T1, 2, 4), traffic(T1, 12, 6)]
    with db([treated()], rows, ledger(CH, 14)) as sb:
        lm.measure_channel(CH, today=TODAY)
    r = stored(sb)["measurement_result"]
    assert stored(sb)["status"] == "judged"
    assert r["source_views"] == 112
    assert r["window"]["extended"] is True and r["window"]["post_days"] == 14
    # 10 views over 14 days is 5 a week, against 3 in the 7-day pre.
    assert (r["pre"], r["post"], r["delta"]) == (3, 10, 2.0)


def test_pair_views_near_zero_are_judged_not_discarded():
    with db([treated()], source_daily(50), ledger(CH, 7)) as sb:
        lm.measure_channel(CH, today=TODAY)
    assert stored(sb)["status"] == "judged"
    assert stored(sb)["measurement_result"]["delta"] == 0


# ── restatements ─────────────────────────────────────────────────────────

def test_a_restated_day_changes_a_recently_judged_row_on_the_next_run():
    rows = source_daily(50) + [traffic(T1, 3, 4)]
    with db([treated()], rows, ledger(CH, 10)) as sb:
        lm.measure_channel(CH, today=date.fromisoformat(day(10)))
        first = stored(sb)["measurement_result"]
        assert first["post"] == 4

        # traffic_poll replaces the day with the restated report's rows.
        table = sb._tables["video_traffic_source_daily"]
        table[:] = [r for r in table if not (r["video_id"] == T1 and r["date"] == day(3))]
        table.append(traffic(T1, 3, 9))
        counts = lm.measure_channel(CH, today=date.fromisoformat(day(11)))
    again = stored(sb)["measurement_result"]
    assert again["post"] == 9 and again["delta"] == 9
    assert again["judged_at"] == first["judged_at"]
    assert stored(sb)["status"] == "judged"
    assert counts["changed"] == 1


def test_a_restatement_that_reopens_the_extension_keeps_the_verdict_until_it_can_decide():
    """Judged at 7 days; a restated source day takes it under the floor, and the
    14-day window isn't complete yet: the verdict stands, nothing is written."""
    with db([treated()], source_daily(15, range(1, 8)), ledger(CH, 8)) as sb:
        lm.measure_channel(CH, today=TODAY)
        assert stored(sb)["status"] == "judged"
        writes = len(sb.writes)
        table = sb._tables["video_traffic_source_daily"]
        table[:] = [r for r in table if r["date"] != day(1)]       # 105 -> 90
        lm.measure_channel(CH, today=TODAY)
    assert stored(sb)["status"] == "judged"
    assert stored(sb)["measurement_status"] == "done"
    assert len(sb.writes) == writes


def test_a_judged_row_past_the_restatement_horizon_is_left_alone():
    rows = source_daily(50) + [traffic(T1, 3, 4)]
    with db([treated()], rows, ledger(CH, 10)) as sb:
        lm.measure_channel(CH, today=date.fromisoformat(day(10)))
        sb._tables["video_traffic_source_daily"].append(traffic(T2, 3, 9))
        late = date.fromisoformat(day(7 + lm.RESTATEMENT_HORIZON_DAYS + 1))
        counts = lm.measure_channel(CH, today=late)
    assert stored(sb)["measurement_result"]["post"] == 4
    assert counts["attempted"] == 0


def test_an_unchanged_run_writes_nothing():
    with db([treated()], source_daily(50) + [traffic(T1, 3, 4)], ledger(CH, 10)) as sb:
        lm.measure_channel(CH, today=TODAY)
        before = len(sb.writes)
        counts = lm.measure_channel(CH, today=TODAY)
    assert len(sb.writes) == before
    assert counts == {**counts, "attempted": 1, "judged": 1, "changed": 0}


def test_a_waiting_row_is_written_once_per_progress_step():
    with db([treated()], source_daily(50), ledger(CH, 3)) as sb:
        lm.measure_channel(CH, today=TODAY)
        lm.measure_channel(CH, today=TODAY)
    assert sb.writes == [("interventions", "update", {"measurement_status": "awaiting_window"})]


# ── which rows ───────────────────────────────────────────────────────────

def test_only_treated_holdout_and_human_backlinks_rows_are_measured():
    rows = [
        treated(1), holdout(2), human(3),
        treated(4, status="cancelled"),                              # reverted / never applied
        treated(5, status="planned", applied_at=None),
        treated(6, arm="n/a", status="declined", applied_at=None),
        {**treated(7), "lever": "playlist"},
        {**treated(8), "channel_id": SIB},                           # another channel's source
    ]
    with db(rows, source_daily(50), ledger(CH, 10)) as sb:
        counts = lm.measure_channel(CH, today=TODAY)
    assert counts["attempted"] == 3
    assert {r["id"] for r in sb.rows("interventions") if r["status"] == "judged"} == {1, 2, 3}


def test_human_rows_are_measured_only_on_traffic_ingest_channels():
    row = human(channel=OFF)
    sb = FakeSupabase({"interventions": [row], "video_traffic_source_daily": source_daily(50),
                       "reporting_reports_ingested": ledger(OFF, 10) + ledger(CH, 10),
                       "videos": VIDEOS})
    with patch.object(lm, "supabase", return_value=sb), \
         patch.object(reach, "supabase", return_value=sb), \
         patch.object(settings, "TRAFFIC_INGEST_CHANNELS", {CH}):
        counts = lm.measure_channel(OFF, today=TODAY)
    assert counts["attempted"] == 0
    assert sb.writes == []


def test_a_bad_row_is_counted_and_the_others_still_run():
    bad = treated(1, payload={"targets": []})
    with db([bad, holdout(2)], source_daily(50), ledger(CH, 10)) as sb:
        counts = lm.measure_channel(CH, today=TODAY)
    assert (counts["attempted"], counts["errored"], counts["judged"]) == (2, 1, 1)
    assert stored(sb, 1)["status"] == "measuring"
    assert stored(sb, 2)["status"] == "judged"


# ── paging ───────────────────────────────────────────────────────────────

def test_reads_are_paged_past_the_row_cap():
    """1,400 rows of the source's own traffic: an unpaged read would see 1,000."""
    rows = [traffic(SRC, 1 + i % 7, 1, source_type=8, detail=f"d{i}") for i in range(1400)]
    with db([treated()], rows + [traffic(T1, 2, 3)], ledger(CH, 7)) as sb:
        lm.measure_channel(CH, today=TODAY)
    assert stored(sb)["measurement_result"]["source_views"] == 1400
