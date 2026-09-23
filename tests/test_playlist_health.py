"""playlist_health.score_channel end to end against the in-memory client.

The scorer had no test, which is how the rows refactor (b355f40) could delete
its METRIC_ROW_PAGE constant and leave the daily job raising NameError on every
channel with playlists — reported by APScheduler as "executed successfully".
"""
from unittest.mock import patch

from app import playlist_health
from tests.fakes import FakeSupabase


def _metric(pid, end, starts, vps, atip, rid):
    return {
        "id": rid, "playlist_id": pid, "window_start": end, "window_end": end,
        "playlist_starts": starts, "views_per_playlist_start": vps,
        "avg_time_in_playlist_sec": atip,
    }


def test_score_channel_scores_and_gates():
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=3)).isoformat()
    sb = FakeSupabase({
        "playlists": [
            {"id": "pA", "channel_id": "c1", "title": "A"},
            {"id": "pB", "channel_id": "c1", "title": "B"},
            {"id": "pC", "channel_id": "c1", "title": "C"},
        ],
        "playlist_metrics": [
            _metric("pA", recent, 100, 2.0, 300, 1),
            _metric("pB", recent, 80, 1.0, 100, 2),
            _metric("pC", recent, 5, 1.0, 100, 3),  # under MIN_PLAYLIST_STARTS
        ],
        "video_traffic_source_playlist": [],
    })
    with patch.object(playlist_health, "supabase", return_value=sb):
        summary = playlist_health.score_channel("c1")

    assert summary["playlists_total"] == 3
    assert summary["gated_in"] == 2
    assert summary["insufficient_data"] == 1
    rows = {r["id"]: r for r in sb._tables["playlists"]}
    assert rows["pC"]["health_recommendation"] == "insufficient_data"
    assert rows["pA"]["health_score"] == 600.0
    assert rows["pB"]["health_score"] == 100.0
