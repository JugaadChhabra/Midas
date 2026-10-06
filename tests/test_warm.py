"""Phase B · B4 — the warm filter (spec Part 2 §2.1, Part 3 B4; #35).

The in-app path runs against the FakeSupabase double; the SQL twin is checked
against it on a real Postgres in test_warm_pool_parity.py.
"""
import random
import re
from datetime import date, timedelta
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


def intervention(video_id, origin="midas", status="applied"):
    return {"video_id": video_id, "channel_id": CH, "lever": "backlinks",
            "origin": origin, "arm": "treated" if origin == "midas" else "n/a",
            "status": status}


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
    """Only an open Midas intervention holds a video (§1.6, as active_for). A
    human row never closes, so counting it would bar every video the team edited."""
    sb = sb_for(
        reach_rows=[reach("judged", 1000), reach("declined", 1000), reach("human", 1000)],
        videos=[video("judged"), video("declined"), video("human")],
        interventions=[intervention("judged", status="judged"),
                       intervention("declined", status="declined"),
                       intervention("human", origin="human", status="applied")],
    )
    assert sorted(pool_ids(sb)) == ["declined", "human", "judged"]


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
        "p_measurement_window_days": warm.settings.MEASUREMENT_WINDOW_DAYS,
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


# ── not wired into the tick (Slice 1 does that) ───────────────────────────

def test_the_warm_filter_is_not_called_from_the_tick():
    autopilot = (REPO / "app/autopilot.py").read_text()
    assert "warm" not in autopilot.lower(), "Phase B must not wire the warm filter into the tick"


def test_nothing_in_the_app_uses_the_warm_filter_yet():
    users = [
        p.relative_to(REPO).as_posix()
        for p in (REPO / "app").rglob("*.py")
        if p.name != "warm.py"
        and re.search(r"\bapp\.warm\b|from app import[^\n]*\bwarm\b|[\"']warm_pool[\"']",
                      p.read_text())
    ]
    assert users == [], f"wired before Slice 1: {users}"


def test_the_sql_counts_the_same_report_type_as_reach_coverage():
    from app.reporting_client import REACH_REPORT_TYPE_ID
    sql = (REPO / "supabase/migrations/20261006040000_warm_pool_rpc.sql").read_text()
    assert re.findall(r"report_type = '([^']+)'", sql) == [REACH_REPORT_TYPE_ID]
