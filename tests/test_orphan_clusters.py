"""Tier 3′ RPC 2 — orphan clustering via pgvector.

Unit tests for the RPC/in-app dispatch + row grouping. The live parity guard
(RPC partition == in-app partition on real data) is in
tests/test_orphan_clusters_parity_live.py.
"""
from unittest.mock import MagicMock, patch

from app import playlist_discovery as pd


def test_rpc_cluster_orphans_groups_rows_by_cluster_id():
    rows = [
        {"video_id": "a", "cluster_id": 1},
        {"video_id": "b", "cluster_id": 1},
        {"video_id": "c", "cluster_id": 2},
    ]
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = rows
    with patch.object(pd, "supabase", return_value=sb):
        clusters = pd._rpc_cluster_orphans("c1", ["a", "b", "c"])
    assert clusters == [["a", "b"], ["c"]]  # ordered by cluster_id


def test_dispatch_uses_rpc_when_flag_on():
    with patch.object(pd.settings, "PLAYLIST_DISCOVERY_USE_RPC", True), \
         patch.object(pd, "_rpc_cluster_orphans", return_value=[["a", "b"]]) as rpc, \
         patch.object(pd, "_cluster_orphans_inapp") as inapp:
        out = pd._cluster_orphans_for_channel("c1", ["a", "b"])
    assert out == [["a", "b"]]
    rpc.assert_called_once()
    inapp.assert_not_called()


def test_dispatch_uses_inapp_when_flag_off():
    with patch.object(pd.settings, "PLAYLIST_DISCOVERY_USE_RPC", False), \
         patch.object(pd, "_rpc_cluster_orphans") as rpc, \
         patch.object(pd, "_cluster_orphans_inapp", return_value=[["x"]]) as inapp:
        out = pd._cluster_orphans_for_channel("c1", ["x"])
    assert out == [["x"]]
    inapp.assert_called_once()
    rpc.assert_not_called()


def test_dispatch_falls_back_to_inapp_when_rpc_errors():
    with patch.object(pd.settings, "PLAYLIST_DISCOVERY_USE_RPC", True), \
         patch.object(pd, "_rpc_cluster_orphans", side_effect=RuntimeError("no function")), \
         patch.object(pd, "_cluster_orphans_inapp", return_value=[["y", "z"]]) as inapp:
        out = pd._cluster_orphans_for_channel("c1", ["y", "z"])
    assert out == [["y", "z"]]
    inapp.assert_called_once()


def test_cluster_orphans_is_deterministic_and_order_independent():
    """sorted() pinning => same clusters regardless of input order."""
    # two tight groups in 2-D (cosine): near-x and near-y axis
    emb = {
        "v1": [1.0, 0.02], "v2": [1.0, 0.01], "v3": [0.99, 0.03], "v4": [1.0, 0.0],
        "w1": [0.02, 1.0], "w2": [0.0, 1.0], "w3": [0.03, 0.99], "w4": [0.01, 1.0],
    }
    ids = list(emb)
    with patch.object(pd, "MIN_CLUSTER_SIZE", 4), \
         patch.object(pd, "CLUSTER_SIM_THRESHOLD", 0.9):
        a = pd._cluster_orphans(ids, emb)
        b = pd._cluster_orphans(list(reversed(ids)), emb)
    part = lambda cs: {frozenset(c) for c in cs}
    assert part(a) == part(b)
    assert part(a) == {frozenset({"v1", "v2", "v3", "v4"}), frozenset({"w1", "w2", "w3", "w4"})}
