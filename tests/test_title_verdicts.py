"""Slice 3 · S3.5 (#120): title verdicts per path against the shared holdout,
the two stop rules, the path hand-over, the auto-revert, the title-test
endpoint and the job's title half.

The real write_verdicts, auto_revert, revert_title (with its quota gate and
yt_* helpers), run_weekly and endpoint run against FakeSupabase; only YouTube
is faked (tests/test_backlinks_apply.py FakeYouTube).
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import backlinks_apply as ba, eligibility, lever_measurement, main, quota, reach
from app import lever_verdicts as lv
from app import title_measurement as tm
from app import titles, titles_apply as ta
from app.config import settings
from app.job_status import JobRunFailed
from tests.fakes import FakeSupabase
from tests.test_backlinks_apply import FakeYouTube

CH = "UCmarathi1"
#: Four consecutive Mondays.
W1, W2, W3, W4 = (date(2026, 11, 2) + timedelta(weeks=k) for k in range(4))


def row(id_, arm, delta, week, path="pipeline", status="judged", pre=200, applied=True,
        **kw) -> dict:
    """A title row judged on the Tuesday of `week`."""
    payload = {"path": path, "title": f"New {id_}", "title_before": f"Old {id_}"}
    if arm == "holdout":
        payload = {"title_before": f"Old {id_}"}
    return {"id": id_, "video_id": f"video{id_:05d}", "channel_id": CH, "lever": "title",
            "origin": "midas", "arm": arm, "status": status, "payload": payload,
            "applied_at": (f"{week - timedelta(days=15)}T08:00:00+00:00"
                           if arm == "treated" and applied else None),
            "before_state": {"title": f"Old {id_}"} if arm == "treated" and applied else None,
            "created_at": f"{week - timedelta(days=15)}T08:00:00+00:00",
            "measurement_result": {"pre": pre, "post": pre, "delta": delta,
                                   "judged_at": f"{week + timedelta(days=1)}T09:00:00+00:00"},
            **kw}


def pipe(id_, delta, week, **kw):
    return row(id_, "treated", delta, week, **kw)


def agent(id_, delta, week, **kw):
    return row(id_, "treated", delta, week, path="agent", **kw)


def decline(id_, delta, week, **kw):
    return row(id_, "treated", delta, week, path="agent", applied=False, **kw)


def hold(id_, delta, week, **kw):
    return row(id_, "holdout", delta, week, **kw)


@contextmanager
def db(interventions=(), verdicts=(), quota_log=()):
    sb = FakeSupabase({"interventions": list(interventions), "lever_verdicts": list(verdicts),
                       "channels": [{"id": CH}], "videos": [], "quota_log": list(quota_log),
                       "video_traffic_source_daily": [], "reporting_reports_ingested": [],
                       "video_reach_daily": [], "playlist_arms": []})
    with patch.object(lv, "supabase", return_value=sb), \
         patch.object(tm, "supabase", return_value=sb), \
         patch.object(lever_measurement, "supabase", return_value=sb), \
         patch.object(reach, "supabase", return_value=sb), \
         patch.object(eligibility, "supabase", return_value=sb), \
         patch.multiple(settings, TITLE_MIN_LIFT=0.05, TITLE_EXPERIMENT_WINDOWS=4,
                        TITLE_HARM_WINDOWS=2, TITLE_HARM_LIFT=0.10, TITLE_REVERT_LIFT=0.30,
                        TITLE_REVERTS_PER_DAY=10, TITLE_MIN_PRE_VIEWS=100,
                        TRAFFIC_INGEST_CHANNELS=set()):
        yield sb


def scope_rows(sb, scope) -> list[dict]:
    return sorted((r for r in sb.rows("lever_verdicts") if r["arm_scope"] == scope),
                  key=lambda r: r["week_start"])


def tuesday(week: date) -> date:
    return week + timedelta(days=1)


# ── the verdicts ─────────────────────────────────────────────────────────

def test_two_path_scopes_share_one_holdout():
    rows = [pipe(1, 0.4, W1), pipe(2, 0.2, W1), agent(3, -0.1, W1),
            hold(4, 0.1, W1), hold(5, 0.0, W1)]
    with db(rows) as sb:
        out = lv.write_verdicts(CH, today=tuesday(W1), lever="title")
    [p] = scope_rows(sb, "pipeline_vs_holdout")
    [a] = scope_rows(sb, "agent_vs_holdout")
    assert set(out) == {"pipeline_vs_holdout", "agent_vs_holdout"}
    assert p["lever"] == a["lever"] == "title"
    assert (p["n_treated"], p["n_holdout"], a["n_treated"], a["n_holdout"]) == (2, 2, 1, 2)
    assert p["holdout_mean_delta"] == a["holdout_mean_delta"] == pytest.approx(0.05)
    assert p["lift"] == pytest.approx(0.25) and p["verdict"] == "helped"
    assert a["lift"] == pytest.approx(-0.15) and a["verdict"] == "worse"
    assert (p["windows_judged"], a["windows_judged"]) == (1, 1)


def test_agent_declines_count_in_the_agent_mean():
    rows = [agent(1, 0.3, W1), decline(2, 0.0, W1), hold(3, 0.0, W1)]
    with db(rows) as sb:
        lv.write_verdicts(CH, today=tuesday(W1), lever="title")
    [a] = scope_rows(sb, "agent_vs_holdout")
    assert a["n_treated"] == 2 and a["treated_mean_delta"] == pytest.approx(0.15)
    assert scope_rows(sb, "pipeline_vs_holdout") == []


@pytest.mark.parametrize("lift, verdict", [(0.05, "helped"), (0.049, "no_change"),
                                           (-0.049, "no_change"), (-0.05, "worse")])
def test_the_verdict_band_is_title_min_lift(lift, verdict):
    with db([pipe(1, lift, W1), hold(2, 0.0, W1)]) as sb:
        lv.write_verdicts(CH, today=tuesday(W1), lever="title")
    assert scope_rows(sb, "pipeline_vs_holdout")[0]["verdict"] == verdict


def test_insufficient_and_unjudged_rows_stay_out_a_reverted_judged_title_stays_in():
    rows = [pipe(1, 0.2, W1), hold(2, 0.0, W1),
            pipe(3, 9.0, W1, status="insufficient_data", pre=50),
            pipe(4, 9.0, W1, status="measuring"),
            pipe(5, -0.6, W1, status="cancelled",
                 payload={"path": "pipeline", "title": "New", "revert": {"auto": True}}),
            pipe(6, 9.0, W1, status="cancelled", pre=50,
                 payload={"path": "pipeline", "revert": {"auto": False}})]
    with db(rows) as sb:
        lv.write_verdicts(CH, today=tuesday(W1), lever="title")
    [p] = scope_rows(sb, "pipeline_vs_holdout")
    assert p["n_treated"] == 2 and p["treated_mean_delta"] == pytest.approx(-0.2)


def test_the_stop_rule_fires_after_four_windows_below_the_bar_per_path():
    rows = []
    for k, week in enumerate((W1, W2, W3, W4)):
        rows += [pipe(10 * k + 1, 0.04, week), agent(10 * k + 2, 0.2, week),
                 hold(10 * k + 3, 0.0, week)]
    with db(rows) as sb:
        for week in (W1, W2, W3, W4):
            lv.write_verdicts(CH, today=tuesday(week), lever="title")
        assert lv.stopped(CH, "title", "pipeline_vs_holdout") is True
        assert lv.stopped(CH, "title", "agent_vs_holdout") is False
    pipeline = scope_rows(sb, "pipeline_vs_holdout")
    assert [r["stop_rule_triggered"] for r in pipeline] == [False, False, False, True]
    assert not any(r["stop_rule_triggered"] for r in scope_rows(sb, "agent_vs_holdout"))


def test_the_harm_guard_stops_a_path_after_two_windows_at_or_below_minus_ten_percent():
    rows = [agent(1, -0.1, W1), hold(2, 0.0, W1), agent(3, -0.1, W2), hold(4, 0.0, W2),
            pipe(5, -0.09, W1), pipe(6, -0.09, W2)]
    with db(rows) as sb:
        lv.write_verdicts(CH, today=tuesday(W1), lever="title")
        assert lv.stopped(CH, "title", "agent_vs_holdout") is False    # one window only
        lv.write_verdicts(CH, today=tuesday(W2), lever="title")
        assert lv.stopped(CH, "title", "agent_vs_holdout") is True
        assert lv.stopped(CH, "title", "pipeline_vs_holdout") is False  # −0.09 > −0.10
        assert lv.stopped(CH) is False                                  # backlinks untouched


def test_a_stopped_path_hands_its_videos_to_the_other_and_both_stop_the_lever():
    stop = {"channel_id": CH, "lever": "title", "arm_scope": "pipeline_vs_holdout",
            "week_start": W4.isoformat(), "stop_rule_triggered": True}
    ids = [f"vid{i:08d}" for i in range(200)]
    with db(verdicts=[stop]) as sb, patch.object(settings, "TITLE_AGENT_PCT", 0.5):
        assert titles.path_stopped(CH, "pipeline") and not titles.path_stopped(CH, "agent")
        assert {titles.route(CH, v) for v in ids} == {"agent"}
        assert not titles.stopped(CH)
        sb._tables["lever_verdicts"].append({**stop, "arm_scope": "agent_vs_holdout"})
        assert titles.stopped(CH)
        assert not titles.path_stopped("UCother", "pipeline")


def test_every_title_path_has_a_scope():
    assert set(lv.TITLE_SCOPES) == set(titles.PATHS)


# ── the auto-revert ──────────────────────────────────────────────────────

LIVE = {"description": "keep me", "tags": ["a"], "categoryId": "27"}


def _snippets(rows, title_of=lambda r: r["payload"]["title"]):
    return FakeYouTube({r["video_id"]: {**LIVE, "title": title_of(r)}
                        for r in rows if r.get("applied_at")})


@contextmanager
def youtube(sb, yt, *, enabled=True):
    with patch.object(ba, "supabase", return_value=sb), \
         patch.object(ta, "supabase", return_value=sb), \
         patch.object(quota, "supabase", return_value=sb), \
         patch.object(ba, "youtube_for_channel", return_value=yt), \
         patch.multiple(settings, TITLE_APPLY_ENABLED=enabled, DRY_RUN=False):
        yield


def test_a_losing_title_is_put_back_once_and_keeps_its_numbers():
    rows = [pipe(1, -0.5, W1), pipe(2, -0.1, W1), agent(3, -0.4, W1),
            decline(4, -0.9, W1), hold(5, 0.0, W1)]
    with db(rows) as sb:
        yt = _snippets(rows)
        with youtube(sb, yt):
            counts = lv.auto_revert(CH)
            assert lv.auto_revert(CH)["attempted"] == 0       # once
    assert (counts["reverted"], counts["errored"]) == (2, 0)
    by_id = {r["id"]: r for r in sb.rows("interventions")}
    assert {i for i, r in by_id.items() if r["status"] == "cancelled"} == {1, 3}
    assert by_id[1]["payload"]["revert"]["auto"] is True
    assert by_id[1]["measurement_result"]["delta"] == -0.5
    assert yt.snippets["video00001"]["title"] == "Old 1"
    assert yt.snippets["video00002"]["title"] == "New 2"            # −0.1: kept
    assert len(yt.updates) == 2                                      # the decline sent nothing


def test_the_same_weeks_holdout_mean_else_the_cumulative_one():
    # Week 2 has no holdout: row 3 is judged against the cumulative mean (0.5).
    rows = [hold(1, 0.5, W1), pipe(2, 0.15, W1), pipe(3, 0.15, W2)]
    with db(rows) as sb:
        with youtube(sb, _snippets(rows)):
            assert lv.auto_revert(CH)["reverted"] == 2
    rows = [hold(1, 0.5, W1), hold(4, -0.5, W2), pipe(2, 0.15, W1), pipe(3, -0.15, W2)]
    with db(rows) as sb:
        with youtube(sb, _snippets(rows)):
            assert lv.auto_revert(CH)["reverted"] == 1
        assert {r["id"] for r in sb.rows("interventions") if r["status"] == "cancelled"} == {2}


def test_no_revert_while_there_is_no_holdout_mean():
    rows = [pipe(1, -2.0, W1), hold(2, 0.0, W1, status="holdout")]
    with db(rows) as sb:
        yt = _snippets(rows)
        with youtube(sb, yt):
            assert lv.auto_revert(CH)["attempted"] == 0
    assert yt.updates == []


def test_the_daily_limit_and_worst_first():
    rows = [pipe(i, -0.3 - i / 100, W1) for i in range(1, 5)] + [hold(9, 0.0, W1)]
    with db(rows) as sb, patch.object(settings, "TITLE_REVERTS_PER_DAY", 2):
        with youtube(sb, _snippets(rows)):
            assert lv.auto_revert(CH)["reverted"] == 2
        assert {r["id"] for r in sb.rows("interventions") if r["status"] == "cancelled"} == {3, 4}


def test_a_human_edited_title_is_never_touched_and_doesnt_use_the_limit():
    rows = [pipe(1, -0.9, W1), pipe(2, -0.5, W1), hold(3, 0.0, W1)]
    with db(rows) as sb, patch.object(settings, "TITLE_REVERTS_PER_DAY", 1):
        yt = _snippets(rows, lambda r: "The team's title" if r["id"] == 1 else r["payload"]["title"])
        with youtube(sb, yt):
            counts = lv.auto_revert(CH)
    assert (counts["skipped"], counts["reverted"]) == (1, 1)
    assert yt.snippets["video00001"]["title"] == "The team's title"
    status = {r["id"]: r["status"] for r in sb.rows("interventions")}
    assert status[1] == "judged" and status[2] == "cancelled"


def test_the_kill_switch_or_a_short_ledger_skips_and_retries_next_run():
    rows = [pipe(1, -0.9, W1), pipe(2, -0.8, W1), hold(3, 0.0, W1)]
    with db(rows) as sb:
        yt = _snippets(rows)
        with youtube(sb, yt, enabled=False):
            assert lv.auto_revert(CH) == {"attempted": 1, "errored": 0, "reverted": 0,
                                          "skipped": 1}
        assert yt.lists == [] and yt.updates == []
        spent = {"units": settings.YT_DAILY_QUOTA, "operation": "videos.update",
                 "occurred_at": datetime.now(timezone.utc).isoformat(), "channel_id": CH,
                 "success": True, "id": 1}
        sb._tables["quota_log"].append(spent)
        with youtube(sb, yt):
            assert lv.auto_revert(CH)["skipped"] == 1
        sb._tables["quota_log"].clear()
        with youtube(sb, yt):
            assert lv.auto_revert(CH)["reverted"] == 2
    assert all(r["status"] != "judged" or r["arm"] == "holdout" for r in sb.rows("interventions"))


def test_a_youtube_failure_is_an_errored_revert_and_the_next_still_runs():
    rows = [pipe(1, -0.9, W1), pipe(2, -0.8, W1), hold(3, 0.0, W1)]
    with db(rows) as sb:
        yt = _snippets([r for r in rows if r["id"] != 1])     # video 1 is gone
        with youtube(sb, yt):
            counts = lv.auto_revert(CH)
    assert (counts["attempted"], counts["errored"], counts["reverted"]) == (2, 1, 1)


# ── the job ──────────────────────────────────────────────────────────────

def test_the_job_measures_titles_writes_their_verdicts_then_reverts():
    calls = []
    with db([hold(1, 0.0, W1)]), \
         patch.object(lever_measurement, "measure_channel",
                      return_value={"attempted": 0, "errored": 0}), \
         patch.object(tm, "measure_channel",
                      side_effect=lambda cid, **_: calls.append("measure")
                      or {"attempted": 2, "errored": 1}), \
         patch.object(lv, "write_verdicts",
                      side_effect=lambda cid, lever="backlinks", **_: calls.append(lever)), \
         patch.object(lv, "auto_revert", side_effect=lambda cid: calls.append("revert")
                      or {"attempted": 1, "errored": 0}):
        out = lv.run_weekly(today=tuesday(W1))
    assert calls == ["backlinks", "measure", "title", "revert"]
    assert out == {"partial_errors": {CH: "title interventions: 1/2 failed"}}


def test_a_channel_without_title_rows_skips_the_title_half():
    with db(), patch.object(tm, "measure_channel") as measure:
        assert lv.run_weekly(today=tuesday(W1)) is None
    measure.assert_not_called()


@pytest.mark.parametrize("measured, reverts, message", [
    ((2, 2), (0, 0), "ItemsFailed: title interventions: all 2 failed"),
    ((0, 2), (3, 3), "ItemsFailed: title reverts: all 3 failed"),
])
def test_title_errors_are_their_own_categories(measured, reverts, message):
    with db([hold(1, 0.0, W1)]), \
         patch.object(tm, "measure_channel",
                      return_value={"attempted": measured[1], "errored": measured[0]}), \
         patch.object(lv, "auto_revert",
                      return_value={"attempted": reverts[1], "errored": reverts[0]}):
        with pytest.raises(JobRunFailed) as exc:
            lv.run_weekly(today=tuesday(W1))
    assert exc.value.failed_channels == {CH: message}


def test_the_real_job_end_to_end_writes_the_title_week():
    rows = [pipe(1, 0.3, W1), hold(2, 0.0, W1)]
    with db(rows) as sb:
        assert lv.run_weekly(today=tuesday(W1)) is None
    [p] = scope_rows(sb, "pipeline_vs_holdout")
    assert p["lift"] == pytest.approx(0.3)
    assert sb.rows("lever_verdicts") == [p]       # no backlinks row from title rows


# ── the endpoint ─────────────────────────────────────────────────────────

def _trajectory(*tools):
    return {"messages": [{"role": "assistant", "tool_calls": [{"id": str(i), "name": t}]}
                         for i, t in enumerate(tools)]}


def test_title_test_endpoint_reports_each_path_the_holdout_and_the_trace():
    common = _trajectory("get_video", "get_transcript", "submit_title")
    rows = [pipe(1, 0.2, W1), pipe(2, 0.4, W1, status="insufficient_data", pre=10),
            pipe(3, None, W1, status="cancelled", applied=False, measurement_result=None,
                 payload={"path": "pipeline", "error": {"reason": "checks_failed"}}),
            pipe(4, -0.6, W1, status="cancelled",
                 payload={"path": "pipeline", "revert": {"auto": True}}),
            agent(5, 0.1, W1, trajectory=common),
            decline(6, -0.1, W1, trajectory=_trajectory("get_video", "decline")),
            agent(7, None, W1, status="cancelled", applied=False, measurement_result=None,
                  payload={"path": "agent", "error": {"reason": "turn_cap"}}, trajectory=common),
            decline(8, None, W1, status="declined", measurement_result=None, trajectory=common),
            hold(9, 0.0, W1), hold(10, 0.1, W1), hold(11, None, W1, status="holdout",
                                                    measurement_result=None)]
    stop = {"channel_id": CH, "lever": "title", "arm_scope": "agent_vs_holdout",
            "week_start": W1.isoformat(), "stop_rule_triggered": True}
    with db(rows, [stop]):
        body = TestClient(main.app).get(f"/channels/{CH}/title-test").json()
    p, a = body["paths"]["pipeline"], body["paths"]["agent"]
    assert body["holdout"] == {"n": 3, "judged": 2, "mean_delta": pytest.approx(0.05)}
    assert (p["treated"], p["declined"], p["judged"], p["insufficient"]) == (3, 0, 2, 1)
    assert p["cancelled"] == {"checks_failed": 1, "reverted": 1}
    assert p["mean_delta"] == pytest.approx(-0.2) and p["auto_reverts"] == 1
    assert p["cumulative_lift"] == pytest.approx(-0.25) and p["stopped"] is False
    assert (a["treated"], a["declined"], a["judged"]) == (1, 2, 2)
    assert a["cancelled"] == {"turn_cap": 1} and a["stopped"] is True
    assert a["mean_delta"] == pytest.approx(0.0)
    trace = body["trace"]
    assert trace["runs"] == 4
    assert trace["most_common"] == ["get_transcript", "get_video", "submit_title"]
    assert trace["share_differing"] == pytest.approx(0.25)
    assert trace["share_calling"] == {"decline": 0.25, "get_transcript": 0.75,
                                      "get_video": 1.0, "submit_title": 0.75}
