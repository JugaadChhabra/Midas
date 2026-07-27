"""Egress fix — the autopilot audit picker via next_audit_candidate() RPC.

Unit tests for the RPC/in-app dispatch. The live parity guard (RPC pick ==
in-app pick on real data) is in tests/test_autopilot_picker_parity_live.py.
"""
from unittest.mock import MagicMock, patch

import app.autopilot as ap


def _rpc_sb(rows):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = rows
    return sb


def test_picker_rpc_returns_single_row():
    row = {"id": "vid1", "is_short": False, "privacy_status": "public"}
    with patch.object(ap.settings, "AUTOPILOT_PICKER_USE_RPC", True), \
         patch.object(ap, "supabase", return_value=_rpc_sb([row])):
        out = ap._next_video_for_channel("UC1")
    assert out == row


def test_picker_rpc_returns_none_when_empty():
    with patch.object(ap.settings, "AUTOPILOT_PICKER_USE_RPC", True), \
         patch.object(ap, "supabase", return_value=_rpc_sb([])):
        out = ap._next_video_for_channel("UC1")
    assert out is None


def test_picker_falls_back_to_inapp_when_rpc_errors():
    """RPC raising must transparently use the in-app scan (which returns the
    newest eligible unaudited public video)."""
    sb = MagicMock()
    sb.rpc.return_value.execute.side_effect = RuntimeError("no function")
    # in-app path: videos scan, then audits scan
    videos = [
        {"id": "new", "is_short": False, "privacy_status": "public"},
        {"id": "old", "is_short": False, "privacy_status": "public"},
    ]
    sb.table.return_value.select.return_value.eq.return_value.order.return_value \
        .order.return_value.execute.return_value.data = videos
    sb.table.return_value.select.return_value.in_.return_value.order.return_value \
        .execute.return_value.data = [
            {"video_id": "new", "status": "applied", "created_at": "2026-01-02"},  # blocked
        ]
    with patch.object(ap.settings, "AUTOPILOT_PICKER_USE_RPC", True), \
         patch.object(ap, "supabase", return_value=sb):
        out = ap._next_video_for_channel("UC1")
    assert out["id"] == "old"  # 'new' is applied -> skip, 'old' is eligible


def test_inapp_path_used_when_flag_off():
    videos = [{"id": "v", "is_short": False, "privacy_status": "public"}]
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value \
        .order.return_value.execute.return_value.data = videos
    sb.table.return_value.select.return_value.in_.return_value.order.return_value \
        .execute.return_value.data = []  # no audits -> eligible
    with patch.object(ap.settings, "AUTOPILOT_PICKER_USE_RPC", False), \
         patch.object(ap, "supabase", return_value=sb):
        out = ap._next_video_for_channel("UC1")
    assert out["id"] == "v"
    sb.rpc.assert_not_called()  # flag off => never touches the RPC
