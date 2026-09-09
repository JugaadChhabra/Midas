"""The playlist-join threshold tuner lives with the playlist engine.

`tune_thresholds` nudges `PLAYLIST_JOIN_HIGH` from the churn of the
`playlist_assignments` log — a playlist concern. It used to sit in
`reflection` and ride the weekly reflection tick, which conflated it with
CTR-driven prompt reflection; it now belongs to `app.playlists` (the engine
that reads the threshold) and is driven by its own weekly scheduler job.
"""
import inspect

import pytest
from unittest.mock import patch, MagicMock


def test_tune_thresholds_nudges_up_on_high_fpr():
    """FPR > 20%: join_high should increase by 0.01."""
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(10)] +
        [{"action": "removed"} for _ in range(3)]  # 30% FPR
    )
    stored = []
    with patch("app.playlists.supabase") as mock_sb, \
         patch("app.playlists.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.72
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                def capture(row):
                    stored.append(row)
                    inner = MagicMock()
                    inner.execute.return_value = None
                    return inner
                m.insert.side_effect = capture
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.playlists import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] == pytest.approx(0.73, abs=0.001)
    assert result["fpr"] == pytest.approx(0.30, abs=0.01)


def test_tune_thresholds_nudges_down_on_low_fpr():
    """FPR < 5%: join_high should decrease by 0.01."""
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(20)] +
        [{"action": "removed"} for _ in range(0)]  # 0% FPR
    )
    stored = []
    with patch("app.playlists.supabase") as mock_sb, \
         patch("app.playlists.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.72
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                def capture(row):
                    stored.append(row)
                    inner = MagicMock()
                    inner.execute.return_value = None
                    return inner
                m.insert.side_effect = capture
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.playlists import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] == pytest.approx(0.71, abs=0.001)


def test_tune_thresholds_respects_upper_bound():
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(10)] +
        [{"action": "removed"} for _ in range(4)]  # 40% FPR
    )
    with patch("app.playlists.supabase") as mock_sb, \
         patch("app.playlists.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.84  # one nudge would exceed 0.85
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                m.insert.return_value.execute.return_value = None
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.playlists import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] <= 0.85


def test_reflection_no_longer_owns_the_tuner():
    """The tuner was evicted from the CTR-reflection domain.

    Guards the locality win: reflection must neither define nor call
    tune_thresholds — its weekly tick no longer drives playlist tuning.
    """
    from app import reflection

    assert not hasattr(reflection, "tune_thresholds")
    assert "tune_thresholds" not in inspect.getsource(reflection._reflect_inner)


def test_scheduler_drives_the_tuner_on_its_own_job():
    """main wires tune_thresholds to a dedicated weekly job, not reflection's."""
    from app import main

    src = inspect.getsource(main._weekly_playlist_tuning)
    assert "tune_thresholds(" in src
