"""Slice 1 · S1.4b (#65): the agent tick — routing, triage, holdout, the cap,
the kill switch — and the read-only preview.

These run the real tick, eligibility, reach certification, warm pool,
candidates, decide(), interventions.record, apply_backlinks and quota gate
against FakeSupabase. Faked at the edge: the YouTube client (it records every
call), OpenRouter (decide's shadow backend), and audit_video, which the agent
path must never reach.
"""
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import agent_tick, autopilot as ap, backlinks, backlinks_apply, decide, eligibility
from app.apply_outcome import ApplyError
from app import interventions as iv
from app.reembed import MODEL_VERSION
from scripts import preview_backlinks
from tests.fakes import FakeSupabase
from tests.test_backlinks_apply import FakeYouTube

CH = "UCmarathi1"
SRC = "srcVideo001"
T1, T2, T3, T4 = "tgtVideo001", "tgtVideo002", "tgtVideo003", "tgtVideo004"
OTHER_CH_VIDEO = "hindiVideo1"
HEADING = "Watch next"
SRC_DESCRIPTION = "Twinkle twinkle\nLyrics and more"
FRONTIER = date(2026, 10, 20)
REACH, TRAFFIC = "channel_reach_basic_a1", "channel_traffic_source_a3"
NOW = datetime.now(timezone.utc)
TODAY = NOW.replace(hour=0, minute=0, second=0, microsecond=0)


def day(n: int) -> str:
    return (FRONTIER - timedelta(days=n)).isoformat()


def _channel(**kw):
    return {"id": CH, "autopilot_enabled": True, "agent_enabled": True,
            "default_language": "mr", "autopilot_paused_reason": None,
            "autopilot_shorts_enabled": False, "autopilot_last_tick_at": None,
            "autopilot_daily_cap": 40, "last_synced_at": NOW.isoformat(),
            "playlist_thresholds": {"model_version": MODEL_VERSION, "join_high": 0.95,
                                    "join_low": 0.8, "leave": 0.9},
            "sync_shorts": True, **kw}


def _video(vid, channel=CH, description=""):
    return {"id": vid, "channel_id": channel, "title": f"Rhyme {vid}",
            "description": description, "privacy_status": "public", "is_short": False,
            "is_episode": False}


#: Pool order: SRC first (most impressions), then the targets.
IMPRESSIONS = {SRC: 9000, T1: 800, T2: 700, T3: 600, T4: 550}
VECTORS = {SRC: [1.0, 0.0], T1: [1.0, 0.1], T2: [1.0, 0.2], T3: [1.0, 0.3],
           T4: [0.0, 1.0]}                    # T4: warm but not similar


def world(*, channel=None, interventions=(), description=SRC_DESCRIPTION, audits=(),
          reach_days=28, verdicts=()):
    tables = {
        "channels": [channel or _channel()],
        "videos": [_video(SRC, description=description)]
                  + [_video(v) for v in (T1, T2, T3, T4)]
                  + [_video(OTHER_CH_VIDEO, channel="UChindi")],
        "reporting_reports_ingested":
            [{"report_id": f"r{d}", "channel_id": CH, "data_date": day(d),
              "report_type": REACH} for d in range(reach_days)]
            + [{"report_id": f"t{d}", "channel_id": CH, "data_date": day(d),
                "report_type": TRAFFIC} for d in range(28)],
        "video_reach_daily": [{"video_id": v, "channel_id": CH, "date": day(0),
                               "impressions": n, "ctr": 0.05}
                              for v, n in IMPRESSIONS.items()],
        "video_traffic_source_daily": [
            {"video_id": SRC, "channel_id": CH, "date": day(1), "source_type": 7,
             "source_detail": "", "views": 30},
            {"video_id": SRC, "channel_id": CH, "date": day(2), "source_type": 14,
             "source_detail": "", "views": 50},
            {"video_id": SRC, "channel_id": CH, "date": day(40), "source_type": 3,
             "source_detail": "", "views": 999},                 # outside the 28 days
        ],
        "video_embeddings": [{"video_id": v, "chunk_index": "pooled",
                              "model_version": MODEL_VERSION, "embedding": vec}
                             for v, vec in VECTORS.items()],
        "interventions": list(interventions),
        "decision_log": [],
        "audits": list(audits),
        "quota_log": [],
        "lever_verdicts": list(verdicts),
    }
    for name, rows in tables.items():
        for i, r in enumerate(rows, 1):
            r.setdefault("id", i)
    return FakeSupabase(tables, serial=("interventions", "decision_log"))


_DB_MODULES = ("autopilot", "eligibility", "reach", "warm", "backlinks", "embeddings",
               "human_edits", "interventions", "decide", "agent_tick", "backlinks_apply",
               "lever_verdicts",
               "quota", "channel_audits")


def _shadow_says_no_change(prompt, model=None, system=None, image_urls=None, label=None):
    """The shadow backend disagrees with the rules: no_change to triage, no to
    every next-watch pair."""
    if label == "decide.next_watch":
        return {"answer": "no", "probs": {"yes": 0.2, "no": 0.8}}
    return {"answer": "no_change",
            "probs": {a: (1.0 if a == "no_change" else 0.0) for a in decide.TRIAGE.answers}}


@contextmanager
def wired(sb, *, yt=None, enabled=True, dry_run=False, holdout_pct=0.0, heading=True):
    """The fake DB and YouTube installed; writes on, DRY_RUN off, no explore."""
    yt = yt or FakeYouTube({SRC: {"title": "Live", "description": SRC_DESCRIPTION,
                                  "tags": [], "categoryId": "27"}})
    with ExitStack() as stack:
        for mod in _DB_MODULES:
            stack.enter_context(patch(f"app.{mod}.supabase", return_value=sb))
        youtube = stack.enter_context(
            patch("app.backlinks_apply.youtube_for_channel", return_value=yt))
        stack.enter_context(patch.multiple(
            ap.settings, BACKLINK_APPLY_ENABLED=enabled, DRY_RUN=dry_run,
            HOLDOUT_PCT=holdout_pct, WARM_EXPLORE_PCT=0.0, WARM_POOL_USE_RPC=False,
            WARM_MIN_IMPRESSIONS=500, BACKLINK_MAX=3, BACKLINK_MIN_CANDIDATES=2,
            TRAFFIC_INGEST_CHANNELS={CH}, DECIDE_BACKEND="llm"))
        stack.enter_context(patch("app.decide.openrouter.chat_json", _shadow_says_no_change))
        stack.enter_context(patch.dict(backlinks.HEADINGS, {"mr": HEADING} if heading else {},
                                       clear=True))
        audit = stack.enter_context(patch("app.audits.audit_video"))
        span = stack.enter_context(patch("app.autopilot.tracing.span"))
        rec = MagicMock()
        span.return_value.__enter__.return_value = rec
        ap._yt_quota_exhausted_until = None
        ap._failure_counts.clear()
        yield {"yt": yt, "youtube_for_channel": youtube, "audit": audit, "rec": rec}
        ap._failure_counts.clear()


def outcome(p):
    calls = [c.kwargs["tick.outcome"] for c in p["rec"].set.call_args_list
             if "tick.outcome" in c.kwargs]
    return calls[-1]


def midas_rows(sb):
    return [r for r in sb.rows("interventions") if r["origin"] == "midas"]


# ── routing ───────────────────────────────────────────────────────────────

def test_with_agent_enabled_off_the_tick_does_the_shorts_action_only():
    """S3.6 (F13): the house-format title path is gone from the tick. A channel
    with autopilot_enabled on and agent_enabled off (or unset) gets the Shorts
    action and nothing else: no pick, no audit, no agent, no YouTube call."""
    for channel in (_channel(agent_enabled=False, autopilot_shorts_enabled=True),
                    {k: v for k, v in _channel(autopilot_shorts_enabled=True).items()
                     if k != "agent_enabled"}):
        sb = world(channel=channel)
        with wired(sb) as p, \
             patch("app.autopilot._run_shorts_action") as shorts, \
             patch("app.autopilot.agent_tick.run") as agent_run, \
             patch("app.autopilot._next_video_for_channel") as pick:
            ap.tick()
        shorts.assert_called_once()
        assert outcome(p) == "shorts_only"
        agent_run.assert_not_called()
        pick.assert_not_called()
        p["audit"].assert_not_called()
        p["youtube_for_channel"].assert_not_called()
        assert sb.rows("interventions") == [] and sb.rows("decision_log") == []
        assert sb.rows("channels")[0]["autopilot_last_tick_at"] is not None


def test_an_agent_tick_applies_backlinks_and_never_calls_audit_video():
    sb = world()
    with wired(sb) as p:
        ap.tick()
    p["audit"].assert_not_called()
    assert outcome(p) == "measuring"
    [row] = midas_rows(sb)
    assert (row["video_id"], row["lever"], row["arm"], row["status"]) == (
        SRC, "backlinks", "treated", "measuring")
    assert [t["video_id"] for t in row["payload"]["targets"]] == [T1, T2, T3]
    assert row["applied_at"] is not None
    [(part, body)] = p["yt"].updates
    assert part == "snippet" and HEADING in body["snippet"]["description"]


def test_an_agent_channel_whose_agent_path_is_closed_does_nothing():
    for channel, reach_days in ((_channel(), 10),                  # reach not certified
                                (_channel(autopilot_paused_reason="repeated_failures",
                                          autopilot_shorts_enabled=True), 28)):
        sb = world(channel=channel, reach_days=reach_days)
        with wired(sb) as p, patch("app.autopilot._run_shorts_action"):
            ap.tick()
        _assert_did_nothing(sb, p)


def _assert_did_nothing(sb, p):
    p["audit"].assert_not_called()
    assert outcome(p) == "agent_ineligible"
    assert sb.rows("interventions") == [] and p["yt"].lists == []


# ── can_run_agent ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("channel, reach_days, expected", [
    (_channel(), 28, True),
    (_channel(autopilot_enabled=False), 28, False),             # can_audit: not enabled
    (_channel(autopilot_paused_reason="token_expired"), 28, False),   # can_audit: paused
    (_channel(default_language=None), 28, False),                # can_audit: no language
    (_channel(agent_enabled=False), 28, False),                  # agent_enabled
    (_channel(), 10, False),                                     # reach not certified
])
def test_can_run_agent(channel, reach_days, expected):
    sb = world(channel=channel, reach_days=reach_days)
    with wired(sb):
        assert eligibility.can_run_agent(channel) is expected


# ── holdout ───────────────────────────────────────────────────────────────

def test_a_holdout_records_its_would_be_targets_and_never_calls_youtube():
    sb = world()
    with wired(sb, holdout_pct=1.0) as p:
        ap.tick()
    assert outcome(p) == "holdout"
    [row] = midas_rows(sb)
    assert (row["arm"], row["status"], row["applied_at"]) == ("holdout", "holdout", None)
    assert [t["video_id"] for t in row["payload"]["targets"]] == [T1, T2, T3]
    p["youtube_for_channel"].assert_not_called()
    assert p["yt"].lists == [] and p["yt"].updates == []


# ── the cap ───────────────────────────────────────────────────────────────

def _iv(vid, status, arm, applied_at=None, origin="midas", created_at=None):
    return {"video_id": vid, "channel_id": CH, "lever": "backlinks", "origin": origin,
            "arm": arm, "status": status, "applied_at": applied_at,
            "created_at": created_at or NOW.isoformat(), "payload": {}}


def test_applied_midas_interventions_count_toward_the_cap_and_holdout_declined_do_not():
    today = (TODAY + timedelta(minutes=5)).isoformat()
    yesterday = (TODAY - timedelta(hours=1)).isoformat()
    sb = world(
        interventions=[
            _iv(T1, "measuring", "treated", applied_at=today),      # counts
            _iv(T2, "holdout", "holdout"),                          # no
            _iv(T3, "declined", "n/a"),                             # no
            _iv(T4, "measuring", "treated", applied_at=yesterday),  # not today
            _iv(T4, "applied", "n/a", origin="human"),              # not Midas
        ],
        audits=[{"status": "applied", "applied_at": today, "videos.channel_id": CH}],
    )
    with wired(sb):
        assert ap._applies_today(CH) == 2                           # the audit + T1

    # Treated attempts today that never reached YouTube count too (review,
    # 2026-10-23), so a systematic failure is bounded by the cap.
    sb = world(interventions=[
        _iv(T1, "cancelled", "treated"),                            # counts
        _iv(T2, "cancelled", "treated", created_at=yesterday),      # not today
        _iv(T3, "holdout", "holdout"),                              # no
    ])
    with wired(sb):
        assert ap._applies_today(CH) == 1

    sb = world(channel=_channel(autopilot_daily_cap=2), interventions=[
        _iv(T1, "measuring", "treated", applied_at=today),
        _iv(T2, "measuring", "treated", applied_at=today)])
    with wired(sb) as p:
        ap.tick()
    assert outcome(p) == "daily_cap"
    assert len(midas_rows(sb)) == 2 and sb.rows("decision_log") == []


# ── one active Midas intervention per video ───────────────────────────────

def test_a_second_active_midas_intervention_is_impossible():
    """The pool excludes held videos; a pick that raced past it is refused by record."""
    sb = world(interventions=[_iv(SRC, "holdout", "holdout")])
    with wired(sb) as p, patch("app.agent_tick.warm.warm_pool",
                                return_value=[{"id": SRC, "impressions": 9000,
                                               "explore": False}]):
        ap.tick()
    assert outcome(p) == "active_intervention"
    assert len(midas_rows(sb)) == 1
    assert p["yt"].updates == []
    assert ap._failure_counts.get(CH, 0) == 0
    with wired(sb), pytest.raises(iv.ActiveInterventionExists):
        iv.record(video_id=SRC, channel_id=CH, lever="backlinks", origin="midas",
                  arm="treated", status="planned")


# ── the kill switch, DRY_RUN, failures ────────────────────────────────────

def test_the_kill_switch_makes_the_agent_do_nothing_at_all():
    """Slice 1 review (2026-10-23): with writes off a tick used to pick, triage
    and record rows that never reached YouTube, using up the experiment's pool.
    Now it does nothing: no pick, no LLM call, no row, no YouTube call."""
    sb = world()
    with wired(sb, enabled=False) as p, \
         patch("app.agent_tick.run") as run:
        ap.tick()
    assert outcome(p) == "apply_disabled"
    run.assert_not_called()
    assert midas_rows(sb) == [] and sb.rows("decision_log") == []
    p["youtube_for_channel"].assert_not_called()
    assert p["yt"].lists == [] and p["yt"].updates == []
    assert ap._failure_counts.get(CH, 0) == 0


def test_with_no_heading_for_the_language_the_agent_does_nothing():
    """S1.2/D3: Marathi's heading isn't in the table yet. Every pick would end in a
    refused render, so the agent waits instead of burning videos and LLM calls."""
    sb = world()
    with wired(sb, heading=False) as p, patch("app.agent_tick.run") as run:
        ap.tick()
    assert outcome(p) == "no_heading"
    run.assert_not_called()
    assert midas_rows(sb) == []
    p["youtube_for_channel"].assert_not_called()


def test_the_backlinks_apply_still_refuses_while_writes_are_off():
    """Belt and braces under the tick's gate: apply_backlinks itself refuses."""
    sb = world()
    with wired(sb, enabled=False):
        row = iv.record(video_id=SRC, channel_id=CH, lever="backlinks", origin="midas",
                        arm="treated", status="planned",
                        payload={"targets": [{"video_id": T1, "channel_id": CH, "title": "t"}]})
        with pytest.raises(ApplyError) as e:
            backlinks_apply.apply_backlinks(row)
    assert e.value.outcome.value == "apply_disabled"


def test_dry_run_sends_nothing_and_cancels_the_rehearsal():
    sb = world()
    with wired(sb, dry_run=True) as p:
        ap.tick()
    assert outcome(p) == "dry_run"
    [row] = midas_rows(sb)
    assert row["status"] == "cancelled" and row["payload"]["error"]["reason"] == "dry_run"
    assert HEADING in row["payload"]["description"]
    p["youtube_for_channel"].assert_not_called()


def test_a_youtube_failure_cancels_with_the_error_and_counts_a_failure():
    yt = FakeYouTube({SRC: {"title": "Live", "description": SRC_DESCRIPTION}},
                     fail=RuntimeError("backendError"))
    sb = world()
    with wired(sb, yt=yt) as p:
        ap.tick()
        assert ap._failure_counts[CH] == 1
    assert outcome(p) == "failed"
    [row] = midas_rows(sb)
    assert row["status"] == "cancelled" and row["payload"]["error"]["reason"] == "failed"
    assert "backendError" in row["payload"]["error"]["detail"]


# ── triage ────────────────────────────────────────────────────────────────

def test_triage_is_deterministic_for_a_given_context():
    sb = world()
    with wired(sb):
        video = agent_tick._video(SRC)
        (found1, ctx1), (found2, ctx2) = agent_tick._assess(video, "mr"), agent_tick._assess(video, "mr")
        assert ctx1 == ctx2 and found1 == found2
        answers = {decide.decide(decide.TRIAGE, SRC, ctx1).answer for _ in range(3)}
    assert answers == {"backlinks"}                 # the shadow said no_change every time
    assert ctx1["backlink_candidates"] == 3
    assert ctx1["traffic_mix_28d"] == {"Suggested videos": 30, "Playlists": 50}
    assert ctx1["impressions"] == 9000 and ctx1["ctr"] == pytest.approx(0.05)
    assert {r["used"] for r in sb.rows("decision_log")} == {"rules"}
    assert {r["jev_answer"] for r in sb.rows("decision_log")} == {"no_change"}


def test_the_tick_reads_a_channels_target_pool_once_an_hour():
    """Reading the pool pulls every warm target's vector on the channel and its
    siblings: minutes on a channel with many siblings, so it's kept an hour."""
    sb = world()
    reads = []
    real = agent_tick.backlinks.target_pool

    def counting(channel_id, **kw):
        reads.append(channel_id)
        return real(channel_id, **kw)

    with wired(sb), patch.object(agent_tick.backlinks, "target_pool", counting):
        video = agent_tick._video(SRC)
        first, _ = agent_tick._assess(video, "mr")
        again, _ = agent_tick._assess(video, "mr")
        assert reads == [CH] and again == first
        with patch.object(agent_tick, "POOL_TTL_SECONDS", 0):
            stale, _ = agent_tick._assess(video, "mr")
        assert reads == [CH, CH] and stale == first
    assert first.rows
    assert all(type(v).__name__ == "array" for v in agent_tick._pools[CH][1].vectors.values())


def test_a_block_that_would_not_fit_is_declined_before_the_arm_is_drawn():
    """A description that the block would push past 5,000 characters: declined in
    either arm alike, so it never becomes a treated failure that counts toward
    the channel's pause."""
    sb = world(description="x" * 4990)
    with wired(sb, holdout_pct=1.0) as p:
        ap.tick()
    assert outcome(p) == "declined"
    [row] = midas_rows(sb)
    assert (row["status"], row["arm"]) == ("declined", "n/a")
    assert "can't be rendered" in row["payload"]["rationale"]
    assert "over 5000" in row["triage_json"]["render_refused"]
    assert p["yt"].lists == [] and p["yt"].updates == []


def test_d5_a_description_that_links_to_our_video_gets_no_change():
    sb = world(description=f"{SRC_DESCRIPTION}\nhttps://youtu.be/{OTHER_CH_VIDEO}")
    with wired(sb) as p:
        ap.tick()
    assert outcome(p) == "declined"
    [row] = midas_rows(sb)
    assert (row["status"], row["arm"], row["lever"]) == ("declined", "n/a", "backlinks")
    assert "D5" in row["payload"]["rationale"]
    assert row["triage_json"]["context"]["has_related_block"] is True
    assert p["yt"].lists == []


def test_a_link_to_a_video_that_isnt_ours_is_no_related_block():
    sb = world(description=f"{SRC_DESCRIPTION}\nhttps://youtu.be/notOurVideo")
    with wired(sb):
        _, context = agent_tick._assess(agent_tick._video(SRC), "mr")
    assert context["has_related_block"] is False


def test_a_stopped_lever_gets_no_change():
    sb = world()
    with wired(sb) as p, patch("app.agent_tick.backlinks_stopped", return_value=True):
        ap.tick()
    [row] = midas_rows(sb)
    assert row["status"] == "declined" and "stopped" in row["payload"]["rationale"]
    assert p["yt"].lists == []


def test_too_few_candidates_gets_no_change():
    sb = world()
    with wired(sb) as p:
        ap.settings.BACKLINK_MIN_CANDIDATES = 4
        ap.tick()
    [row] = midas_rows(sb)
    assert row["status"] == "declined"
    assert "fewer than BACKLINK_MIN_CANDIDATES = 4" in row["payload"]["rationale"]


def _verdict(stopped, **kw):
    return {"channel_id": CH, "lever": "backlinks", "arm_scope": "treated_vs_holdout",
            "week_start": "2026-10-12", "stop_rule_triggered": stopped, **kw}


def test_backlinks_stops_once_any_treated_vs_holdout_verdict_triggered_the_stop_rule():
    with wired(world()):
        assert agent_tick.backlinks_stopped(CH) is False
    with wired(world(verdicts=[_verdict(False)])):
        assert agent_tick.backlinks_stopped(CH) is False
    # A human row never stops the lever, nor another channel's verdict.
    with wired(world(verdicts=[_verdict(True, arm_scope="human"),
                               _verdict(True, channel_id="UCother")])):
        assert agent_tick.backlinks_stopped(CH) is False
    # An earlier week's trigger holds even after a later week that didn't.
    with wired(world(verdicts=[_verdict(True, week_start="2026-10-05"), _verdict(False)])):
        assert agent_tick.backlinks_stopped(CH) is True


def test_a_triggered_stop_rule_row_makes_the_real_tick_decline():
    """S1.6b acceptance: stopped triage returns `no_change`, read from lever_verdicts."""
    sb = world(verdicts=[_verdict(True)])
    with wired(sb) as p:
        ap.tick()
    [row] = midas_rows(sb)
    assert row["status"] == "declined" and "stopped" in row["payload"]["rationale"]
    assert row["triage_json"]["context"]["backlinks_stopped"] is True
    assert p["yt"].lists == []


# ── the decision and the intervention link both ways ──────────────────────

def test_triage_json_and_decision_log_intervention_id_link_both_ways():
    sb = world()
    with wired(sb):
        ap.tick()
    [row] = midas_rows(sb)
    [logged] = [r for r in sb.rows("decision_log") if r["subject"] == SRC]
    assert row["triage_json"]["decision_log_id"] == logged["id"]
    assert logged["intervention_id"] == row["id"]
    assert logged["subject"] == SRC and logged["rules_answer"] == row["triage_json"]["answer"]
    assert row["triage_json"]["question_set_version"] == decide.QUESTION_SET_VERSION


# ── next-watch in shadow, per candidate pair (S1.5, #66) ──────────────────

def _pair_rows(sb):
    return [r for r in sb.rows("decision_log") if r["subject"] != SRC]


@pytest.mark.parametrize("holdout_pct, status", [(0.0, "measuring"), (1.0, "holdout")])
def test_next_watch_is_asked_once_per_candidate_pair_and_stored_on_the_intervention(
        holdout_pct, status):
    sb = world()
    with wired(sb, holdout_pct=holdout_pct):
        ap.tick()
    [row] = midas_rows(sb)
    assert row["status"] == status
    pairs = _pair_rows(sb)
    assert [r["subject"] for r in pairs] == [f"{SRC}->{t}" for t in (T1, T2, T3)]
    assert all(r["question_set_version"] == decide.QUESTION_SET_VERSION for r in pairs)
    # The rules answer is used (every candidate is ≥ join_low); the backend's "no" is only logged.
    assert {(r["rules_answer"], r["jev_answer"], r["used"]) for r in pairs} == {("yes", "no", "rules")}
    assert {r["intervention_id"] for r in pairs} == {row["id"]}

    stored = row["triage_json"]["next_watch"]
    assert [s["target_video_id"] for s in stored] == [T1, T2, T3]
    assert [s["decision_log_id"] for s in stored] == [r["id"] for r in pairs]
    assert {s["answer"] for s in stored} == {"yes"}
    assert stored[0]["probs"] == {"yes": 1.0, "no": 0.0}
    assert stored[0]["similarity"] == pytest.approx(1 / (1.01 ** 0.5))


def test_next_watch_asks_every_pair_candidates_returns_not_only_the_targets():
    sb = world()
    with wired(sb) as p:
        ap.settings.BACKLINK_MAX = 2
        ap.tick()
    [row] = midas_rows(sb)
    assert [t["video_id"] for t in row["payload"]["targets"]] == [T1, T2]
    assert [s["target_video_id"] for s in row["triage_json"]["next_watch"]] == [T1, T2, T3]
    assert len(_pair_rows(sb)) == 3
    assert p["yt"].updates


def test_next_watch_is_not_asked_for_a_declined_video():
    sb = world(description=f"{SRC_DESCRIPTION}\nhttps://youtu.be/{OTHER_CH_VIDEO}")
    with wired(sb):
        ap.tick()
    [row] = midas_rows(sb)
    assert row["status"] == "declined"
    assert "next_watch" not in row["triage_json"]
    assert _pair_rows(sb) == []


def test_next_watch_backend_failure_still_logs_every_pair_and_the_tick_goes_on():
    def triage_only(prompt, model=None, system=None, image_urls=None, label=None):
        if label == "decide.next_watch":
            raise RuntimeError("OpenRouter 503")
        return _shadow_says_no_change(prompt, label=label)

    sb = world()
    with wired(sb) as p, patch("app.decide.openrouter.chat_json", triage_only):
        ap.tick()
    assert outcome(p) == "measuring"
    pairs = _pair_rows(sb)
    assert len(pairs) == 3
    assert all(r["jev_answer"] is None and r["rules_answer"] == "yes" for r in pairs)
    assert {s["answer"] for s in midas_rows(sb)[0]["triage_json"]["next_watch"]} == {"yes"}


# ── the preview writes nothing ────────────────────────────────────────────

def _no_llm(*a, **kw):
    raise AssertionError("the preview must not call a decide backend")


@pytest.mark.parametrize("heading", [True, False])
def test_the_preview_writes_nothing_anywhere(heading, capsys):
    sb = world(interventions=[_iv(T4, "declined", "n/a",
                                  created_at=(NOW - timedelta(days=30)).isoformat())])
    before = {name: sb.rows(name) for name in ("interventions", "decision_log", "videos",
                                               "channels")}
    with wired(sb, heading=heading) as p, patch("app.decide.openrouter.chat_json", _no_llm):
        preview_backlinks.main(["--channel", CH, "--n", "20"])
    assert sb.writes == []
    assert {name: sb.rows(name) for name in before} == before
    p["youtube_for_channel"].assert_not_called()
    assert p["yt"].lists == [] and p["yt"].updates == []

    out = capsys.readouterr().out
    if heading:
        assert SRC in out and "answer: backlinks  arm: treated" in out
        assert f"{HEADING}\nRhyme {T1} https://youtu.be/{T1}" in out
    else:
        assert SRC in out and "answer: no_change  arm: -" in out
        assert "render refused: no backlink heading for language 'mr'" in out


def test_the_preview_shows_the_arm_and_the_refusal_per_video():
    sb = world()
    with wired(sb, holdout_pct=1.0):
        [held] = agent_tick.preview(CH, 1)
    assert held["arm"] == "holdout" and held["after"] and not held["refused"]
    with wired(sb, holdout_pct=1.0, heading=False):
        items = agent_tick.preview(CH, 2)
    assert [i["video_id"] for i in items] == [SRC, T1]
    # A block that can't be rendered is declined before the arm is drawn, as in run.
    assert items[0]["answer"] == "no_change" and items[0]["arm"] is None
    assert items[0]["refused"] and "can't be rendered" in items[0]["rationale"]
    assert items[0]["after"] is None and items[0]["before"] == SRC_DESCRIPTION
