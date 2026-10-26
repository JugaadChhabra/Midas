"""Slice 2 · S2.3 — the playlist test's measurement and verdict (spec Part 5 S2.3,
Part 2 §1.2, §1.3, §1.5, P3, E8; #89).

The real playlist_test, reach, lever_verdicts and rows paging run against
FakeSupabase.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import eligibility, lever_measurement, main, playlist_test, reach
from app import lever_verdicts as lv
from app.config import settings
from app.job_status import JobRunFailed
from tests.fakes import FakeSupabase
from tests.test_backlink_candidates import postgrest_cap

CH, OTHER = "UCmarathi1", "UCgujarati"
#: The dose landed 11-02 … 11-04 (Pacific): pre = 10-05 … 11-01, post week k
#: = 11-05 + 7(k − 1) … 11-11 + 7(k − 1).
FIRST, LAST = "2026-11-02T18:00:00+00:00", "2026-11-04T18:00:00+00:00"
PRE = (date(2026, 10, 5), date(2026, 11, 1))
TEST_END = date(2026, 11, 4)


def week(k: int) -> tuple[date, date]:
    start = TEST_END + timedelta(days=1 + 7 * (k - 1))
    return start, start + timedelta(days=6)


def days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def treated(id_, pid, status="dosed", **kw):
    return {"id": id_, "channel_id": CH, "playlist_id": pid, "arm": "treated", "status": status,
            "proposal_ids": [], "first_applied_at": FIRST if status == "dosed" else None,
            "last_applied_at": LAST if status == "dosed" else None,
            "measurement_status": None, "measurement_result": None, **kw}


def holdout(id_, pid, **kw):
    return {"id": id_, "channel_id": CH, "playlist_id": pid, "arm": "holdout", "status": "holdout",
            "proposal_ids": [], "first_applied_at": None, "last_applied_at": None,
            "measurement_status": None, "measurement_result": None, **kw}


def starts(pid, per_day, start, end, *, video="v1", source_type=14, channel=CH):
    """`per_day` playlist starts a day for `pid`, one row per day."""
    return [{"playlist_id": pid, "video_id": video, "channel_id": channel, "date": d.isoformat(),
             "source_type": source_type, "source_detail": "", "views": 0,
             "playlist_starts": per_day, "watch_time_minutes": 0.0}
            for d in days(start, end)]


def ledger(through: date, *, skip=(), channel=CH):
    return [{"report_id": f"{channel}-{d}", "channel_id": channel, "data_date": d.isoformat(),
             "report_type": "playlist_traffic_source_a2"}
            for d in days(PRE[0] - timedelta(days=3), through) if d not in skip]


def by_week(pid, pre_daily: float, weekly: list[float]):
    """`pid`'s traffic: `pre_daily` starts a day over the pre window, then
    week k's total `weekly[k-1]` on its first day."""
    rows = starts(pid, pre_daily, *PRE)
    for k, n in enumerate(weekly, 1):
        rows += starts(pid, n, week(k)[0], week(k)[0])
    return rows


@contextmanager
def db(arms, traffic=(), *, through=None, playlists=None, proposals=(), video_traffic=(),
       verdicts=(), reports=None, channels=({"id": CH},)):
    playlists = ([{"id": a["playlist_id"], "channel_id": a["channel_id"]} for a in arms]
                 if playlists is None else playlists)
    sb = FakeSupabase({
        "playlist_arms": list(arms), "playlists": list(playlists),
        "playlist_proposals": list(proposals), "playlist_traffic_daily": list(traffic),
        "video_traffic_source_daily": list(video_traffic), "lever_verdicts": list(verdicts),
        "reporting_reports_ingested": (list(reports) if reports is not None
                                       else ledger(through) if through else []),
        "channels": list(channels), "interventions": [], "videos": [],
    })
    with patch.object(playlist_test, "supabase", return_value=sb), \
         patch.object(lv, "supabase", return_value=sb), \
         patch.object(reach, "supabase", return_value=sb), \
         patch.object(lever_measurement, "supabase", return_value=sb), \
         patch.object(eligibility, "supabase", return_value=sb), \
         patch.multiple(settings, PLAYLIST_MIN_LIFT=1.0, PLAYLIST_EXPERIMENT_WINDOWS=4):
        yield sb


def arm_rows(sb) -> dict[int, dict]:
    return {a["id"]: a for a in sb.rows("playlist_arms")}


def verdict_rows(sb) -> list[dict]:
    return sorted((r for r in sb.rows("lever_verdicts") if r["lever"] == "playlist"),
                  key=lambda r: r["week_start"])


# ── the indicator ────────────────────────────────────────────────────────

def test_the_indicator_sums_every_video_and_source_type_of_the_playlist_only():
    day = week(1)[0]
    traffic = (starts("PL1", 3, day, day, video="a", source_type=14)
               + starts("PL1", 4, day, day, video="b", source_type=18)
               + starts("PL1", 5, day, day, video="c", source_type=3)
               + starts("PL2", 100, day, day)                 # the holdout's own
               + starts("PL9", 1000, day, day))               # not in the test
    with db([treated(1, "PL1"), holdout(2, "PL2")], traffic, through=week(1)[1]) as sb:
        playlist_test.measure_channel(CH)
    arms = arm_rows(sb)
    assert arms[1]["measurement_result"]["weeks"][0]["starts"] == 12
    assert arms[2]["measurement_result"]["weeks"][0]["starts"] == 100


def test_the_indicator_reads_past_the_row_cap():
    traffic = [row for v in range(45) for row in starts("PL1", 1, *PRE, video=f"v{v}")]
    assert len(traffic) > 1000
    with db([treated(1, "PL1"), holdout(2, "PL2")], traffic, through=week(1)[1]) as sb, \
            postgrest_cap():
        playlist_test.measure_channel(CH)
    assert arm_rows(sb)[1]["measurement_result"]["pre_weekly"] == 45 * 28 * 7 / 28


# ── windows and completeness ─────────────────────────────────────────────

def test_pre_is_the_28_days_before_test_start_as_a_weekly_mean_and_weeks_follow_test_end():
    traffic = (starts("PL1", 1, *PRE)
               + starts("PL1", 1000, PRE[0] - timedelta(days=1), PRE[0] - timedelta(days=1))
               + starts("PL1", 500, date(2026, 11, 2), TEST_END)      # the dose's own days
               + starts("PL1", 2, *week(1)) + starts("PL1", 3, *week(2)))
    with db([treated(1, "PL1"), holdout(2, "PL2")], traffic, through=week(2)[1]) as sb:
        playlist_test.measure_channel(CH)
    result = arm_rows(sb)[1]["measurement_result"]
    assert result["pre_weekly"] == 7                           # 28 × 1 × 7 / 28
    assert result["weeks"] == [
        {"k": 1, "start": "2026-11-05", "end": "2026-11-11", "starts": 14, "delta": 7},
        {"k": 2, "start": "2026-11-12", "end": "2026-11-18", "starts": 21, "delta": 14},
    ]
    assert result["missing_days"] == [] and result["computed_at"]
    assert arm_rows(sb)[1]["measurement_status"] == "measuring"


def test_a_week_waits_for_the_frontier():
    arms = [treated(1, "PL1"), holdout(2, "PL2")]
    traffic = by_week("PL1", 1, [10]) + by_week("PL2", 1, [5])
    with db(arms, traffic, through=week(1)[1] - timedelta(days=1)) as sb:
        playlist_test.measure_channel(CH)
        assert arm_rows(sb)[1]["measurement_status"] == "awaiting_window"
        assert arm_rows(sb)[1]["measurement_result"]["weeks"] == []
        assert verdict_rows(sb) == []
    with db(arms, traffic, through=week(1)[1]) as sb:
        playlist_test.measure_channel(CH)
        assert [w["k"] for w in arm_rows(sb)[1]["measurement_result"]["weeks"]] == [1]
        assert len(verdict_rows(sb)) == 1


def test_missing_days_count_as_zero_and_are_listed():
    gap = date(2026, 10, 20)
    traffic = [r for r in starts("PL1", 1, *PRE) if r["date"] != gap.isoformat()]
    with db([treated(1, "PL1"), holdout(2, "PL2")], traffic,
            reports=ledger(week(1)[1], skip={gap})) as sb:
        playlist_test.measure_channel(CH)
    result = arm_rows(sb)[1]["measurement_result"]
    assert result["missing_days"] == ["2026-10-20"]
    assert result["pre_weekly"] == 27 * 7 / 28


def test_the_frontier_is_the_channels_playlist_report_only():
    reports = [dict(r, report_type="channel_traffic_source_a3") for r in ledger(week(1)[1])]
    reports += ledger(week(1)[1], channel=OTHER)
    with db([treated(1, "PL1"), holdout(2, "PL2")], reports=reports) as sb:
        playlist_test.measure_channel(CH)
    assert arm_rows(sb)[1]["measurement_status"] == "awaiting_window"


def test_nothing_is_measured_until_the_test_is_dosed():
    arms = [treated(1, "PL1"), treated(3, "PL3", status="applying"), holdout(2, "PL2")]
    with db(arms, through=week(4)[1]) as sb:
        counts = playlist_test.measure_channel(CH)
    assert counts["attempted"] == 0
    assert sb.writes == []


# ── per arm ──────────────────────────────────────────────────────────────

def test_added_video_views_are_the_added_videos_type_14_views_from_the_playlist():
    day = week(1)[0].isoformat()

    def views(video, n, *, source_type=14, detail="PL1", on=day):
        return {"video_id": video, "channel_id": CH, "date": on, "source_type": source_type,
                "source_detail": detail, "views": n, "engaged_views": 0,
                "watch_time_minutes": 0.0}

    proposals = [
        {"id": 10, "arm_id": 1, "playlist_id": "PL1", "video_id": "added",
         "applied_at": LAST, "status": "approved"},
        {"id": 11, "arm_id": 1, "playlist_id": "PL1", "video_id": "unsent",
         "applied_at": None, "status": "approved"},
    ]
    video_traffic = [views("added", 5), views("added", 2, on=week(2)[0].isoformat()),
                     views("added", 99, detail="PL9"),            # another playlist
                     views("added", 99, source_type=7),           # another source
                     views("unsent", 99)]                         # never added
    with db([treated(1, "PL1"), holdout(2, "PL2")], through=week(2)[1], proposals=proposals,
            video_traffic=video_traffic) as sb:
        playlist_test.measure_channel(CH)
    arms = arm_rows(sb)
    assert arms[1]["measurement_result"]["added_video_views"] == [
        {"k": 1, "views": 5}, {"k": 2, "views": 2}]
    assert arms[2]["measurement_result"]["added_video_views"] == []


def test_no_dose_arms_are_measured_but_never_enter_a_mean():
    arms = [treated(1, "PL1"), treated(3, "PL3", status="no_dose"), holdout(2, "PL2")]
    traffic = by_week("PL1", 0, [6]) + by_week("PL3", 0, [1000]) + by_week("PL2", 0, [2])
    with db(arms, traffic, through=week(1)[1]) as sb:
        playlist_test.measure_channel(CH)
    assert arm_rows(sb)[3]["measurement_result"]["weeks"][0]["starts"] == 1000
    [row] = verdict_rows(sb)
    assert (row["n_treated"], row["n_holdout"]) == (1, 1)
    assert (row["treated_mean_delta"], row["holdout_mean_delta"], row["lift"]) == (6, 2, 4)


# ── the verdict ──────────────────────────────────────────────────────────

def _two_by_two(weekly_treated, weekly_held):
    arms = [treated(1, "PL1"), treated(3, "PL3"), holdout(2, "PL2"), holdout(4, "PL4")]
    traffic = (by_week("PL1", 1, weekly_treated[0]) + by_week("PL3", 1, weekly_treated[1])
               + by_week("PL2", 1, weekly_held[0]) + by_week("PL4", 1, weekly_held[1]))
    return arms, traffic


def test_verdict_arithmetic_one_row_per_complete_week():
    # pre_weekly is 7 for every arm.
    arms, traffic = _two_by_two([[11, 7], [13, 9]], [[8, 7], [6, 3]])
    with db(arms, traffic, through=week(2)[1]) as sb:
        playlist_test.measure_channel(CH)
    one, two = verdict_rows(sb)
    assert (one["arm_scope"], one["week_start"], two["week_start"]) == (
        "treated_vs_holdout", "2026-11-05", "2026-11-12")
    # Week 1: treated deltas 4, 6; holdout 1, −1.
    assert (one["n_treated"], one["n_holdout"]) == (2, 2)
    assert (one["treated_mean_delta"], one["holdout_mean_delta"], one["lift"]) == (5, 0, 5)
    assert (one["cumulative_lift"], one["windows_judged"], one["verdict"]) == (5, 1, "helped")
    # Week 2: treated 0, 2; holdout 0, −4 → lift 1 − (−2) = 3.
    assert (two["lift"], two["windows_judged"], two["verdict"]) == (3, 2, "helped")
    # Pooled over weeks 1 … 2: mean(4, 6, 0, 2) − mean(1, −1, 0, −4).
    assert two["cumulative_lift"] == pytest.approx(3 - (-1))
    assert not one["stop_rule_triggered"] and not two["stop_rule_triggered"]
    assert {a["measurement_status"] for a in arm_rows(sb).values()} == {"measuring"}


@pytest.mark.parametrize("lift, verdict", [(1.0, "helped"), (0.5, "no_change"), (-1.0, "worse")])
def test_the_verdict_band_is_plus_or_minus_playlist_min_lift(lift, verdict):
    arms = [treated(1, "PL1"), holdout(2, "PL2")]
    traffic = by_week("PL1", 0, [10 + lift]) + by_week("PL2", 0, [10])
    with db(arms, traffic, through=week(1)[1]) as sb:
        playlist_test.measure_channel(CH)
    assert verdict_rows(sb)[0]["verdict"] == verdict


def test_a_week_with_no_dosed_treated_or_no_holdout_arm_writes_no_verdict():
    arms = [treated(1, "PL1", status="no_dose"), holdout(2, "PL2"), treated(3, "PL3")]
    with db(arms, through=week(1)[1], playlists=[{"id": "PL1", "channel_id": CH},
                                                  {"id": "PL2", "channel_id": CH}]) as sb:
        playlist_test.measure_channel(CH)    # PL3 vanished: no treated arm counts
    assert verdict_rows(sb) == []


@pytest.mark.parametrize("weekly, answer", [([8, 8, 8, 8], "yes"), ([7.5, 7.5, 7.5, 7.5], "no")])
def test_the_answer_at_window_4(weekly, answer):
    arms = [treated(1, "PL1"), holdout(2, "PL2"), treated(3, "PL3", status="no_dose")]
    traffic = by_week("PL1", 1, weekly + [500]) + by_week("PL2", 1, [7, 7, 7, 7])
    with db(arms, traffic, through=week(5)[1]) as sb:
        playlist_test.measure_channel(CH)
        rows = verdict_rows(sb)
        body = TestClient(main.app).get(f"/channels/{CH}/playlist-test").json()
    assert [r["windows_judged"] for r in rows] == [1, 2, 3, 4]       # no week 5
    assert [r["stop_rule_triggered"] for r in rows] == [False, False, False, answer == "no"]
    assert rows[-1]["cumulative_lift"] == pytest.approx(weekly[0] - 7)
    assert body["answer"] == answer
    arms_ = arm_rows(sb)
    assert (arms_[1]["status"], arms_[2]["status"], arms_[3]["status"]) == (
        "judged", "judged", "no_dose")
    assert {a["measurement_status"] for a in arms_.values()} == {"done"}
    assert len(arms_[1]["measurement_result"]["weeks"]) == 4


def test_the_stop_rule_waits_for_window_4_whatever_the_lift():
    arms = [treated(1, "PL1"), holdout(2, "PL2")]
    traffic = by_week("PL1", 1, [0, 0, 0]) + by_week("PL2", 1, [7, 7, 7])
    with db(arms, traffic, through=week(3)[1]) as sb:
        playlist_test.measure_channel(CH)
    assert [r["stop_rule_triggered"] for r in verdict_rows(sb)] == [False] * 3
    assert {a["status"] for a in arm_rows(sb).values()} == {"dosed", "holdout"}


def test_an_arm_whose_playlist_vanished_is_insufficient_data_and_out_of_the_means():
    arms = [treated(1, "PL1"), treated(3, "PL3"), holdout(2, "PL2")]
    traffic = by_week("PL1", 1, [9] * 4) + by_week("PL3", 1, [0] * 4) + by_week("PL2", 1, [7] * 4)
    present = [{"id": "PL1", "channel_id": CH}, {"id": "PL2", "channel_id": CH}]
    with db(arms, traffic, through=week(4)[1], playlists=present) as sb:
        playlist_test.measure_channel(CH)
    arms_ = arm_rows(sb)
    assert (arms_[1]["status"], arms_[3]["status"]) == ("judged", "insufficient_data")
    assert verdict_rows(sb)[-1]["n_treated"] == 1 and verdict_rows(sb)[-1]["lift"] == 2


def test_a_decided_test_is_not_measured_again():
    arms = [treated(1, "PL1"), holdout(2, "PL2")]
    traffic = by_week("PL1", 1, [9] * 4) + by_week("PL2", 1, [7] * 4)
    with db(arms, traffic, through=week(4)[1]) as sb:
        playlist_test.measure_channel(CH)
        writes = len(sb.writes)
        assert playlist_test.measure_channel(CH)["attempted"] == 0
        assert len(sb.writes) == writes


def test_a_rerun_rewrites_the_weeks_in_place_and_leaves_backlinks_rows_alone():
    arms = [treated(1, "PL1"), holdout(2, "PL2")]
    traffic = by_week("PL1", 1, [9, 9]) + by_week("PL2", 1, [7, 7])
    backlinks = {"id": 77, "channel_id": CH, "lever": "backlinks", "arm_scope": "treated_vs_holdout",
                 "week_start": "2026-11-09", "stop_rule_triggered": True}
    with db(arms, traffic, through=week(2)[1], verdicts=[backlinks]) as sb:
        playlist_test.measure_channel(CH)
        playlist_test.measure_channel(CH)
        assert len(verdict_rows(sb)) == 2
        assert backlinks in sb.rows("lever_verdicts")
        assert lv.stopped(CH, "playlist") is False and lv.stopped(CH) is True


# ── the job ──────────────────────────────────────────────────────────────

def _job_world(**kw):
    arms = [treated(1, "PL1"), holdout(2, "PL2")]
    return db(arms, channels=({"id": CH}, {"id": OTHER}), **kw)


def test_the_job_measures_the_playlist_test_of_channels_with_arms_only():
    calls = []
    with _job_world(), \
         patch.object(lever_measurement, "measure_channel",
                      return_value={"attempted": 0, "errored": 0}), \
         patch.object(lv, "write_verdicts"), \
         patch.object(playlist_test, "measure_channel",
                      side_effect=lambda cid: calls.append(cid)
                      or {"attempted": 2, "errored": 0}):
        assert lv.run_weekly() is None
    assert calls == [CH]


@pytest.mark.parametrize("errored, outcome", [(2, "failed"), (1, "degraded"), (0, "success")])
def test_playlist_arm_errors_are_their_own_category(errored, outcome):
    with _job_world(), \
         patch.object(lever_measurement, "measure_channel",
                      return_value={"attempted": 0, "errored": 0}), \
         patch.object(lv, "write_verdicts") as write, \
         patch.object(playlist_test, "measure_channel",
                      return_value={"attempted": 2, "errored": errored}):
        if outcome == "failed":
            with pytest.raises(JobRunFailed) as exc:
                lv.run_weekly()
            assert exc.value.failed_channels == {CH: "ItemsFailed: playlist arms: all 2 failed"}
        elif outcome == "degraded":
            assert lv.run_weekly() == {"partial_errors": {CH: "playlist arms: 1/2 failed"}}
        else:
            assert lv.run_weekly() is None
    # Backlinks' verdicts were written whatever the playlist test did.
    assert sorted(c.args[0] for c in write.call_args_list) == sorted([CH, OTHER])


def test_a_playlist_crash_does_not_stop_backlinks_on_the_same_channel():
    with _job_world(), \
         patch.object(lever_measurement, "measure_channel",
                      return_value={"attempted": 3, "errored": 1}), \
         patch.object(lv, "write_verdicts") as write, \
         patch.object(playlist_test, "measure_channel", side_effect=RuntimeError("boom")):
        with pytest.raises(JobRunFailed) as exc:
            lv.run_weekly()
    assert exc.value.failed_channels == {CH: "RuntimeError: boom"}
    assert sorted(c.args[0] for c in write.call_args_list) == sorted([CH, OTHER])


def test_a_backlinks_failure_does_not_stop_the_playlist_test_on_the_same_channel():
    calls = []
    with _job_world(), \
         patch.object(lever_measurement, "measure_channel", side_effect=RuntimeError("boom")), \
         patch.object(lv, "write_verdicts"), \
         patch.object(playlist_test, "measure_channel",
                      side_effect=lambda cid: calls.append(cid)
                      or {"attempted": 2, "errored": 0}):
        with pytest.raises(JobRunFailed) as exc:
            lv.run_weekly()
    assert calls == [CH]
    assert exc.value.failed_channels == {CH: "RuntimeError: boom", OTHER: "RuntimeError: boom"}


def test_the_real_job_end_to_end_writes_the_playlist_verdict():
    traffic = by_week("PL1", 1, [9]) + by_week("PL2", 1, [7])
    with _job_world(traffic=traffic, through=week(1)[1]) as sb:
        assert lv.run_weekly(today=week(1)[1] + timedelta(days=3)) is None
    [row] = verdict_rows(sb)
    assert row["lift"] == 2


# ── the endpoint ─────────────────────────────────────────────────────────

def test_the_endpoint_before_the_test_is_dosed_and_while_it_runs():
    with db([treated(1, "PL1", status="applying", first_applied_at=FIRST),
             holdout(2, "PL2")]):
        body = TestClient(main.app).get(f"/channels/{CH}/playlist-test").json()
    assert (body["test_start"], body["test_end"], body["answer"]) == (None, None, "pending")
    assert [a["id"] for a in body["arms"]] == [1, 2] and body["verdicts"] == []

    traffic = by_week("PL1", 1, [9]) + by_week("PL2", 1, [7])
    with db([treated(1, "PL1"), holdout(2, "PL2")], traffic, through=week(1)[1]):
        playlist_test.measure_channel(CH)
        body = TestClient(main.app).get(f"/channels/{CH}/playlist-test").json()
        other = TestClient(main.app).get(f"/channels/{OTHER}/playlist-test").json()
    assert (body["test_start"], body["test_end"]) == ("2026-11-02", "2026-11-04")
    assert [v["week_start"] for v in body["verdicts"]] == ["2026-11-05"]
    assert body["answer"] == "pending"
    assert other == {"test_start": None, "test_end": None, "arms": [], "verdicts": [],
                     "answer": "pending"}


def test_the_settings_start_values():
    from app.config import Settings
    s = Settings()
    assert (s.PLAYLIST_EXPERIMENT_WINDOWS, s.PLAYLIST_MIN_LIFT) == (4, 1.0)
