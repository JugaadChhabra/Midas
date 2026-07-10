from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _sb(recorder):
    sb = MagicMock()
    def _update(patch_dict):
        recorder.append(patch_dict)
        u = MagicMock()
        u.eq.return_value.execute.return_value.data = [{}]
        return u
    sb.table.return_value.update.side_effect = _update
    return sb


def test_patch_persists_shorts_autopilot_settings():
    rec = []
    body = {"autopilot_shorts_enabled": True, "autopilot_shorts_daily_cap": 3,
            "autopilot_shorts_upload_cap": 2, "shorts_cut_mode": "coverage",
            "shorts_camera_motion": "follow"}
    with patch("app.auth.supabase", return_value=_sb(rec)):
        r = _client().patch("/auth/channels/UC1", json=body)
    assert r.status_code == 200
    p = rec[0]
    assert p["autopilot_shorts_enabled"] is True
    assert p["autopilot_shorts_daily_cap"] == 3
    assert p["autopilot_shorts_upload_cap"] == 2
    assert p["shorts_cut_mode"] == "coverage"
    assert p["shorts_camera_motion"] == "follow"


def test_patch_clamps_and_rejects_bad_enums():
    rec = []
    body = {"autopilot_shorts_daily_cap": 999, "autopilot_shorts_upload_cap": 0,
            "shorts_cut_mode": "bogus", "shorts_camera_motion": "bogus"}
    with patch("app.auth.supabase", return_value=_sb(rec)):
        r = _client().patch("/auth/channels/UC1", json=body)
    assert r.status_code == 200
    p = rec[0]
    assert p["autopilot_shorts_daily_cap"] == 20      # clamped to max
    assert p["autopilot_shorts_upload_cap"] == 1       # clamped to min
    assert "shorts_cut_mode" not in p                  # invalid enum ignored
    assert "shorts_camera_motion" not in p
