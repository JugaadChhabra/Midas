"""An audit with no apply-time baseline reports no delta — not the whole view count.

The apply path used to spend a YouTube round trip capturing view/like/comment
counts at apply time, so `view_count_at_apply` was always populated and
`view_count_now - view_count_at_apply` was a real "since we changed it" delta.
That collection is gone.

Both readers coalesced the missing baseline to zero (`a.get(...) or 0`), which
turns the subtraction into `view_count_now - 0` — the video's ENTIRE lifetime view
count, presented as growth attributable to the audit. The percentage columns were
already safe (`_pct` returns None when base <= 0), so the corruption showed up
only in the raw deltas, and on the dashboard it silently inflated the fleet-wide
`delta_views_7d` by the full lifetime views of every newly-applied video.

Absent and zero have to stay distinguishable: a brand-new video can legitimately
have had 0 views at apply, and that row's delta IS meaningful. So the test is
`is None`, never falsiness.

Rows applied before this change keep their stored baselines and their deltas.
"""
from __future__ import annotations

from unittest.mock import patch

from app import performance


def _audit(aid, *, view_at, applied_at="2026-07-01T00:00:00+00:00"):
    """view_at=None models a post-change apply; a number models a historical one."""
    return {
        "id": aid, "video_id": f"v{aid}", "status": "applied",
        "applied_at": applied_at, "created_at": applied_at,
        "suggested_title": "new", "title_before": "old",
        "suggested_description": "d2", "description_before": "d1",
        "suggested_tags": ["b"], "tags_before": ["a"],
        "view_count_at_apply": view_at,
        "like_count_at_apply": None if view_at is None else 10,
        "comment_count_at_apply": None if view_at is None else 1,
        "measurement_status": None, "measurement_result": {},
        "ai_reasoning": "why",
    }


def _rows(audits):
    videos = [{"id": a["video_id"], "channel_id": "ch1", "title": "t",
               "thumbnail_url": None, "view_count": 50_000,
               "like_count": 900, "comment_count": 40,
               "last_fetched_at": None,
               "published_at": "2026-01-01T00:00:00+00:00"}
              for a in audits]
    with patch.object(performance, "audits_for_channel"), \
         patch.object(performance, "fetch_all", return_value=audits), \
         patch.object(performance, "supabase") as sb:
        sb.return_value.table.return_value.select.return_value.in_.return_value \
            .execute.return_value.data = videos
        return performance._build_rows("ch1", None)


def test_missing_baseline_reports_no_delta():
    """Not 50,000. The audit did not earn those views; nobody measured."""
    row = _rows([_audit(1, view_at=None)])[0]
    assert row["view_count_at_apply"] is None
    assert row["delta_views"] is None
    assert row["delta_likes"] is None
    assert row["delta_comments"] is None
    assert row["pct_views"] is None


def test_a_stored_baseline_still_produces_a_delta():
    """Historical rows are unaffected — they have real baselines."""
    row = _rows([_audit(1, view_at=1_000)])[0]
    assert row["view_count_at_apply"] == 1_000
    assert row["delta_views"] == 49_000


def test_a_genuine_zero_baseline_is_not_treated_as_missing():
    """A video with 0 views at apply is measured, and its delta is real. This is
    why the check is `is None` and not falsiness."""
    row = _rows([_audit(1, view_at=0)])[0]
    assert row["view_count_at_apply"] == 0
    assert row["delta_views"] == 50_000


def test_dashboard_excludes_unmeasured_audits_from_the_fleet_delta():
    """The 7-day fleet delta must skip unmeasured audits rather than add their
    lifetime views — one applied video could otherwise dwarf the real signal."""
    from app import dashboard

    assert dashboard._delta_views_7d(
        audits=[{"video_id": "v1", "view_count_at_apply": 1_000},
                {"video_id": "v2", "view_count_at_apply": None}],
        current_views={"v1": 1_500, "v2": 90_000},
    ) == 500
