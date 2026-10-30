"""S3.6 (spec Part 6, F13): a manual house-format apply on an agent channel.

The house-format apply sends the whole snippet, so on a channel with live
backlinks it replaces the description and the block in it. The manual routes
refuse there with 409 unless `?force=true`; on any other channel they work as
before. Through the endpoints, with the DB and YouTube faked at the edge.
"""
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import audits, main
from tests.fakes import FakeSupabase

CH = "UC1"
REFUSED = ("agent channel: a house-format apply replaces the description and its "
           "backlink block; pass force=true")


def _db(*, agent_enabled):
    return FakeSupabase({
        "channels": [{"id": CH, "default_language": "en", "measurement_enabled": False,
                      "agent_enabled": agent_enabled}],
        "videos": [{"id": "vid1", "channel_id": CH, "title": "old",
                    "description": "old desc", "tags": []}],
        "audits": [{"id": 7, "status": "pending", "video_id": "vid1",
                    "videos.channel_id": CH, "created_at": "2026-10-30T00:00:00+00:00",
                    "suggested_title": "new title", "suggested_description": "new desc",
                    "suggested_tags": ["a"]}],
    })


@contextmanager
def _edges(sb):
    with patch("app.audits.supabase", return_value=sb), \
         patch("app.channel_audits.supabase", return_value=sb), \
         patch.object(audits.settings, "DRY_RUN", False), \
         patch("app.audits.youtube_for_channel"), \
         patch("app.audits.yt_videos_update") as update, \
         patch("app.quota.can_afford", return_value=True) as afford:
        yield {"update": update, "afford": afford}


def _client():
    return TestClient(main.app, raise_server_exceptions=False)


def _status(sb):
    return sb.rows("audits")[0]["status"]


# ── POST /audits/{id}/apply ─────────────────────────────────────────────────

def test_a_manual_apply_on_an_agent_channel_is_409_and_sends_nothing():
    sb = _db(agent_enabled=True)
    with _edges(sb) as p:
        r = _client().post("/audits/7/apply")
    assert r.status_code == 409
    assert r.json()["detail"] == REFUSED
    p["update"].assert_not_called()
    assert _status(sb) == "pending"
    assert sb.writes == []


def test_a_manual_apply_on_an_agent_channel_goes_through_with_force():
    sb = _db(agent_enabled=True)
    with _edges(sb) as p:
        r = _client().post("/audits/7/apply?force=true")
    assert r.status_code == 200, r.text
    p["update"].assert_called_once()
    assert _status(sb) == "applied"


def test_a_manual_apply_on_another_channel_is_unchanged():
    for agent_enabled in (False, None):
        sb = _db(agent_enabled=agent_enabled)
        with _edges(sb) as p:
            r = _client().post("/audits/7/apply")
        assert r.status_code == 200, r.text
        p["update"].assert_called_once()
        assert _status(sb) == "applied"


# ── POST /channels/{id}/audits/apply-pending ────────────────────────────────

def test_apply_pending_on_an_agent_channel_is_409_before_any_apply():
    sb = _db(agent_enabled=True)
    with _edges(sb) as p:
        r = _client().post(f"/channels/{CH}/audits/apply-pending")
    assert r.status_code == 409
    assert r.json()["detail"] == REFUSED
    p["afford"].assert_not_called()
    p["update"].assert_not_called()
    assert sb.writes == []


def test_apply_pending_on_an_agent_channel_goes_through_with_force():
    sb = _db(agent_enabled=True)
    with _edges(sb) as p:
        r = _client().post(f"/channels/{CH}/audits/apply-pending?force=true")
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 1
    p["update"].assert_called_once()
    assert _status(sb) == "applied"


def test_apply_pending_on_an_unknown_channel_answers_as_before():
    sb = _db(agent_enabled=True)
    with _edges(sb) as p:
        r = _client().post("/channels/UCnobody/audits/apply-pending")
    assert r.status_code == 200, r.text
    assert r.json()["total_pending"] == 0
    p["update"].assert_not_called()


def test_apply_pending_on_another_channel_is_unchanged():
    sb = _db(agent_enabled=False)
    with _edges(sb) as p:
        r = _client().post(f"/channels/{CH}/audits/apply-pending")
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 1
    p["update"].assert_called_once()


# ── a suggest-only audit is unguarded ───────────────────────────────────────

def test_a_suggest_only_audit_is_not_guarded():
    """POST /videos/{id}/audit writes no YouTube field, so it stays open: it
    reads no channel flag and goes straight to audit_video."""
    with patch("app.audits.audit_video", return_value={"id": 8}) as audit:
        r = _client().post("/videos/vid1/audit")
    assert r.status_code == 200, r.text
    audit.assert_called_once_with("vid1")


# ── POST /audits/{id}/revert ────────────────────────────────────────────────

REVERT_REFUSED = ("agent channel: an audit revert replaces the description and its "
                  "backlink block; pass force=true")


def _applied(sb):
    sb._tables["audits"][0].update({"status": "applied", "title_before": "older",
                                    "description_before": "older desc", "tags_before": []})
    return sb


def test_an_audit_revert_on_an_agent_channel_is_409_and_sends_nothing():
    sb = _applied(_db(agent_enabled=True))
    with _edges(sb) as p:
        r = _client().post("/audits/7/revert")
    assert r.status_code == 409
    assert r.json()["detail"] == REVERT_REFUSED
    p["update"].assert_not_called()
    assert _status(sb) == "applied"


def test_an_audit_revert_on_an_agent_channel_goes_through_with_force():
    sb = _applied(_db(agent_enabled=True))
    with _edges(sb) as p:
        r = _client().post("/audits/7/revert?force=true")
    assert r.status_code == 200, r.text
    p["update"].assert_called_once()
    assert _status(sb) == "reverted"


def test_an_audit_revert_on_another_channel_is_unchanged():
    sb = _applied(_db(agent_enabled=False))
    with _edges(sb) as p:
        r = _client().post("/audits/7/revert")
    assert r.status_code == 200, r.text
    p["update"].assert_called_once()
