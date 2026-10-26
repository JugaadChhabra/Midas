"""Phase B · B4 — the warm filter (spec Part 2 §2.1, Part 3 B4; #35).

The in-app path runs against the FakeSupabase double; the SQL twin is checked
against it on a real Postgres in test_warm_pool_parity.py.
"""
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app import warm
from tests.fakes import FakeSupabase

REPO = Path(__file__).resolve().parents[1]
FRONTIER = date(2026, 10, 4)
CH = "c1"


def day(n: int) -> str:
    """The data-day n days before the frontier."""
    return (FRONTIER - timedelta(days=n)).isoformat()


def ledger(days, channel=CH, report_type="channel_reach_basic_a1"):
    return [{"report_id": f"{channel}-{report_type}-{d}", "channel_id": channel,
             "data_date": d, "report_type": report_type} for d in days]


def reach(video_id, impressions, d=None, channel=CH):
    return {"video_id": video_id, "channel_id": channel, "date": d or day(0),
            "impressions": impressions, "ctr": 0.05}


def video(video_id, privacy="public", is_episode=None, channel=CH):
    return {"id": video_id, "channel_id": channel, "privacy_status": privacy,
            "is_episode": is_episode}


def ago(days: float) -> str:
    """A created_at `days` before now, as PostgREST returns a timestamptz."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def intervention(video_id, origin="midas", status="applied", *, lever="title", arm=None,
                 age_days=365, applied=None):
    """Old and off the backlinks experiment by default, so only `status` matters."""
    return {"video_id": video_id, "channel_id": CH, "lever": lever,
            "origin": origin, "arm": arm or ("treated" if origin == "midas" else "n/a"),
            "status": status, "created_at": ago(age_days),
            "applied_at": ago(age_days) if applied else None}


#: 28 contiguous covered days: certified (21-day window behind the frontier).
CERTIFIED = ledger([day(n) for n in range(28)])


def sb_for(*, ledger_rows=CERTIFIED, reach_rows=(), videos=(), interventions=()):
    rows = list(reach_rows)
    for i, r in enumerate(rows, 1):
        r.setdefault("id", i)
    for i, r in enumerate(interventions, 1):
        r.setdefault("id", i)
    return FakeSupabase({
        "reporting_reports_ingested": list(ledger_rows),
        "video_reach_daily": rows,
        "videos": list(videos),
        "interventions": list(interventions),
    })


def pool_ids(sb, channel=CH):
    with patch.object(warm, "supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch.object(warm.settings, "WARM_POOL_USE_RPC", False):
        return [r["id"] for r in warm.ranked_pool(channel)]


# ── eligibility ───────────────────────────────────────────────────────────

def test_dormant_episode_private_and_in_intervention_videos_are_excluded():
    sb = sb_for(
        reach_rows=[reach("warm", 1000), reach("dormant", 100), reach("episode", 1000),
                    reach("private", 1000), reach("unlisted", 1000),
                    reach("in_intervention", 1000), reach("in_holdout", 1000)],
        videos=[video("warm"), video("dormant"), video("episode", is_episode=True),
                video("private", privacy="private"), video("unlisted", privacy="unlisted"),
                video("in_intervention"), video("in_holdout")],
        interventions=[intervention("in_intervention", status="applied"),
                       intervention("in_holdout", status="holdout")],
    )
    assert pool_ids(sb) == ["warm"]


def test_closed_midas_and_any_human_intervention_do_not_exclude():
    """Past the cooldown and off the backlinks experiment, only an open Midas
    intervention holds a video (§1.6, as active_for). A human row never closes,
    so counting it would bar every video the team edited."""
    sb = sb_for(
        reach_rows=[reach("judged", 1000), reach("declined", 1000), reach("human", 1000)],
        videos=[video("judged"), video("declined"), video("human")],
        interventions=[intervention("judged", status="judged"),
                       intervention("declined", status="declined"),
                       intervention("human", origin="human", status="applied")],
    )
    assert sorted(pool_ids(sb)) == ["declined", "human", "judged"]


# ── S1.4a: the agent's exclusions (Part 4 S1.4 "Pick", finding 2) ────────

def test_the_cooldown_excludes_any_recent_midas_row_and_keeps_an_older_one():
    """A `no_change` is a declined row, not active: without the cooldown the
    same top video is offered again on the next tick."""
    cooldown = warm.settings.TRIAGE_COOLDOWN_DAYS
    recent = {"declined": "declined", "holdout": "holdout", "planned": "planned",
              "cancelled": "cancelled", "judged": "judged"}
    sb = sb_for(
        reach_rows=[reach(v, 1000) for v in [*recent, "declined_long_ago", "fresh"]],
        videos=[video(v) for v in [*recent, "declined_long_ago", "fresh"]],
        interventions=[
            *(intervention(v, status=s, lever="title", age_days=1) for v, s in recent.items()),
            # The video's last Midas row is older than the cooldown.
            intervention("declined_long_ago", status="declined", age_days=cooldown + 1),
            intervention("declined_long_ago", status="judged", age_days=cooldown + 30),
        ],
    )
    assert pool_ids(sb) == ["declined_long_ago", "fresh"]


def test_the_cooldown_is_triage_cooldown_days():
    sb = sb_for(reach_rows=[reach("v", 1000)], videos=[video("v")],
                interventions=[intervention("v", status="declined", age_days=3)])
    with patch.object(warm.settings, "TRIAGE_COOLDOWN_DAYS", 2):
        assert pool_ids(sb) == ["v"]
    with patch.object(warm.settings, "TRIAGE_COOLDOWN_DAYS", 4):
        assert pool_ids(sb) == []


def test_a_midas_backlinks_row_of_either_arm_excludes_for_good():
    """Each video is in the backlinks experiment once, at any age; a human
    backlinks row (the B3a ledger) and other levers' old rows don't count."""
    sb = sb_for(
        reach_rows=[reach(v, 1000) for v in ("treated", "held_out", "human", "old_playlist")],
        videos=[video(v) for v in ("treated", "held_out", "human", "old_playlist")],
        interventions=[
            intervention("treated", status="judged", lever="backlinks", arm="treated",
                         age_days=400, applied=True),
            intervention("held_out", status="judged", lever="backlinks", arm="holdout",
                         age_days=400),
            intervention("human", origin="human", status="applied", lever="backlinks",
                         age_days=1),
            intervention("old_playlist", status="judged", lever="playlist", arm="treated",
                         age_days=400),
        ],
    )
    assert pool_ids(sb) == ["human", "old_playlist"]


def test_unclassified_privacy_and_episode_count_as_eligible():
    """NULL privacy_status / is_episode mean not yet known, as in next_audit_candidate."""
    sb = sb_for(reach_rows=[reach("v", 900)], videos=[video("v", privacy=None, is_episode=None)])
    assert pool_ids(sb) == ["v"]


def test_the_impression_floor_is_inclusive_and_sums_across_days():
    sb = sb_for(
        reach_rows=[reach("exact", 250, day(0)), reach("exact", 250, day(5)),
                    reach("short", 499, day(0))],
        videos=[video("exact"), video("short")],
    )
    assert pool_ids(sb) == ["exact"]


def test_a_video_not_in_videos_or_on_another_channel_is_not_in_the_pool():
    sb = sb_for(
        reach_rows=[reach("unsynced", 1000), reach("elsewhere", 1000, channel="c2")],
        videos=[video("elsewhere", channel="c2")],
    )
    assert pool_ids(sb) == []


def test_an_uncertified_channel_has_an_empty_pool():
    """reach.certify's question: the window ending at the frontier must be fully covered."""
    gap = ledger([day(n) for n in range(28) if n != 10])
    sb = sb_for(ledger_rows=gap, reach_rows=[reach("v", 5000)], videos=[video("v")])
    assert pool_ids(sb) == []


def test_a_never_polled_channel_has_an_empty_pool():
    sb = sb_for(ledger_rows=[], reach_rows=[reach("v", 5000)], videos=[video("v")])
    assert pool_ids(sb) == []


# ── the window: ingested data-days, not calendar days ─────────────────────

def test_the_window_counts_ingested_data_days_not_calendar_days():
    """Covered: the 21 days up to the frontier, then a 10-day hole, then 8 more.

    The latest 28 INGESTED days reach back past the hole to day 37; day 38 is
    the 29th. 28 calendar days would stop at day 27 and see neither."""
    covered = [day(n) for n in range(21)] + [day(n) for n in range(31, 39)]
    sb = sb_for(
        ledger_rows=ledger(covered),
        reach_rows=[reach("behind_the_hole", 600, day(37)),
                    reach("29th_day", 600, day(38))],
        videos=[video("behind_the_hole"), video("29th_day")],
    )
    assert pool_ids(sb) == ["behind_the_hole"]


def test_traffic_reports_in_the_ledger_are_not_ingested_reach_days():
    """The ledger also holds B1's traffic reports; only reach makes a day ingested."""
    traffic = ledger([day(n) for n in range(28, 40)], report_type="channel_traffic_source_a3")
    sb = sb_for(ledger_rows=CERTIFIED + traffic,
                reach_rows=[reach("v", 600, day(30))], videos=[video("v")])
    assert pool_ids(sb) == []


def test_the_window_length_is_warm_window_days():
    sb = sb_for(reach_rows=[reach("v", 600, day(10))], videos=[video("v")])
    with patch.object(warm.settings, "WARM_WINDOW_DAYS", 10):
        assert pool_ids(sb) == []
    with patch.object(warm.settings, "WARM_WINDOW_DAYS", 11):
        assert pool_ids(sb) == ["v"]


# ── order and the explore share ───────────────────────────────────────────

def test_the_pool_is_ordered_by_impressions_then_id():
    sb = sb_for(
        reach_rows=[reach("b", 700), reach("a", 700), reach("top", 900, day(1)),
                    reach("top", 100, day(2)), reach("low", 600)],
        videos=[video("a"), video("b"), video("top"), video("low")],
    )
    with patch.object(warm, "supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb):
        pool = warm.ranked_pool(CH)
    assert pool == [{"id": "top", "impressions": 1000}, {"id": "a", "impressions": 700},
                    {"id": "b", "impressions": 700}, {"id": "low", "impressions": 600}]


RANKED = [{"id": f"v{i:04d}", "impressions": 10_000 - i} for i in range(2000)]


def test_the_explore_share_is_about_warm_explore_pct():
    for seed in range(5):
        order = warm.explore_order(RANKED, 0.10, random.Random(seed))
        share = sum(r["explore"] for r in order) / len(order)
        assert 0.08 <= share <= 0.12, (seed, share)


def test_explore_picks_come_from_the_rest_of_the_pool_and_lose_nobody():
    order = warm.explore_order(RANKED, 0.10, random.Random(1))
    assert sorted(r["id"] for r in order) == [r["id"] for r in RANKED]
    remaining = list(RANKED)
    for pick in order:
        top = remaining[0]["id"]
        # A non-explore pick is the best remaining; an explore pick never is.
        assert (pick["id"] == top) is (not pick["explore"])
        remaining = [r for r in remaining if r["id"] != pick["id"]]


def test_without_exploration_the_order_is_the_ranking():
    order = warm.explore_order(RANKED[:50], 0.0, random.Random(0))
    assert [r["id"] for r in order] == [r["id"] for r in RANKED[:50]]
    assert not any(r["explore"] for r in order)


def test_a_seed_makes_the_order_reproducible_and_the_input_is_untouched():
    before = [dict(r) for r in RANKED[:100]]
    a = warm.explore_order(RANKED[:100], 0.5, random.Random(42))
    b = warm.explore_order(RANKED[:100], 0.5, random.Random(42))
    assert a == b
    assert RANKED[:100] == before


def test_warm_pool_applies_the_explore_share_over_the_ranking():
    sb = sb_for(reach_rows=[reach(f"v{i}", 1000 + i) for i in range(20)],
                videos=[video(f"v{i}") for i in range(20)])
    with patch.object(warm, "supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch.object(warm.settings, "WARM_EXPLORE_PCT", 0.0):
        pool = warm.warm_pool(CH, rng=random.Random(0))
    assert [r["id"] for r in pool] == [f"v{i}" for i in range(19, -1, -1)]


def test_the_pick_leaves_out_shorts_and_keeps_unprobed_videos():
    """A backlink block on a Short isn't clickable. ranked_pool (the SQL twin)
    keeps them; warm_pool, the pick, drops them. NULL is_short stays in."""
    vids = [video("long"), {**video("short"), "is_short": True}, {**video("unprobed"), "is_short": None}]
    sb = sb_for(reach_rows=[reach("long", 900), reach("short", 5000), reach("unprobed", 700)],
                videos=vids)
    with patch.object(warm, "supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch.object(warm.settings, "WARM_POOL_USE_RPC", False):
        ranked = [r["id"] for r in warm.ranked_pool(CH)]
        picked = [r["id"] for r in warm.warm_pool(CH, rng=random.Random(0))
                  if not r["explore"]]
        everything = {r["id"] for r in warm.warm_pool(CH, rng=random.Random(0))}
    assert ranked == ["short", "long", "unprobed"]
    assert everything == {"long", "unprobed"} and "short" not in picked


def test_the_rpc_pick_leaves_out_shorts_too():
    rows = [{"id": "short", "impressions": 5000}, {"id": "long", "impressions": 900}]
    sb = FakeSupabase({"videos": [{**video("short"), "is_short": True}, video("long")]},
                      rpc={"warm_pool": rows})
    with patch.object(warm, "supabase", return_value=sb), \
         patch.object(warm.settings, "WARM_POOL_USE_RPC", True), \
         patch.object(warm.settings, "WARM_EXPLORE_PCT", 0.0):
        assert [r["id"] for r in warm.warm_pool(CH)] == ["long"]


# ── the RPC path ──────────────────────────────────────────────────────────

def test_rpc_path_pages_the_function_and_passes_the_settings():
    rows = [{"id": f"v{i:04d}", "impressions": 5000 - i} for i in range(1500)]
    sb = FakeSupabase(rpc={"warm_pool": rows})
    with patch.object(warm, "supabase", return_value=sb), \
         patch.object(warm.settings, "WARM_POOL_USE_RPC", True):
        pool = warm.ranked_pool(CH)
    assert pool == rows                       # past PostgREST's 1000-row cap
    name, params = sb.rpc_calls[0]
    assert name == "warm_pool"
    assert params == {
        "p_channel_id": CH,
        "p_min_impressions": warm.settings.WARM_MIN_IMPRESSIONS,
        "p_window_days": warm.settings.WARM_WINDOW_DAYS,
        "p_measurement_window_days": warm.reach.window_length(),
        "p_cooldown_days": warm.settings.TRIAGE_COOLDOWN_DAYS,
    }


def test_rpc_failure_falls_back_to_the_in_app_pool():
    sb = sb_for(reach_rows=[reach("v", 900)], videos=[video("v")])   # rpc unstubbed: raises
    with patch.object(warm, "supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch.object(warm.settings, "WARM_POOL_USE_RPC", True):
        assert [r["id"] for r in warm.ranked_pool(CH)] == ["v"]
    assert [name for name, _ in sb.rpc_calls] == ["warm_pool"]


def test_flag_off_never_touches_the_rpc():
    sb = sb_for(reach_rows=[reach("v", 900)], videos=[video("v")])
    pool_ids(sb)
    assert sb.rpc_calls == []


# ── wired only through the agent tick (S1.4b) ─────────────────────────────

def test_the_audit_tick_never_picks_from_the_warm_pool():
    autopilot = (REPO / "app/autopilot.py").read_text()
    # Not a bare "warm": autopilot may well mention channels.reach_warmup. The
    # agent path picks through app/agent_tick.py, never the audit path.
    assert not re.search(r"\bwarm\b|warm_pool|ranked_pool|explore_order", autopilot), (
        "the audit path must not pick from the warm filter")


def test_only_the_agent_tick_picks_and_s1_1_candidates_use_only_the_warmth_measure():
    """S1.4b's agent tick picks from the pool (`warm_pool`, with its explore
    share); S1.1's candidates read only `warm_impressions` for their targets,
    and so do S2.1's playlist-test candidates (app/playlist_test.py) and S2.4's
    Short-link targets (app/short_links.py)."""
    users = sorted(
        p.relative_to(REPO).as_posix()
        for p in (REPO / "app").rglob("*.py")
        if p.name != "warm.py"
        and re.search(r"\bapp\.warm\b|from app import[^\n]*\bwarm\b|[\"']warm_pool[\"']",
                      p.read_text())
    )
    assert users == ["app/agent_tick.py", "app/backlinks.py", "app/playlist_test.py",
                     "app/short_links.py"], users
    for path in ("app/backlinks.py", "app/playlist_test.py", "app/short_links.py"):
        src = (REPO / path).read_text()
        assert not re.search(r"warm\.(ranked_pool|warm_pool|explore_order)\b", src), path
    agent = (REPO / "app/agent_tick.py").read_text()
    assert re.search(r"warm\.warm_pool\(", agent)
    assert not re.search(r"warm\.(ranked_pool|explore_order)\b", agent)


def test_the_sql_counts_the_same_report_type_as_reach_coverage():
    from app.reporting_client import REACH_REPORT_TYPE_ID
    sql = (REPO / "supabase/migrations/20261023000000_warm_pool_agent_exclusions.sql").read_text()
    assert re.findall(r"report_type = '([^']+)'", sql) == [REACH_REPORT_TYPE_ID]


def test_a_treated_backlinks_row_that_never_reached_youtube_doesnt_use_up_the_video():
    """Slice 1 review (2026-10-23): a treated row cancelled before its write
    (kill switch, DRY_RUN, a refused render, a YouTube error) has no applied_at.
    The video never got a block, so past the cooldown it is back in the pool;
    otherwise every failed tick would burn a video for good."""
    sb = sb_for(
        reach_rows=[reach(v, 1000) for v in ("never_sent", "sent", "recent_fail")],
        videos=[video(v) for v in ("never_sent", "sent", "recent_fail")],
        interventions=[
            intervention("never_sent", status="cancelled", lever="backlinks", arm="treated",
                         age_days=30),
            intervention("sent", status="cancelled", lever="backlinks", arm="treated",
                         age_days=30, applied=True),     # applied, then reverted
            intervention("recent_fail", status="cancelled", lever="backlinks", arm="treated",
                         age_days=1),                    # still in the cooldown
        ],
    )
    assert pool_ids(sb) == ["never_sent"]
