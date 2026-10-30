"""Slice 3 · S3.5 (#120): title measurement per video.

The real measure_channel, reach.coverage/aggregate and rows paging run against
FakeSupabase on fixed traffic and reach rows; nothing else is faked.
"""
import math
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import reach
from app import title_measurement as tm
from app.config import settings
from tests.fakes import FakeSupabase

CH = "UCmarathi1"
VID = "titleVideo1"
TRAFFIC = "channel_traffic_source_a3"
D0 = date(2026, 10, 1)
TODAY = date(2026, 10, 25)


def day(n: int) -> str:
    return (D0 + timedelta(days=n)).isoformat()


def ledger(through: int, start: int = -20, skip=()) -> list[dict]:
    return [{"report_id": f"r{n}", "channel_id": CH, "report_type": TRAFFIC, "data_date": day(n)}
            for n in range(start, through + 1) if n not in skip]


def traffic(n: int, views: int, source_type: int = 3, video: str = VID) -> dict:
    return {"video_id": video, "channel_id": CH, "date": day(n), "source_type": source_type,
            "source_detail": "", "views": views}


def daily(views: int, days, source_type: int = 3) -> list[dict]:
    return [traffic(n, views, source_type) for n in days]


def treated(id_=1, **kw) -> dict:
    """Applied at 03:00 UTC on D0 + 1: still D0 in Pacific time."""
    return {"id": id_, "video_id": VID, "channel_id": CH, "lever": "title", "origin": "midas",
            "arm": "treated", "status": "measuring",
            "payload": {"path": "pipeline", "title": "New", "title_before": "Old"},
            "applied_at": f"{day(1)}T03:00:00+00:00", "created_at": f"{day(1)}T02:59:00+00:00",
            "measurement_status": None, "measurement_result": None, **kw}


def holdout(id_=2, **kw) -> dict:
    return treated(id_, **{"arm": "holdout", "status": "holdout", "applied_at": None,
                           "created_at": f"{day(1)}T03:00:00+00:00", **kw})


def declined(id_=3, **kw) -> dict:
    return treated(id_, **{"status": "declined", "applied_at": None,
                           "payload": {"path": "agent", "title_before": "Old",
                                       "rationale": "already works"}, **kw})


@contextmanager
def db(interventions, rows, ingested, reach_rows=()):
    sb = FakeSupabase({"interventions": interventions, "video_traffic_source_daily": rows,
                       "reporting_reports_ingested": ingested,
                       "video_reach_daily": list(reach_rows)})
    with patch.object(tm, "supabase", return_value=sb), \
         patch.object(reach, "supabase", return_value=sb), \
         patch.multiple(settings, TITLE_WINDOW_DAYS=14, TITLE_MIN_PRE_VIEWS=100):
        yield sb


def test_windows_are_14_days_either_side_of_the_pacific_d0():
    pre, post = tm.windows(D0)
    assert pre == (day(-14), day(-1)) and post == (day(1), day(14))
    assert tm.as_of(treated()) == D0           # 03:00 UTC on D0 + 1 is D0 in Los Angeles
    assert tm.as_of(holdout()) == D0
    assert tm.as_of(declined()) == D0


def test_a_row_waits_until_the_channel_frontier_reaches_the_post_window():
    with db([treated()], daily(20, range(-14, 15)), ledger(13)) as sb:
        counts = tm.measure_channel(CH, today=TODAY)
    row = sb.rows("interventions")[0]
    assert counts["awaiting_window"] == 1
    assert (row["status"], row["measurement_status"]) == ("measuring", "awaiting_window")
    assert row["measurement_result"] is None


def test_the_log_ratio_of_browse_plus_suggested_views():
    rows = (daily(5, range(-14, 0)) + daily(5, range(-14, 0), source_type=7)    # pre 140
            + daily(10, range(1, 15)) + daily(10, range(1, 15), source_type=7)  # post 280
            + daily(1000, range(-14, 15), source_type=5)                          # search: not read
            + [traffic(0, 999), traffic(-15, 999), traffic(15, 999)])             # outside both
    reach_rows = [{"video_id": VID, "channel_id": CH, "date": day(n), "impressions": 100,
                   "ctr": 0.05 if n < 0 else 0.04} for n in range(-14, 15) if n]
    with db([treated()], rows, ledger(14), reach_rows) as sb:
        counts = tm.measure_channel(CH, today=TODAY)
    row = sb.rows("interventions")[0]
    assert counts["judged"] == 1 and row["status"] == "judged"
    assert row["measurement_status"] == "done"
    result = row["measurement_result"]
    assert (result["pre"], result["post"]) == (140, 280)
    assert result["delta"] == pytest.approx(math.log(281 / 141))
    assert result["impressions"] == {"pre": 1400, "post": 1400}
    assert result["ctr"]["pre"] == pytest.approx(0.05) and result["ctr"]["post"] == pytest.approx(0.04)
    assert result["window"] == {"d0": D0.isoformat(), "pre": [day(-14), day(-1)],
                                "post": [day(1), day(14)]}
    assert result["missing_days"] == [] and result["judged_at"] and result["computed_at"]


def test_a_pre_under_the_floor_is_insufficient_data_with_its_numbers():
    rows = daily(7, range(-14, 0)) + daily(50, range(1, 15))    # pre 98 < 100
    with db([treated()], rows, ledger(14)) as sb:
        counts = tm.measure_channel(CH, today=TODAY)
    row = sb.rows("interventions")[0]
    assert counts["insufficient_data"] == 1 and row["status"] == "insufficient_data"
    assert row["measurement_result"]["pre"] == 98


def test_the_floor_is_exactly_the_setting():
    rows = daily(10, range(-14, -4)) + daily(10, range(1, 15))    # pre 100
    with db([treated()], rows, ledger(14)) as sb:
        tm.measure_channel(CH, today=TODAY)
    assert sb.rows("interventions")[0]["status"] == "judged"


def test_missing_traffic_days_count_as_zero_and_are_listed():
    rows = daily(10, range(-14, 15))
    with db([treated()], rows, ledger(14, skip={-3, 5})) as sb:
        tm.measure_channel(CH, today=TODAY)
    result = sb.rows("interventions")[0]["measurement_result"]
    assert result["missing_days"] == [day(-3), day(5)]


def test_holdouts_and_agent_declines_are_measured_cancelled_rows_are_not():
    rows = daily(10, range(-14, 15))
    cancelled = treated(4, status="cancelled", payload={"path": "pipeline",
                                                        "error": {"reason": "checks_failed"}})
    planned = treated(5, status="planned", applied_at=None)
    backlinks = holdout(6, lever="backlinks")
    with db([treated(), holdout(), declined(), cancelled, planned, backlinks],
            rows, ledger(14)) as sb:
        counts = tm.measure_channel(CH, today=TODAY)
    status = {r["id"]: r["status"] for r in sb.rows("interventions")}
    assert counts["attempted"] == 3 and counts["judged"] == 3
    assert status == {1: "judged", 2: "judged", 3: "judged", 4: "cancelled", 5: "planned",
                      6: "holdout"}


def test_a_decided_row_is_recomputed_after_a_restatement_and_keeps_its_judged_at():
    rows = daily(10, range(-14, 15))
    with db([treated()], rows, ledger(14)) as sb:
        tm.measure_channel(CH, today=TODAY)
        first = dict(sb.rows("interventions")[0]["measurement_result"])
        assert tm.measure_channel(CH, today=TODAY)["changed"] == 0
        sb._tables["video_traffic_source_daily"].append(traffic(3, 500, source_type=7))
        tm.measure_channel(CH, today=TODAY)
    again = sb.rows("interventions")[0]["measurement_result"]
    assert again["post"] == first["post"] + 500
    assert again["judged_at"] == first["judged_at"]


def test_a_row_that_errors_is_counted_and_left_as_it_was():
    with db([holdout(created_at=None)], [], ledger(14)) as sb:
        counts = tm.measure_channel(CH, today=TODAY)
    assert (counts["attempted"], counts["errored"]) == (1, 1)
    assert sb.rows("interventions")[0]["status"] == "holdout"
