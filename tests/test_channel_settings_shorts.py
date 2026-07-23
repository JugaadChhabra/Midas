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
    body = {"autopilot_shorts_enabled": True, "shorts_cut_mode": "coverage",
            "shorts_camera_motion": "follow"}
    with patch("app.auth.supabase", return_value=_sb(rec)):
        r = _client().patch("/auth/channels/UC1", json=body)
    assert r.status_code == 200
    p = rec[0]
    assert p["autopilot_shorts_enabled"] is True
    assert p["shorts_cut_mode"] == "coverage"
    assert p["shorts_camera_motion"] == "follow"


def test_patch_rejects_bad_enums():
    rec = []
    # A valid field so the patch is non-empty (else the endpoint no-ops without
    # touching the DB); the bogus enums must be dropped from what gets written.
    body = {"autopilot_shorts_enabled": True,
            "shorts_cut_mode": "bogus", "shorts_camera_motion": "bogus"}
    with patch("app.auth.supabase", return_value=_sb(rec)):
        r = _client().patch("/auth/channels/UC1", json=body)
    assert r.status_code == 200
    p = rec[0]
    assert p["autopilot_shorts_enabled"] is True
    assert "shorts_cut_mode" not in p                  # invalid enum ignored
    assert "shorts_camera_motion" not in p


def test_patch_sets_valid_nas_folder():
    rec = []
    with patch("app.auth.supabase", return_value=_sb(rec)), \
         patch("app.auth.list_source_languages", return_value=["HINDI", "TAMIL"]):
        r = _client().patch("/auth/channels/UC1", json={"nas_folder": "hindi"})
    assert r.status_code == 200
    assert rec[0]["nas_folder"] == "HINDI"          # uppercased


def test_patch_rejects_unknown_nas_folder():
    rec = []
    with patch("app.auth.supabase", return_value=_sb(rec)), \
         patch("app.auth.list_source_languages", return_value=["HINDI"]):
        r = _client().patch("/auth/channels/UC1", json={"nas_folder": "KLINGON"})
    assert r.status_code == 400


def test_patch_clears_nas_folder_on_empty():
    rec = []
    with patch("app.auth.supabase", return_value=_sb(rec)), \
         patch("app.auth.list_source_languages", return_value=["HINDI"]):
        r = _client().patch("/auth/channels/UC1", json={"nas_folder": ""})
    assert r.status_code == 200
    assert rec[0]["nas_folder"] is None
