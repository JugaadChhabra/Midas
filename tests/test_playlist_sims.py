"""Tier 3′ RPC 1 — playlist centroid scoring via pgvector.

Unit tests for the RPC-vs-fallback dispatch in _sims_for_video / _sims_matrix.
The live parity guard (RPC output == in-app centroid math on real data) lives in
tests/test_playlist_sims_parity_live.py.
"""
from unittest.mock import MagicMock, patch

from app import playlists


def _rpc_sb(rows):
    """supabase() whose .rpc(...).execute().data returns `rows`."""
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = rows
    return sb


def test_sims_for_video_rpc_shapes_by_playlist():
    rows = [
        {"playlist_id": "PL1", "video_id": "v1", "sim": 0.9},
        {"playlist_id": "PL2", "video_id": "v1", "sim": 0.4},
    ]
    with patch.object(playlists.settings, "PLAYLIST_SIMS_USE_RPC", True), \
         patch.object(playlists, "supabase", return_value=_rpc_sb(rows)), \
         patch.object(playlists, "_has_pooled_embedding", return_value=True):
        out = playlists._sims_for_video("c1", "v1", [])
    assert out == {"PL1": 0.9, "PL2": 0.4}


def test_sims_for_video_rpc_none_when_no_embedding():
    with patch.object(playlists.settings, "PLAYLIST_SIMS_USE_RPC", True), \
         patch.object(playlists, "supabase", return_value=_rpc_sb([])), \
         patch.object(playlists, "_has_pooled_embedding", return_value=False):
        out = playlists._sims_for_video("c1", "vX", [])
    assert out is None


def test_sims_for_video_falls_back_when_rpc_errors():
    """RPC raising must transparently use the in-app centroid path."""
    sb = MagicMock()
    sb.rpc.return_value.execute.side_effect = RuntimeError("function missing")
    pls = [{"id": "PL1"}]
    with patch.object(playlists.settings, "PLAYLIST_SIMS_USE_RPC", True), \
         patch.object(playlists, "supabase", return_value=sb), \
         patch.object(playlists, "_get_embedding", return_value=[1.0, 0.0]), \
         patch.object(playlists, "_current_members", return_value={"m1": "item1"}), \
         patch.object(playlists, "_centroid", return_value=[1.0, 0.0]), \
         patch.object(playlists, "_cosine_sim", return_value=0.77):
        out = playlists._sims_for_video("c1", "v1", pls)
    assert out == {"PL1": 0.77}


def test_sims_matrix_rpc_builds_pair_keyed_dict_and_centroid_set():
    rows = [
        {"playlist_id": "PL1", "video_id": "v1", "sim": 0.8},
        {"playlist_id": "PL1", "video_id": "v2", "sim": 0.3},
        {"playlist_id": "PL2", "video_id": "v1", "sim": 0.6},
    ]
    with patch.object(playlists.settings, "PLAYLIST_SIMS_USE_RPC", True), \
         patch.object(playlists, "supabase", return_value=_rpc_sb(rows)):
        sims, centroid_pids = playlists._sims_matrix("c1", [{"id": "PL1"}, {"id": "PL2"}],
                                                     ["v1", "v2"])
    assert sims == {("PL1", "v1"): 0.8, ("PL1", "v2"): 0.3, ("PL2", "v1"): 0.6}
    assert centroid_pids == {"PL1", "PL2"}


def test_sims_matrix_fallback_matches_inapp_math():
    """Flag off => in-app centroids; only embedded videos get a sim, only
    playlists with a centroid appear."""
    emb_rows = [{"video_id": "v1", "embedding": "[1,0]"}]  # v2 has no embedding
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.eq.return_value.eq.return_value.execute.return_value.data = emb_rows
    with patch.object(playlists.settings, "PLAYLIST_SIMS_USE_RPC", False), \
         patch.object(playlists, "supabase", return_value=sb), \
         patch.object(playlists, "_parse_embedding", side_effect=lambda r: [1.0, 0.0]), \
         patch.object(playlists, "_current_members", return_value={"v1": "item1"}), \
         patch.object(playlists, "_centroid", side_effect=lambda ids: [1.0, 0.0] if ids else None), \
         patch.object(playlists, "_cosine_sim", return_value=0.5):
        sims, centroid_pids = playlists._sims_matrix("c1", [{"id": "PL1"}], ["v1", "v2"])
    assert sims == {("PL1", "v1"): 0.5}   # v2 (no embedding) absent
    assert centroid_pids == {"PL1"}
