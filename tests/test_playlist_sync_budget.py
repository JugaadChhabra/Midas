"""The playlist walk under a quota budget.

Covers the three things that are easy to get wrong and expensive to get wrong:
the plan's ordering, the deferred item_count write (losing a drift signal is
silent), and the mid-walk stop (a partial membership must not look walked).
"""
from unittest.mock import MagicMock, patch

import pytest

import app.playlists_sync as ps
from app.quota import JobBudget


def _budget(units: int, reserve: int = 0) -> JobBudget:
    # units_used_today() is read in __init__; stub it so the fleet-wide arm of
    # can_spend never interferes with the per-run budget under test.
    with patch.object(ps, "settings", ps.settings), \
         patch("app.quota.units_used_today", return_value=0):
        return JobBudget("test", units, reserve=reserve)


# --------------------------------------------------------------------------
# _walk_plan
# --------------------------------------------------------------------------

def test_unchanged_count_is_not_walked():
    yt = [{"id": "p1", "item_count": 10, "title": "p1", "description": ""}]
    existing = {"p1": {"item_count": 10, "membership_walked_at": "2026-08-12T00:00:00+00:00"}}
    assert ps._walk_plan(yt, existing, cutoff="2026-07-13T00:00:00+00:00") == []


def test_changed_count_is_walked():
    yt = [{"id": "p1", "item_count": 11, "title": "p1", "description": ""}]
    existing = {"p1": {"item_count": 10, "membership_walked_at": "2026-08-12T00:00:00+00:00"}}
    plan = ps._walk_plan(yt, existing, cutoff="2026-07-13T00:00:00+00:00")
    assert [(e["id"], e["reason"]) for e in plan] == [("p1", "changed")]


def test_missing_count_is_walked_not_assumed_unchanged():
    """YouTube omitting itemCount is not evidence of no change."""
    yt = [{"id": "p1"}]
    existing = {"p1": {"item_count": 10, "membership_walked_at": "2026-08-12T00:00:00+00:00"}}
    plan = ps._walk_plan(yt, existing, cutoff="2026-07-13T00:00:00+00:00")
    assert [e["reason"] for e in plan] == ["changed"]


def test_stale_walk_rotates_even_when_count_matches():
    """The equal-count swap: same itemCount, drifted membership."""
    yt = [{"id": "p1", "item_count": 10, "title": "p1", "description": ""}]
    existing = {"p1": {"item_count": 10, "membership_walked_at": "2026-01-01T00:00:00+00:00"}}
    plan = ps._walk_plan(yt, existing, cutoff="2026-07-13T00:00:00+00:00")
    assert [e["reason"] for e in plan] == ["rotation"]


def test_rotation_disabled_by_null_cutoff():
    yt = [{"id": "p1", "item_count": 10, "title": "p1", "description": ""}]
    existing = {"p1": {"item_count": 10, "membership_walked_at": "2026-01-01T00:00:00+00:00"}}
    assert ps._walk_plan(yt, existing, cutoff=None) == []


def test_observed_drift_outranks_rotation_and_oldest_goes_first():
    """Ordering IS the budget policy: under a cap that cannot cover the plan,
    known drift must be walked before a mere precaution."""
    yt = [
        {"id": "rot_recent", "item_count": 10},
        {"id": "changed", "item_count": 99},
        {"id": "rot_old", "item_count": 10},
        {"id": "new", "item_count": 3},
    ]
    existing = {
        "rot_recent": {"item_count": 10, "membership_walked_at": "2026-02-01T00:00:00+00:00"},
        "changed": {"item_count": 10, "membership_walked_at": "2026-08-12T00:00:00+00:00"},
        "rot_old": {"item_count": 10, "membership_walked_at": "2026-01-01T00:00:00+00:00"},
    }
    plan = ps._walk_plan(yt, existing, cutoff="2026-07-13T00:00:00+00:00")
    # "new" has no walked_at at all, so it sorts ahead of "changed" within the
    # observed-drift group; both precede either rotation candidate.
    assert [e["id"] for e in plan] == ["new", "changed", "rot_old", "rot_recent"]


# --------------------------------------------------------------------------
# sync_playlists under a budget
# --------------------------------------------------------------------------

def _stub_sync(yt_playlists, existing_rows, pages_by_playlist):
    """Wire sync_playlists' collaborators. Returns (supabase_mock, calls list)."""
    sb = MagicMock()
    tables: dict[str, MagicMock] = {}

    def _table(name):
        return tables.setdefault(name, MagicMock())

    sb.table.side_effect = _table

    _table("playlists").select.return_value.eq.return_value.in_.return_value \
        .execute.return_value.data = existing_rows
    _table("videos").select.return_value.eq.return_value \
        .execute.return_value.data = [{"id": "v1"}]
    _table("playlist_assignments").select.return_value.in_.return_value \
        .execute.return_value.data = []

    pages_fetched: list[str] = []

    def _page(yt, channel_id, playlist_id, page_token):
        pages_fetched.append(playlist_id)
        pages = pages_by_playlist[playlist_id]
        idx = 0 if page_token is None else int(page_token)
        return pages[idx]

    return sb, tables, pages_fetched, _page


def _run(sb, page_fn, yt_playlists, budget, full_walk_days=30):
    with patch.object(ps, "supabase", return_value=sb), \
         patch.object(ps, "youtube_for_channel", return_value=MagicMock()), \
         patch.object(ps, "yt_playlists_list", return_value=yt_playlists), \
         patch.object(ps, "yt_playlist_items_page", side_effect=page_fn), \
         patch.object(ps.settings, "PLAYLIST_FULL_WALK_DAYS", full_walk_days):
        return ps.sync_playlists("chan1", budget=budget)


def _upserted_item_counts(tables) -> dict[str, object]:
    rows = tables["playlists"].upsert.call_args[0][0]
    return {r["id"]: r["item_count"] for r in rows}


def _stamped(tables) -> list[dict]:
    """The (item_count, membership_walked_at) updates for completed walks."""
    return [c[0][0] for c in tables["playlists"].update.call_args_list]


def test_budget_stops_the_pass_and_defers_the_rest():
    yt = [{"id": "p1", "item_count": 1, "title": "p1", "description": ""}, {"id": "p2", "item_count": 1, "title": "p2", "description": ""}]
    existing = [
        {"id": "p1", "item_count": 0, "membership_walked_at": "2026-01-01T00:00:00+00:00"},
        {"id": "p2", "item_count": 0, "membership_walked_at": "2026-02-01T00:00:00+00:00"},
    ]
    pages = {
        "p1": [{"items": [], "nextPageToken": None}],
        "p2": [{"items": [], "nextPageToken": None}],
    }
    sb, tables, fetched, page_fn = _stub_sync(yt, existing, pages)

    result = _run(sb, page_fn, yt, budget=_budget(1))

    # One unit of budget => exactly one playlist walked, the older one first.
    assert fetched == ["p1"]
    assert result["walked"] == 1
    assert result["deferred_over_budget"] == 1


def test_deferred_playlist_keeps_its_stale_item_count():
    """The drift signal must survive the deferral.

    If the upsert wrote YouTube's current count for a playlist we never walked,
    tomorrow's plan would compare equal, call it unchanged, and skip it — the
    change would be lost until rotation, ~30 days later.
    """
    yt = [{"id": "p1", "item_count": 5, "title": "p1", "description": ""}, {"id": "p2", "item_count": 7, "title": "p2", "description": ""}]
    existing = [
        {"id": "p1", "item_count": 4, "membership_walked_at": "2026-01-01T00:00:00+00:00"},
        {"id": "p2", "item_count": 6, "membership_walked_at": "2026-02-01T00:00:00+00:00"},
    ]
    pages = {
        "p1": [{"items": [], "nextPageToken": None}],
        "p2": [{"items": [], "nextPageToken": None}],
    }
    sb, tables, fetched, page_fn = _stub_sync(yt, existing, pages)

    _run(sb, page_fn, yt, budget=_budget(1))

    # Both are in the plan, so the upsert defers BOTH counts...
    assert _upserted_item_counts(tables) == {"p1": 4, "p2": 6}
    # ...and only the completed walk advances its count + resets its clock.
    stamped = _stamped(tables)
    assert len(stamped) == 1
    assert stamped[0]["item_count"] == 5
    assert stamped[0]["membership_walked_at"] is not None


def test_skipped_playlist_still_records_the_current_count():
    """A playlist NOT owed a walk is not deferred — its count is written as usual."""
    yt = [{"id": "p1", "item_count": 10, "title": "p1", "description": ""}]
    existing = [{"id": "p1", "item_count": 10,
                 "membership_walked_at": "2026-08-12T00:00:00+00:00"}]
    sb, tables, fetched, page_fn = _stub_sync(yt, existing, {})

    result = _run(sb, page_fn, yt, budget=_budget(100))

    assert fetched == []
    assert result["skipped_unchanged"] == 1
    assert _upserted_item_counts(tables) == {"p1": 10}
    assert _stamped(tables) == []


def test_mid_walk_stop_does_not_stamp_the_playlist():
    """A partially-read membership must not look walked, or the pages past the
    stop point would never be read."""
    yt = [{"id": "p1", "item_count": 100, "title": "p1", "description": ""}]
    existing = [{"id": "p1", "item_count": 50,
                 "membership_walked_at": "2026-01-01T00:00:00+00:00"}]
    pages = {"p1": [
        {"items": [], "nextPageToken": "1"},
        {"items": [], "nextPageToken": None},
    ]}
    sb, tables, fetched, page_fn = _stub_sync(yt, existing, pages)

    result = _run(sb, page_fn, yt, budget=_budget(1))  # 1 unit, 2 pages needed

    assert len(fetched) == 1                       # stopped after page 1
    assert result["walked"] == 0                   # not counted as walked
    assert _stamped(tables) == []                  # and not stamped
    assert _upserted_item_counts(tables) == {"p1": 50}   # stale count preserved


def test_no_budget_walks_everything():
    """The manual endpoint passes budget=None and keeps the unbounded walk."""
    yt = [{"id": "p1", "item_count": 1, "title": "p1", "description": ""}, {"id": "p2", "item_count": 1, "title": "p2", "description": ""}]
    existing = [
        {"id": "p1", "item_count": 0, "membership_walked_at": None},
        {"id": "p2", "item_count": 0, "membership_walked_at": None},
    ]
    pages = {
        "p1": [{"items": [], "nextPageToken": None}],
        "p2": [{"items": [], "nextPageToken": None}],
    }
    sb, tables, fetched, page_fn = _stub_sync(yt, existing, pages)

    result = _run(sb, page_fn, yt, budget=None)

    assert sorted(fetched) == ["p1", "p2"]
    assert result["walked"] == 2
    assert result["deferred_over_budget"] == 0


# --------------------------------------------------------------------------
# JobBudget
# --------------------------------------------------------------------------

def test_reserve_stops_a_job_that_is_under_its_own_budget():
    """9,000 units already spent: the job has budget left, the fleet does not."""
    with patch("app.quota.units_used_today", return_value=9_000):
        b = JobBudget("t", budget=5_000, reserve=1_500)
        assert b.remaining == 5_000        # own budget untouched
        assert not b.can_spend(1)          # 10000 - 300 - 1500 - 9000 < 0


def test_reserve_leaves_room_for_applies():
    """A job with a budget larger than the whole day still stops at the reserve.

    The meter tracks the job's own spend here, as it does in production —
    youtube_client._log_quota writes a quota_log row per call, so
    units_used_today() already includes whatever this job has spent.
    """
    used = {"n": 0}
    with patch("app.quota.units_used_today", side_effect=lambda: used["n"]):
        b = JobBudget("t", budget=10_000, reserve=1_500)
        spendable = 0
        while b.can_spend(1):
            b.note(1)
            used["n"] += 1
            spendable += 1
        assert spendable == 10_000 - 300 - 1_500   # 8,200


def test_live_meter_is_rechecked_mid_run():
    """Concurrent spend by another job is seen within _RECHECK_EVERY units."""
    used = {"n": 0}
    with patch("app.quota.units_used_today", side_effect=lambda: used["n"]):
        b = JobBudget("t", budget=10_000, reserve=0)
        for _ in range(JobBudget._RECHECK_EVERY):
            assert b.can_spend(1)
            b.note(1)
        used["n"] = 9_800          # something else drained the day
        assert not b.can_spend(1)
