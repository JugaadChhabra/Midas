"""Slice 1 · S1.6b (#68): the weekly lever verdict, the stop rule, the human
benchmark, the `lever_measurement` job and the two read endpoints.

The real write_verdicts, run_weekly, measure_channel and rows paging run
against FakeSupabase.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient

from app import agent_tick, eligibility, interventions, job_status, lever_measurement, main, reach, short_links
from app import lever_verdicts as lv
from app.config import settings
from app.job_status import JobRunFailed, JobStatusRegistry
from tests.fakes import FakeSupabase
from tests.test_backlink_candidates import postgrest_cap

CH, OTHER = "UCmarathi1", "UCgujarati"
#: Three consecutive Mondays.
W1, W2, W3 = date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)


def judged(id_, arm, delta, week, origin="midas", status="judged", channel=CH) -> dict:
    """A backlinks row S1.6a judged on the Tuesday of `week`."""
    return {"id": id_, "video_id": f"video{id_:05d}", "channel_id": channel,
            "lever": "backlinks", "origin": origin, "arm": arm, "status": status,
            "created_at": f"{week.isoformat()}T08:00:00+00:00",
            "measurement_result": {"delta": delta,
                                   "judged_at": f"{week.replace(day=week.day + 1)}T09:00:00+00:00"}}


def human(id_, delta, week, **kw) -> dict:
    return judged(id_, "n/a", delta, week, origin="human", **kw)


@contextmanager
def db(interventions=(), verdicts=(), channels=({"id": CH},), videos=()):
    sb = FakeSupabase({"interventions": list(interventions), "lever_verdicts": list(verdicts),
                       "channels": list(channels), "video_traffic_source_daily": [],
                       "reporting_reports_ingested": [], "videos": list(videos), "playlist_arms": []})
    with patch.object(lv, "supabase", return_value=sb), \
         patch.object(agent_tick, "supabase", return_value=sb), \
         patch.object(lever_measurement, "supabase", return_value=sb), \
         patch.object(reach, "supabase", return_value=sb), \
         patch.object(eligibility, "supabase", return_value=sb), \
         patch.multiple(settings, BACKLINK_MIN_LIFT=1.0, BACKLINK_EXPERIMENT_WINDOWS=3):
        yield sb


def verdict_rows(sb, scope="treated_vs_holdout") -> list[dict]:
    return sorted((r for r in sb.rows("lever_verdicts") if r["arm_scope"] == scope),
                  key=lambda r: r["week_start"])


# ── the arithmetic ───────────────────────────────────────────────────────

def test_lift_cumulative_lift_and_the_directional_verdict():
    rows = [judged(1, "treated", 3, W1), judged(2, "treated", 5, W1), judged(3, "holdout", 1, W1),
            judged(4, "treated", 0, W2), judged(5, "holdout", 2, W2), judged(6, "holdout", 0, W2),
            judged(7, "treated", 1.5, W3), judged(8, "holdout", 1, W3)]
    with db(rows) as sb:
        for week in (W1, W2, W3):
            lv.write_verdicts(CH, today=week.replace(day=week.day + 2))
    one, two, three = verdict_rows(sb)

    assert one["week_start"] == "2026-10-05"
    assert (one["n_treated"], one["n_holdout"]) == (2, 1)
    assert (one["treated_mean_delta"], one["holdout_mean_delta"], one["lift"]) == (4, 1, 3)
    assert one["cumulative_lift"] == 3 and one["windows_judged"] == 1
    assert one["verdict"] == "helped"

    # Week 2: treated 0, holdout mean 1 → lift −1, exactly −BACKLINK_MIN_LIFT.
    assert (two["lift"], two["verdict"], two["windows_judged"]) == (-1, "worse", 2)
    # Cumulative over every row judged so far: mean(3, 5, 0) − mean(1, 2, 0).
    assert two["cumulative_lift"] == pytest.approx(8 / 3 - 1)

    # Week 3: lift 0.5, inside the band.
    assert (three["lift"], three["verdict"]) == (0.5, "no_change")
    assert three["cumulative_lift"] == pytest.approx(9.5 / 4 - 1)
    assert {r["lever"] for r in (one, two, three)} == {"backlinks"}


@pytest.mark.parametrize("lift, verdict", [(1.0, "helped"), (0.99, "no_change"),
                                           (-0.99, "no_change"), (-1.0, "worse")])
def test_the_verdict_band_is_plus_or_minus_backlink_min_lift(lift, verdict):
    assert lv.directional(lift, 1.0) == verdict


def test_insufficient_data_and_unjudged_rows_stay_out_of_the_means():
    rows = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1),
            judged(3, "treated", 900, W1, status="insufficient_data"),
            judged(4, "holdout", -900, W1, status="measuring")]
    with db(rows) as sb:
        lv.write_verdicts(CH, today=W1)
    [row] = verdict_rows(sb)
    assert (row["n_treated"], row["n_holdout"], row["lift"]) == (1, 1, 3)


def test_rows_judged_after_the_week_are_not_counted_yet():
    rows = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1),
            judged(3, "treated", 100, W2), judged(4, "holdout", 0, W2)]
    with db(rows) as sb:
        lv.write_verdicts(CH, today=W1)
    [row] = verdict_rows(sb)
    assert row["cumulative_lift"] == 3


# ── no judged holdout → no verdict ───────────────────────────────────────

def test_a_week_with_no_judged_holdout_writes_no_verdict():
    rows = [judged(1, "treated", 4, W1),
            judged(2, "holdout", 1, W1, status="insufficient_data"),
            judged(3, "holdout", 1, W2)]                   # judged next week
    with db(rows) as sb:
        assert lv.write_verdicts(CH, today=W1) == {}
    assert sb.rows("lever_verdicts") == []


def test_a_week_with_no_judged_treated_row_writes_no_verdict_either():
    with db([judged(1, "holdout", 1, W1)]) as sb:
        lv.write_verdicts(CH, today=W1)
    assert sb.rows("lever_verdicts") == []


def test_a_week_without_a_verdict_doesnt_count_as_a_window():
    rows = [judged(1, "treated", 0, W1), judged(2, "holdout", 0, W1),
            judged(3, "treated", 0, W3), judged(4, "holdout", 0, W3)]
    with db(rows) as sb:
        for week in (W1, W2, W3):
            lv.write_verdicts(CH, today=week)
    assert [r["windows_judged"] for r in verdict_rows(sb)] == [1, 2]


# ── the stop rule ────────────────────────────────────────────────────────

def test_the_stop_rule_triggers_exactly_at_the_window_count_and_triage_then_says_no_change():
    # Lift 0.5 every week: under BACKLINK_MIN_LIFT, so a stop at window 3.
    rows = [r for i, week in enumerate((W1, W2, W3))
            for r in (judged(2 * i + 1, "treated", 1.5, week), judged(2 * i + 2, "holdout", 1, week))]
    with db(rows) as sb:
        lv.write_verdicts(CH, today=W1)
        lv.write_verdicts(CH, today=W2)
        assert [r["stop_rule_triggered"] for r in verdict_rows(sb)] == [False, False]
        assert agent_tick.backlinks_stopped(CH) is False

        lv.write_verdicts(CH, today=W3)
        assert [r["stop_rule_triggered"] for r in verdict_rows(sb)] == [False, False, True]
        assert verdict_rows(sb)[-1]["windows_judged"] == 3
        assert agent_tick.backlinks_stopped(CH) is True
        assert agent_tick.backlinks_stopped(OTHER) is False

    # What triage does with it (the real rules; the tick itself is in test_agent_tick).
    from app.decide import TRIAGE
    assert TRIAGE.rules({"has_related_block": False, "backlink_candidates": 6,
                         "backlinks_stopped": True}) == "no_change"


def test_a_cumulative_lift_at_the_bar_doesnt_stop_the_lever():
    rows = [r for i, week in enumerate((W1, W2, W3))
            for r in (judged(2 * i + 1, "treated", 2, week), judged(2 * i + 2, "holdout", 1, week))]
    with db(rows) as sb:
        for week in (W1, W2, W3):
            lv.write_verdicts(CH, today=week)
    assert verdict_rows(sb)[-1]["cumulative_lift"] == 1.0
    assert not any(r["stop_rule_triggered"] for r in verdict_rows(sb))


def test_the_window_count_follows_the_setting():
    rows = [judged(1, "treated", 0, W1), judged(2, "holdout", 0, W1)]
    with db(rows) as sb, patch.object(settings, "BACKLINK_EXPERIMENT_WINDOWS", 1):
        lv.write_verdicts(CH, today=W1)
    assert verdict_rows(sb)[0]["stop_rule_triggered"] is True


# ── the human benchmark ──────────────────────────────────────────────────

def test_human_rows_never_enter_the_lift_and_get_their_own_row():
    midas = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1)]
    team = [human(3, 50, W1), human(4, 70, W1)]
    with db(midas) as alone:
        lv.write_verdicts(CH, today=W1)
    with db(midas + team) as sb:
        lv.write_verdicts(CH, today=W1)

    keep = ("n_treated", "n_holdout", "treated_mean_delta", "holdout_mean_delta", "lift",
            "cumulative_lift", "windows_judged", "verdict", "stop_rule_triggered")
    [with_team], [without] = verdict_rows(sb), verdict_rows(alone)
    assert {k: with_team[k] for k in keep} == {k: without[k] for k in keep}

    [bench] = verdict_rows(sb, "human")
    assert bench["lever"] == "backlinks" and bench["week_start"] == "2026-10-05"
    assert (bench["n_treated"], bench["n_holdout"], bench["treated_mean_delta"]) == (2, 0, 60)
    assert bench["holdout_mean_delta"] is None and bench["lift"] is None
    assert bench["cumulative_lift"] is None and bench["verdict"] is None
    assert bench["stop_rule_triggered"] is False and bench["windows_judged"] == 1


def test_backlinks_rows_on_shorts_stay_out_of_every_verdict():
    """The pick took Shorts before 2026-10-26 (#103); a Short's description links
    aren't clickable, so its rows, either arm or human, would only pull the means
    toward zero. A NULL is_short (not yet probed) still counts."""
    long_ = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1), human(3, 50, W1)]
    on_shorts = [judged(4, "treated", 0, W1), judged(5, "holdout", 30, W1), human(6, -90, W1)]
    unprobed = judged(7, "treated", 10, W1)
    videos = ([{"id": r["video_id"], "is_short": False} for r in long_]
              + [{"id": r["video_id"], "is_short": True} for r in on_shorts]
              + [{"id": unprobed["video_id"], "is_short": None}])
    with db(long_ + on_shorts + [unprobed], videos=videos) as sb:
        lv.write_verdicts(CH, today=W1)
    [row], [bench] = verdict_rows(sb), verdict_rows(sb, "human")
    assert (row["n_treated"], row["n_holdout"]) == (2, 1)
    assert (row["treated_mean_delta"], row["holdout_mean_delta"]) == (7, 1)
    assert (bench["n_treated"], bench["treated_mean_delta"]) == (1, 50)


def test_short_link_rows_are_not_dropped_as_shorts():
    """A short_link row's video is the long target; nothing to drop, but the
    Short filter is backlinks-only all the same."""
    row = short_link(1, 5, W1)
    with db([row], videos=[{"id": row["video_id"], "is_short": True}]) as sb:
        lv.write_verdicts(CH, today=W1, lever="short_link")
    assert len([r for r in sb.rows("lever_verdicts") if r["lever"] == "short_link"]) == 1


def test_a_human_only_week_writes_only_the_human_row_and_never_stops_the_lever():
    with db([human(1, -40, W1)]) as sb, patch.object(settings, "BACKLINK_EXPERIMENT_WINDOWS", 1):
        lv.write_verdicts(CH, today=W1)
        assert verdict_rows(sb) == []
        assert len(verdict_rows(sb, "human")) == 1
        assert agent_tick.backlinks_stopped(CH) is False


# ── reruns ───────────────────────────────────────────────────────────────

def test_a_rerun_replaces_this_weeks_row_and_leaves_past_weeks_alone():
    past = {"id": 1, "channel_id": CH, "lever": "backlinks", "arm_scope": "treated_vs_holdout",
            "week_start": "2026-09-28", "lift": 9, "stop_rule_triggered": False}
    rows = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1)]
    with db(rows, [past]) as sb:
        lv.write_verdicts(CH, today=W1)
        # A restated day, recomputed by S1.6a.
        sb.table("interventions").update(
            {"measurement_result": {**rows[0]["measurement_result"], "delta": 6}}
        ).eq("id", 1).execute()
        lv.write_verdicts(CH, today=W1)
    old, now = verdict_rows(sb)
    assert old == past
    assert now["lift"] == 5 and now["windows_judged"] == 2


def test_a_rerun_after_the_weeks_holdout_was_undecided_deletes_the_stale_row():
    rows = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1)]
    with db(rows) as sb:
        lv.write_verdicts(CH, today=W1)
        sb.table("interventions").update({"status": "insufficient_data"}).eq("id", 2).execute()
        lv.write_verdicts(CH, today=W1)
    assert sb.rows("lever_verdicts") == []


def test_a_week_judged_but_never_written_is_written_by_the_next_run():
    """A run that measured on W1, then died before its verdicts: W2's run writes W1 first."""
    rows = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1),
            judged(3, "treated", 2, W2), judged(4, "holdout", 1, W2), human(5, 7, W1)]
    with db(rows) as sb:
        current = lv.write_verdicts(CH, today=W2)
        lv.write_verdicts(CH, today=W2)                # a rerun doesn't duplicate it
    one, two = verdict_rows(sb)
    assert (one["week_start"], one["lift"], one["windows_judged"]) == ("2026-10-05", 3, 1)
    assert (two["week_start"], two["lift"], two["windows_judged"]) == ("2026-10-12", 1, 2)
    assert current["treated_vs_holdout"]["lift"] == 1
    assert [r["week_start"] for r in verdict_rows(sb, "human")] == ["2026-10-05"]


def test_a_same_week_rerun_keeps_a_triggered_stop():
    rows = [judged(1, "treated", 0, W1), judged(2, "holdout", 0, W1)]
    with db(rows) as sb, patch.object(settings, "BACKLINK_EXPERIMENT_WINDOWS", 1):
        lv.write_verdicts(CH, today=W1)
        assert agent_tick.backlinks_stopped(CH) is True
        # A restatement lifts the cumulative lift over the bar...
        sb.table("interventions").update(
            {"measurement_result": {**rows[0]["measurement_result"], "delta": 5}}
        ).eq("id", 1).execute()
        lv.write_verdicts(CH, today=W1)
        assert verdict_rows(sb)[0]["lift"] == 5
        assert agent_tick.backlinks_stopped(CH) is True
        # ...or takes the week's holdout away: the triggered row isn't deleted.
        sb.table("interventions").update({"status": "insufficient_data"}).eq("id", 2).execute()
        lv.write_verdicts(CH, today=W1)
        assert agent_tick.backlinks_stopped(CH) is True


def test_the_week_is_the_monday_of_the_utc_judged_date():
    assert lv.week_start(date(2026, 10, 11)) == date(2026, 10, 5)     # a Sunday
    assert lv.week_start(date(2026, 10, 12)) == date(2026, 10, 12)    # a Monday
    row = judged(1, "treated", 0, W1)
    row["measurement_result"]["judged_at"] = "2026-10-12T01:00:00+05:30"   # Sunday in UTC
    assert lv._judged_week(row) == date(2026, 10, 5)


# ── the job ──────────────────────────────────────────────────────────────

def test_lever_measurement_is_registered_monday_0900_utc_and_shows_in_health_jobs():
    sched = BackgroundScheduler(daemon=True)
    main._register_jobs(sched)
    job = sched.get_job("lever_measurement")
    assert job is not None and job.func is lv.run_weekly
    assert job.max_instances == 1 and job.coalesce is True
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["day_of_week"], fields["hour"], fields["minute"]) == ("mon", "9", "0")
    assert str(job.trigger.timezone) == "UTC"

    reg = JobStatusRegistry()
    reg.watch(sched)
    with patch.object(job_status, "registry", reg):
        body = TestClient(main.app).get("/health/jobs").json()
    assert body["jobs"]["lever_measurement"]["status"] == "never_run"


def test_the_job_measures_then_writes_verdicts_for_every_channel():
    calls = []
    with db(channels=({"id": CH}, {"id": OTHER})), \
         patch.object(lever_measurement, "measure_channel",
                      side_effect=lambda cid, **_: calls.append(("measure", cid))
                      or {"attempted": 0, "errored": 0}), \
         patch.object(lv, "write_verdicts",
                      side_effect=lambda cid, **_: calls.append(("verdicts", cid))):
        assert lv.run_weekly() is None
    assert sorted(calls) == sorted([("measure", CH), ("verdicts", CH),
                                   ("measure", OTHER), ("verdicts", OTHER)])
    # Each channel is measured before its verdicts are written.
    for cid in (CH, OTHER):
        assert calls.index(("measure", cid)) + 1 == calls.index(("verdicts", cid))


def test_a_channel_crash_fails_the_run_after_every_channel_ran():
    seen = []

    def measure(cid, **_):
        seen.append(cid)
        if cid == CH:
            raise RuntimeError("boom")
        return {"attempted": 0, "errored": 0}

    with db(channels=({"id": CH}, {"id": OTHER})), \
         patch.object(lever_measurement, "measure_channel", side_effect=measure), \
         patch.object(lv, "write_verdicts"):
        with pytest.raises(JobRunFailed) as exc:
            lv.run_weekly()
    assert sorted(seen) == sorted([CH, OTHER])
    assert exc.value.failed_channels == {CH: "RuntimeError: boom"}


@pytest.mark.parametrize("errored, attempted, outcome", [
    (3, 3, "failed"), (1, 3, "degraded"), (0, 3, "success"), (0, 0, "success"),
])
def test_per_intervention_errors_are_judged_by_item_error_verdict(errored, attempted, outcome):
    with db(), patch.object(lever_measurement, "measure_channel",
                            return_value={"attempted": attempted, "errored": errored}), \
         patch.object(lv, "write_verdicts") as write:
        if outcome == "failed":
            with pytest.raises(JobRunFailed) as exc:
                lv.run_weekly()
            assert exc.value.failed_channels == {CH: "ItemsFailed: interventions: all 3 failed"}
            write.assert_not_called()      # no verdicts from a channel whose every row errored
        elif outcome == "degraded":
            assert lv.run_weekly() == {"partial_errors": {CH: "interventions: 1/3 failed"}}
        else:
            assert lv.run_weekly() is None


def test_the_real_job_end_to_end_writes_the_weeks_verdict():
    rows = [judged(1, "treated", 4, W1), judged(2, "holdout", 1, W1)]
    with db(rows) as sb:
        assert lv.run_weekly(today=date(2026, 10, 6)) is None
    [row] = verdict_rows(sb)
    assert row["week_start"] == "2026-10-05" and row["lift"] == 3


# ── the endpoints ────────────────────────────────────────────────────────

def _intervention(id_, created, lever="backlinks", status="measuring", channel=CH):
    return {"id": id_, "channel_id": channel, "video_id": f"v{id_}", "lever": lever,
            "origin": "midas", "arm": "treated", "status": status,
            "created_at": f"2026-10-{created:02d}T08:00:00+00:00"}


def test_interventions_endpoint_pages_newest_first():
    rows = [_intervention(i, 1 + i // 2) for i in range(1, 8)]     # pairs share created_at
    rows.append(_intervention(99, 28, channel=OTHER))
    with db(rows):
        client = TestClient(main.app)
        first = client.get(f"/channels/{CH}/interventions", params={"limit": 3}).json()
        second = client.get(f"/channels/{CH}/interventions",
                            params={"limit": 3, "offset": first["next_offset"]}).json()
        last = client.get(f"/channels/{CH}/interventions",
                          params={"limit": 3, "offset": second["next_offset"]}).json()
    ids = [r["id"] for page in (first, second, last) for r in page["interventions"]]
    assert ids == [7, 6, 5, 4, 3, 2, 1]                   # created_at desc, then id desc
    assert (first["limit"], first["offset"], first["next_offset"]) == (3, 0, 3)
    assert second["next_offset"] == 6
    assert last["next_offset"] is None and len(last["interventions"]) == 1


def test_interventions_endpoint_filters_by_lever_and_status():
    rows = [_intervention(1, 1), _intervention(2, 2, status="judged"),
            _intervention(3, 3, lever="playlist", status="applied")]
    with db(rows):
        client = TestClient(main.app)
        judged_ = client.get(f"/channels/{CH}/interventions",
                             params={"lever": "backlinks", "status": "judged"}).json()
        playlist = client.get(f"/channels/{CH}/interventions", params={"lever": "playlist"}).json()
        bad_lever = client.get(f"/channels/{CH}/interventions", params={"lever": "nope"})
        bad_status = client.get(f"/channels/{CH}/interventions", params={"status": "nope"})
        too_big = client.get(f"/channels/{CH}/interventions", params={"limit": 1001})
    assert [r["id"] for r in judged_["interventions"]] == [2]
    assert [r["id"] for r in playlist["interventions"]] == [3]
    assert (bad_lever.status_code, bad_status.status_code, too_big.status_code) == (400, 400, 422)


def test_lever_verdicts_endpoint_lists_every_week_newest_first_with_the_stop_state():
    verdicts = [{"id": i, "channel_id": CH, "lever": "backlinks", "arm_scope": scope,
                 "week_start": week, "stop_rule_triggered": stop}
                for i, (scope, week, stop) in enumerate([
                    ("treated_vs_holdout", "2026-10-05", False),
                    ("human", "2026-10-05", False),
                    ("treated_vs_holdout", "2026-10-19", True),
                ], 1)]
    verdicts.append({"id": 9, "channel_id": OTHER, "lever": "backlinks",
                     "arm_scope": "treated_vs_holdout", "week_start": "2026-10-19",
                     "stop_rule_triggered": False})
    with db(verdicts=verdicts):
        body = TestClient(main.app).get(f"/channels/{CH}/lever-verdicts").json()
        other = TestClient(main.app).get(f"/channels/{OTHER}/lever-verdicts").json()
    assert [r["id"] for r in body["verdicts"]] == [3, 1, 2]
    assert body["backlinks_stopped"] is True
    assert [r["id"] for r in other["verdicts"]] == [9] and other["backlinks_stopped"] is False


def test_lever_verdicts_endpoint_reads_past_the_row_cap():
    verdicts = [{"id": i, "channel_id": CH, "lever": "backlinks", "arm_scope": "human",
                 "week_start": "2026-10-05", "stop_rule_triggered": False}
                for i in range(1, 1206)]
    with db(verdicts=verdicts), postgrest_cap():
        body = TestClient(main.app).get(f"/channels/{CH}/lever-verdicts").json()
    assert len(body["verdicts"]) == 1205


# ── Short links (Slice 2 S2.6, #92) ──────────────────────────────────────

def short_link(id_, delta, week, **kw) -> dict:
    return {**human(id_, delta, week, **kw), "lever": "short_link"}


def test_short_link_rows_get_human_verdict_rows_and_never_a_lift_or_a_stop():
    rows = [short_link(1, 6, W1), short_link(2, 2, W1), short_link(3, 9, W2),
            human(4, 50, W1), judged(5, "treated", 4, W1), judged(6, "holdout", 1, W1)]
    with db(rows) as sb, patch.object(settings, "BACKLINK_EXPERIMENT_WINDOWS", 1):
        lv.write_verdicts(CH, today=W1, lever="short_link")
        lv.write_verdicts(CH, today=W2, lever="short_link")
        stopped = lv.stopped(CH, "short_link")
    mine = sorted((r for r in sb.rows("lever_verdicts") if r["lever"] == "short_link"),
                  key=lambda r: r["week_start"])
    assert [(r["arm_scope"], r["week_start"], r["n_treated"], r["treated_mean_delta"],
             r["windows_judged"]) for r in mine] == [
        ("human", "2026-10-05", 2, 4, 1), ("human", "2026-10-12", 1, 9, 2)]
    for r in mine:
        assert r["n_holdout"] == 0 and r["holdout_mean_delta"] is None
        assert r["lift"] is None and r["cumulative_lift"] is None and r["verdict"] is None
        assert r["stop_rule_triggered"] is False
    assert stopped is False
    # Backlinks' rows are written by their own call, untouched by this one.
    assert [r for r in sb.rows("lever_verdicts") if r["lever"] == "backlinks"] == []


def test_the_job_detects_short_links_before_measuring_on_traffic_ingest_channels():
    calls = []
    with db(channels=({"id": CH}, {"id": OTHER})), \
         patch.object(settings, "TRAFFIC_INGEST_CHANNELS", {CH}), \
         patch.object(short_links, "detect",
                      side_effect=lambda cid: calls.append(("detect", cid))
                      or {"attempted": 0, "errored": 0}), \
         patch.object(lever_measurement, "measure_channel",
                      side_effect=lambda cid, **_: calls.append(("measure", cid))
                      or {"attempted": 0, "errored": 0}), \
         patch.object(lv, "write_verdicts",
                      side_effect=lambda cid, lever="backlinks", **_:
                      calls.append(("verdicts", cid, lever))):
        assert lv.run_weekly() is None
    mine = [c for c in calls if c[1] == CH]
    assert mine == [("detect", CH), ("measure", CH), ("verdicts", CH, "backlinks"),
                    ("verdicts", CH, "short_link")]
    assert [c for c in calls if c[1] == OTHER] == [("measure", OTHER),
                                                   ("verdicts", OTHER, "backlinks")]


@pytest.mark.parametrize("detected, outcome", [
    ({"attempted": 2, "errored": 2}, {CH: "ItemsFailed: short-link pairs: all 2 failed"}),
    ({"attempted": 2, "errored": 1}, {"partial_errors": {CH: "short-link pairs: 1/2 failed"}}),
    (RuntimeError("boom"), {CH: "RuntimeError: boom"}),
])
def test_detection_errors_are_their_own_category_and_measurement_still_runs(detected, outcome):
    with db(), patch.object(settings, "TRAFFIC_INGEST_CHANNELS", {CH}), \
         patch.object(short_links, "detect", side_effect=[detected]
                      if isinstance(detected, Exception) else None,
                      return_value=detected), \
         patch.object(lever_measurement, "measure_channel",
                      return_value={"attempted": 0, "errored": 0}) as measure, \
         patch.object(lv, "write_verdicts") as write:
        if "partial_errors" in outcome:
            assert lv.run_weekly() == outcome
        else:
            with pytest.raises(JobRunFailed) as exc:
                lv.run_weekly()
            assert exc.value.failed_channels == outcome
    measure.assert_called_once()
    assert write.call_count == 2


def test_the_real_job_end_to_end_detects_measures_and_writes_the_short_link_week():
    """A Short link seen in the traffic is recorded, judged on type 32 and
    lands in a `short_link` human verdict row, in one run."""
    short, target = "short000001", "tgtVideo001"
    # judged_at is the wall clock, which picks the verdict week: dates are relative to it.
    today = datetime.now(timezone.utc).date()
    d0 = today - timedelta(days=20)
    days = [date.fromordinal(d0.toordinal() + n).isoformat() for n in range(-10, 11)]
    traffic = ([{"video_id": target, "channel_id": CH, "date": d, "source_type": 32,
                 "source_detail": short, "views": 3} for d in days if d >= d0.isoformat()]
               + [{"video_id": short, "channel_id": CH, "date": d, "source_type": 24,
                   "source_detail": "", "views": 50} for d in days])
    ingested = [{"report_id": d, "channel_id": CH, "report_type": "channel_traffic_source_a3",
                 "data_date": d} for d in days]
    with db() as sb, patch.object(settings, "TRAFFIC_INGEST_CHANNELS", {CH}), \
         patch.object(short_links, "supabase", return_value=sb), \
         patch.object(interventions, "supabase", return_value=sb):
        sb._tables["video_traffic_source_daily"].extend(traffic)
        sb._tables["reporting_reports_ingested"].extend(ingested)
        sb._tables["videos"].extend([{"id": short, "channel_id": CH, "is_short": True},
                                     {"id": target, "channel_id": CH, "is_short": False}])
        sb._tables["short_link_recommendations"] = []
        sb._serial.add("interventions")
        assert lv.run_weekly(today=today) is None
    [row] = [r for r in sb.rows("interventions") if r["lever"] == "short_link"]
    assert row["status"] == "judged"
    assert row["measurement_result"]["window"]["d0"] == d0.isoformat()
    assert row["measurement_result"]["post"] == 21 and row["measurement_result"]["pre"] == 0
    [verdict] = [r for r in sb.rows("lever_verdicts") if r["lever"] == "short_link"]
    assert verdict["arm_scope"] == "human" and verdict["treated_mean_delta"] == 21
