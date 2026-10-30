"""Slice 3 · S3.3 (#118): triage and routing for titles in the agent tick.

The real tick, triage rules, warm pool, title channel context, pipeline,
stamp, interventions.record and apply_title run against FakeSupabase (the
Slice 1 agent-tick world, tests/test_agent_tick.py). Faked at the edge: the
YouTube client, OpenRouter (the title writer's `titles.chat_json` and
decide's shadow backend) and the live transcript fetch.
"""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from app import agent_tick, autopilot as ap, decide, lever_verdicts, titles
from tests.test_agent_tick import (
    CH, NOW, SRC, SRC_DESCRIPTION, T1, T2, T3, T4, _channel, _video, day, midas_rows, outcome,
    wired, world,
)
from app.agent import loop
from tests.fakes import FakeSupabase
from tests.test_agent_loop import Model, call
from tests.test_backlinks_apply import FakeYouTube

#: The channel's most-impressed warm video: the ceiling (the top 1% of six).
#: It sits in an old backlinks experiment, so the pool picks SRC first.
BIG = "bigVideo001"
#: Warm long CTRs: SRC .01, BIG .01, T1-T4 .05 → median .05.
CTRS = {SRC: 0.01, BIG: 0.01, T1: 0.05, T2: 0.05, T3: 0.05, T4: 0.05}
TITLE = "ट्विंकल ट्विंकल | Twinkle Twinkle"
SRC_TITLE = f"Rhyme {SRC}"


def title_world(*, interventions=(), big=True, ctrs=CTRS, **kw):
    held = ([{"video_id": BIG, "channel_id": CH, "lever": "backlinks", "origin": "midas",
              "arm": "treated", "status": "judged", "applied_at": "2026-10-01T00:00:00+00:00",
              "created_at": "2026-10-01T00:00:00+00:00"}] if big else [])
    sb = world(interventions=[*held, *interventions], **kw)
    for r in sb._tables["video_reach_daily"]:
        r["ctr"] = ctrs.get(r["video_id"], r["ctr"])
    if big:
        sb._tables["videos"].append(_video(BIG))
        sb._tables["video_reach_daily"].append(
            {"video_id": BIG, "channel_id": CH, "date": day(0), "impressions": 90000,
             "ctr": ctrs[BIG]})
    sb._tables["audit_strategies"] = []
    return sb


def today_title_rows(n, *, arm="treated", status="measuring", path="pipeline"):
    return [{"video_id": f"other{i:06d}", "channel_id": CH, "lever": "title",
             "origin": "midas", "arm": arm, "status": status,
             "payload": {"path": path} if path else {"title_before": "x"},
             "created_at": NOW.isoformat()} for i in range(n)]


def _writes(*titles_):
    def chat(prompt, model=None, system=None, image_urls=None, label=None):
        return {"candidates": [{"title": t, "reason": f"why {t}"} for t in titles_]}
    return chat


@contextmanager
def titled(sb, *, backlinks=False, apply=True, channels=(CH,), agent_pct=0.0,
           chat=None, yt=None, agent=None, **kw):
    """The agent-tick world wired, with the title lever's settings, its
    writer and the agent's model (`agent`, a tests.test_agent_loop.Model)
    faked. Backlinks off unless asked."""
    yt = yt or FakeYouTube({SRC: {"title": SRC_TITLE, "description": SRC_DESCRIPTION,
                                  "tags": ["a"], "categoryId": "27"}})
    with ExitStack() as stack:
        p = stack.enter_context(wired(sb, yt=yt, enabled=backlinks, **kw))
        for mod in ("titles", "titles_apply", "agent.tools"):
            stack.enter_context(patch(f"app.{mod}.supabase", return_value=sb))
        stack.enter_context(patch.multiple(
            ap.settings, TITLE_CHANNELS=set(channels), TITLE_APPLY_ENABLED=apply,
            TITLE_AGENT_PCT=agent_pct, TITLE_DAILY_CAP=10, TITLE_AGENT_DAILY_RUNS=20,
            TITLE_EXCLUDE_VIDEOS=set(), TITLE_MAX_IMPRESSIONS=5_000_000,
            TITLE_CANDIDATES=3, WRITER_MODEL="writer/model"))
        p["chat"] = stack.enter_context(
            patch("app.titles.chat_json", side_effect=chat or _writes(TITLE)))
        stack.enter_context(patch("app.titles.fetch_transcript", return_value=(None, None)))
        p["agent"] = stack.enter_context(patch(
            "app.agent.loop.chat_tools",
            side_effect=agent or AssertionError("the agent ran on the pipeline path")))
        titles._strategy_rows_ensured.clear()
        yield p
        titles._strategy_rows_ensured.clear()


def titles_today(sb):
    """`_titles_today` once the rows just written have the `created_at` the
    database would give them (FakeSupabase sets none)."""
    for r in sb._tables["interventions"]:
        r.setdefault("created_at", NOW.isoformat())
    return agent_tick._titles_today(CH)


def src_rows(sb):
    """The Midas rows on the pick (BIG's held row left out)."""
    return [r for r in midas_rows(sb) if r["video_id"] == SRC]


def title_rows(sb):
    return [r for r in midas_rows(sb) if r["lever"] == "title"]


# ── the treated pipeline title, end to end ────────────────────────────────

def test_a_channel_with_titles_on_and_backlinks_off_retitles_through_the_pipeline():
    sb = title_world()
    with titled(sb) as p:
        ap.tick()
        stamp = titles.strategy_inputs("pipeline")[0]
    assert outcome(p) == "measuring"
    [row] = src_rows(sb)
    assert (row["video_id"], row["lever"], row["arm"], row["status"]) == (
        SRC, "title", "treated", "measuring")
    payload = row["payload"]
    assert (payload["title_before"], payload["title"], payload["path"]) == (
        SRC_TITLE, TITLE, "pipeline")
    assert payload["reason"] == f"why {TITLE}" and payload["candidates"][0]["check"] is None
    assert row["strategy_version"] == stamp
    assert row["triage_json"]["answer"] == "title"
    ctx = row["triage_json"]["context"]
    assert (ctx["backlinks_enabled"], ctx["title_enabled"], ctx["title_excluded"],
            ctx["channel_median_ctr"]) == (False, True, False, pytest.approx(0.05))
    [log] = sb.rows("decision_log")
    assert log["intervention_id"] == row["id"]
    assert log["question_set_version"] == "2026.11-s3-v1"
    # Only the title changed on YouTube.
    [(part, body)] = p["yt"].updates
    assert part == "snippet" and body["snippet"]["title"] == TITLE
    assert body["snippet"]["description"] == SRC_DESCRIPTION
    assert body["snippet"]["tags"] == ["a"]
    p["audit"].assert_not_called()


def test_backlinks_win_when_both_levers_apply():
    sb = title_world()
    with titled(sb, backlinks=True) as p:
        ap.tick()
    [row] = src_rows(sb)
    assert (row["lever"], row["status"]) == ("backlinks", "measuring")
    assert row["triage_json"]["context"]["title_enabled"] is True
    p["chat"].assert_not_called()


def test_a_title_holdout_records_title_before_and_calls_no_writer():
    sb = title_world()
    with titled(sb, holdout_pct=1.0) as p:
        ap.tick()
    assert outcome(p) == "holdout"
    [row] = src_rows(sb)
    assert (row["lever"], row["arm"], row["status"]) == ("title", "holdout", "holdout")
    assert row["payload"] == {"title_before": SRC_TITLE}
    p["chat"].assert_not_called()
    assert p["yt"].lists == [] and p["yt"].updates == []


def test_no_passing_candidate_cancels_with_checks_failed_and_sends_nothing():
    sb = title_world()
    with titled(sb, chat=_writes("Twinkle in English only")) as p:
        ap.tick()
    assert outcome(p) == "cancelled"
    [row] = src_rows(sb)
    assert (row["lever"], row["arm"], row["status"]) == ("title", "treated", "cancelled")
    assert row["payload"]["error"]["reason"] == "checks_failed"
    assert "script" in row["payload"]["error"]["detail"]
    assert len(row["payload"]["candidates"]) == 2          # one per attempt
    assert p["chat"].call_count == 2
    assert p["yt"].updates == []


def test_a_writer_that_raises_cancels_the_row_and_counts_a_failure():
    def down(*a, **kw):
        raise RuntimeError("OpenRouter 503")

    sb = title_world()
    with titled(sb, chat=down) as p:
        ap.tick()
        failures = ap._failure_counts.get(CH)
    assert outcome(p) == "agent_failed" and failures == 1
    [row] = src_rows(sb)
    assert row["status"] == "cancelled"
    assert row["payload"]["error"] == {"reason": "writer_exception",
                                       "detail": "RuntimeError: OpenRouter 503"}


def test_a_title_changed_since_triage_is_cancelled_failed():
    sb = title_world()
    yt = FakeYouTube({SRC: {"title": "Edited by the team", "description": SRC_DESCRIPTION}})
    with titled(sb, yt=yt) as p:
        ap.tick()
    assert outcome(p) == "failed"
    [row] = src_rows(sb)
    assert row["status"] == "cancelled"
    assert row["payload"]["error"] == {"reason": "failed", "detail": "title_changed"}
    assert p["yt"].updates == []


def test_dry_run_cancels_the_title_rehearsal():
    sb = title_world()
    with titled(sb, dry_run=True) as p:
        ap.tick()
    assert outcome(p) == "dry_run"
    [row] = src_rows(sb)
    assert row["payload"]["error"]["reason"] == "dry_run"
    p["youtube_for_channel"].assert_not_called()


# ── videos and channels that never get a title ────────────────────────────

def _declined(sb):
    [row] = src_rows(sb)
    assert (row["lever"], row["arm"], row["status"]) == ("backlinks", "n/a", "declined")
    return row


def test_an_excluded_video_never_gets_a_title():
    sb = title_world()
    with titled(sb) as p, patch.object(ap.settings, "TITLE_EXCLUDE_VIDEOS", {SRC}):
        ap.tick()
    row = _declined(sb)
    assert row["triage_json"]["context"]["title_excluded"] is True
    assert "title: excluded" in row["payload"]["rationale"]
    p["chat"].assert_not_called()


def test_a_ceiling_video_never_gets_a_title():
    """Without BIG the pick's SRC is the channel's most-impressed warm video:
    the top 1% of five."""
    sb = title_world(big=False)
    with titled(sb) as p:
        ap.tick()
    assert _declined(sb)["triage_json"]["context"]["title_excluded"] is True
    p["chat"].assert_not_called()


def test_impressions_over_the_max_are_the_ceiling_too():
    sb = title_world()
    with titled(sb) as p, patch.object(ap.settings, "TITLE_MAX_IMPRESSIONS", 8000):
        ap.tick()                                     # SRC has 9000
    assert _declined(sb)["triage_json"]["context"]["title_excluded"] is True
    p["chat"].assert_not_called()


def test_a_video_at_or_above_the_median_ctr_never_gets_a_title():
    sb = title_world(ctrs={**CTRS, SRC: 0.05})
    with titled(sb) as p:
        ap.tick()
    assert "CTR at or above the channel median" in _declined(sb)["payload"]["rationale"]
    p["chat"].assert_not_called()


def test_a_short_never_gets_a_title():
    """The pool drops Shorts; the rule refuses one anyway (F2)."""
    sb = title_world()
    with titled(sb):
        _, ctx = agent_tick._assess({**_video(SRC), "is_short": True}, "mr")
    assert ctx["is_short"] is True and ctx["title_enabled"] is True
    assert ctx["ctr"] < ctx["channel_median_ctr"]
    assert decide.TRIAGE.rules(ctx) == "no_change"


def test_a_channel_outside_title_channels_never_gets_a_title():
    sb = title_world(description="x" * 4990)
    with titled(sb, backlinks=True, channels=("UCsomeoneelse",)) as p:
        ap.tick()                                     # backlinks' block won't fit
    row = _declined(sb)
    assert row["triage_json"]["context"]["title_enabled"] is False
    p["chat"].assert_not_called()


def test_a_closed_title_lever_and_closed_backlinks_do_nothing_at_all():
    for kw, expected in ((dict(channels=("UCsomeoneelse",)), "apply_disabled"),
                         (dict(apply=False), "apply_disabled"),
                         (dict(apply=False, backlinks=True, heading=False), "no_heading")):
        sb = title_world()
        with titled(sb, **kw) as p, patch("app.agent_tick.run") as run:
            ap.tick()
        assert outcome(p) == expected
        run.assert_not_called()
        assert [r["video_id"] for r in midas_rows(sb)] == [BIG]
        assert sb.rows("decision_log") == []


def test_with_title_apply_off_no_title_row_is_written_on_a_backlinks_channel():
    sb = title_world(description="x" * 4990)          # backlinks declines
    with titled(sb, backlinks=True, apply=False) as p:
        ap.tick()
    assert title_rows(sb) == []
    assert _declined(sb)["triage_json"]["context"]["title_enabled"] is False
    p["chat"].assert_not_called()


# ── the daily limits ──────────────────────────────────────────────────────

def test_the_daily_title_cap_holds():
    sb = title_world(interventions=today_title_rows(10))
    with titled(sb) as p:
        ap.tick()
    assert _declined(sb)["triage_json"]["context"]["title_enabled"] is False
    p["chat"].assert_not_called()


def test_holdout_declined_and_yesterdays_rows_dont_count_toward_the_title_cap():
    rows = (today_title_rows(9)
            + today_title_rows(3, arm="holdout", status="holdout", path=None)
            + today_title_rows(3, status="declined"))
    rows.append({**today_title_rows(1)[0], "video_id": "yesterday01",
                 "created_at": "2020-01-01T00:00:00+00:00"})
    sb = title_world(interventions=rows)
    with titled(sb):
        ap.tick()
    [row] = [r for r in title_rows(sb) if r["video_id"] == SRC]
    assert row["status"] == "measuring"


def test_the_agent_run_limit_holds_for_agent_path_videos_only():
    sb = title_world(interventions=today_title_rows(20, status="declined", path="agent"))
    with titled(sb, agent_pct=1.0) as p:
        ap.tick()
    assert _declined(sb)["triage_json"]["context"]["title_enabled"] is False
    p["chat"].assert_not_called()

    sb = title_world(interventions=today_title_rows(20, status="declined", path="agent"))
    with titled(sb, agent_pct=0.0):
        ap.tick()                                     # SRC is on the pipeline path
    [row] = [r for r in title_rows(sb) if r["video_id"] == SRC]
    assert row["payload"]["path"] == "pipeline"


def test_an_agent_path_video_is_written_by_the_agent():
    agent = Model([call("get_video"), call("write_candidates")],
                  [call("submit_title", title=TITLE, reasoning="plain words")])
    sb = title_world(interventions=today_title_rows(19, status="declined", path="agent"))
    with titled(sb, agent_pct=1.0, agent=agent) as p:
        ap.tick()
        stamp = titles.strategy_inputs("agent")[0]
        today = titles_today(sb)
    assert outcome(p) == "measuring"
    [row] = [r for r in title_rows(sb) if r["video_id"] == SRC]
    assert (row["arm"], row["status"], row["strategy_version"]) == (
        "treated", "measuring", stamp)
    payload = row["payload"]
    assert (payload["path"], payload["title_before"], payload["title"], payload["reason"]) == (
        "agent", SRC_TITLE, TITLE, "plain words")
    assert payload["candidates"] == [{"title": TITLE, "check": None,
                                      "reasoning": "plain words"}]
    assert row["trajectory"]["turns"] == 2 and row["trajectory"]["end"]["kind"] == "title"
    assert loop.tools_called(row["trajectory"]) == ["get_video", "write_candidates",
                                                    "submit_title"]
    [(part, body)] = p["yt"].updates
    assert part == "snippet" and body["snippet"]["title"] == TITLE
    assert body["snippet"]["description"] == SRC_DESCRIPTION
    p["chat"].assert_called_once()                    # the writer tool, once
    assert today == (1, 20)


def test_an_agent_decline_is_a_treated_declined_row_with_no_youtube_call_or_quota():
    agent = Model([call("get_title_history")], [call("decline", reason="it already works")])
    sb = title_world()
    with titled(sb, agent_pct=1.0, agent=agent) as p:
        ap.tick()
        today = titles_today(sb)
    assert outcome(p) == "declined"
    [row] = src_rows(sb)
    assert (row["lever"], row["arm"], row["status"]) == ("title", "treated", "declined")
    assert row["payload"] == {"path": "agent", "title_before": SRC_TITLE,
                              "rationale": "it already works"}
    assert row["strategy_version"] is None and row["applied_at"] is None
    assert row["trajectory"]["end"]["kind"] == "decline"
    assert p["yt"].lists == [] and p["yt"].updates == []
    assert [r for r in sb.rows("quota_log") if r.get("units")] == []
    p["chat"].assert_not_called()
    # Counts as an agent run, not toward TITLE_DAILY_CAP nor autopilot_daily_cap (F14).
    assert today == (0, 1)
    with titled(sb):
        assert ap._applies_today(CH) == 0
    [log] = sb.rows("decision_log")
    assert log["intervention_id"] == row["id"]


def test_a_treated_agent_title_spends_quota_where_a_decline_spends_none():
    agent = Model([call("submit_title", title=TITLE, reasoning="r")])
    sb = title_world()
    with titled(sb, agent_pct=1.0, agent=agent):
        ap.tick()
    assert sum(r.get("units") or 0 for r in sb.rows("quota_log")) == 51


@pytest.mark.parametrize("turns,reason", [
    ([[call("get_video")]] * 12, "turn_cap"),
    ([[call("submit_title", title="English", reasoning="a")],
      [call("submit_title", title="English too", reasoning="b")]], "checks_failed"),
])
def test_an_agent_run_without_a_title_or_decline_is_cancelled_with_its_reason(turns, reason):
    sb = title_world()
    with titled(sb, agent_pct=1.0, agent=Model(*turns)) as p, \
         patch.object(ap.settings, "AGENT_MAX_TURNS", 12):
        ap.tick()
        today = titles_today(sb)
    assert outcome(p) == "cancelled"
    [row] = src_rows(sb)
    assert (row["lever"], row["arm"], row["status"]) == ("title", "treated", "cancelled")
    assert row["payload"]["error"]["reason"] == reason
    assert row["payload"]["path"] == "agent" and row["payload"]["title"] is None
    assert row["trajectory"]["end"] == {"kind": "failed", "reason": reason,
                                        "detail": row["payload"]["error"]["detail"]}
    assert p["yt"].lists == [] and p["yt"].updates == []
    assert today == (1, 1)


def test_an_agent_whose_model_fails_is_cancelled_with_its_trajectory_and_counts_a_failure():
    def down(messages, tools_, **kw):
        raise RuntimeError("OpenRouter 503")

    sb = title_world()
    with titled(sb, agent_pct=1.0, agent=down) as p:
        ap.tick()
        failures = ap._failure_counts.get(CH)
    assert outcome(p) == "agent_failed" and failures == 1
    [row] = src_rows(sb)
    assert row["status"] == "cancelled" and row["payload"]["path"] == "agent"
    assert row["payload"]["error"] == {"reason": "writer_exception",
                                       "detail": "RuntimeError: OpenRouter 503"}
    assert row["trajectory"]["turns"] == 1


def test_pipeline_rows_carry_no_trajectory():
    sb = title_world()
    with titled(sb):
        ap.tick()
    [row] = src_rows(sb)
    assert row["payload"]["path"] == "pipeline" and "trajectory" not in row


def test_titles_count_toward_the_shared_daily_cap():
    sb = title_world(channel=_channel(autopilot_daily_cap=1))
    with titled(sb) as p:
        ap.tick()
        ap.tick()
    assert outcome(p) == "daily_cap"
    assert len(title_rows(sb)) == 1


# ── the path split ────────────────────────────────────────────────────────

def no_verdicts():
    """No title verdict yet: path_stopped (S3.5) reads an empty lever_verdicts."""
    return patch.object(lever_verdicts, "supabase",
                        return_value=FakeSupabase({"lever_verdicts": []}))


def test_a_stopped_path_hands_its_videos_to_the_other():
    ids = [f"vid{i:08d}" for i in range(400)]
    with patch.object(titles.settings, "TITLE_AGENT_PCT", 0.5):
        hashed = {v: titles.title_path(v) for v in ids}
        with patch.object(titles, "path_stopped", lambda ch, path: path == titles.PIPELINE):
            assert {titles.route(CH, v) for v in ids} == {titles.AGENT}
            assert not titles.stopped(CH)
        with patch.object(titles, "path_stopped", lambda ch, path: path == titles.AGENT):
            assert {titles.route(CH, v) for v in ids} == {titles.PIPELINE}
        with no_verdicts():
            assert {v: titles.route(CH, v) for v in ids} == hashed
    with patch.object(titles, "path_stopped", lambda ch, path: True):
        assert titles.stopped(CH)


def test_both_paths_stopped_closes_the_title_lever():
    with patch.object(titles, "path_stopped", lambda ch, path: True), \
         patch.multiple(ap.settings, TITLE_CHANNELS={CH}, TITLE_APPLY_ENABLED=True):
        assert agent_tick.titles_open(CH) is False
    with no_verdicts(), patch.multiple(ap.settings, TITLE_CHANNELS={CH}, TITLE_APPLY_ENABLED=True):
        assert agent_tick.titles_open(CH) is True


def test_the_title_channel_context_is_kept_with_the_target_pool():
    sb = title_world()
    reads = []
    real = titles.channel_context

    def counting(channel_id):
        reads.append(channel_id)
        return real(channel_id)

    with titled(sb), patch.object(titles, "channel_context", counting):
        first = agent_tick.title_channel(CH)
        assert agent_tick.title_channel(CH) is first and reads == [CH]
        assert first.median_ctr == pytest.approx(0.05) and BIG in first.ceiling
        with patch.object(agent_tick, "POOL_TTL_SECONDS", 0):
            agent_tick.title_channel(CH)
        assert reads == [CH, CH]


def test_the_backlinks_preview_shows_a_title_answer_with_its_arm():
    sb = title_world(description=f"Twinkle\nhttps://youtu.be/{T1}")     # D5: no backlinks
    with titled(sb, holdout_pct=1.0) as p:
        [item] = agent_tick.preview(CH, 1)
    assert (item["answer"], item["arm"], item["rationale"]) == ("title", "holdout", None)
    assert sb.writes == []
    p["chat"].assert_not_called()

