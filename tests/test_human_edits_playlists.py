"""Phase B · B3b (#34): the human-edit ledger, playlist memberships.

When the playlist membership walk sees one of our videos newly in one of our
playlists, and Midas didn't put it there, that's one `human` playlist
intervention. These tests drive the real sync_playlists and the real ledger
against FakeSupabase; only YouTube is faked.
"""
from unittest.mock import MagicMock, patch

from app import human_edits as he
from app import interventions as iv
from app import playlists_sync as ps
from tests.fakes import FakeSupabase

CH = "UCchan"
PL = "PLours"
WALKED = "2026-10-01T02:00:00+00:00"


def _playlist(*, walked_at=WALKED, item_count=1, origin="inherited"):
    return {"id": PL, "channel_id": CH, "title": "Rhymes", "description": "",
            "origin": origin, "role": "inherited", "item_count": item_count,
            "membership_walked_at": walked_at}


def _sync_row(video_id):
    return {"video_id": video_id, "playlist_id": PL, "playlist_item_id": f"item-{video_id}",
            "action": "added", "decision_source": "sync", "decided_at": WALKED}


def _sb(*, playlists=None, assignments=(), proposals=(), interventions=()):
    return FakeSupabase({
        "playlists": [_playlist()] if playlists is None else playlists,
        "videos": [{"id": v, "channel_id": CH} for v in ("v1", "v2", "v3")],
        "playlist_assignments": list(assignments),
        "playlist_proposals": list(proposals),
        "interventions": list(interventions),
    })


def _walk(sb, members):
    """One sync_playlists pass, YouTube showing `members` in PL."""
    yt_playlists = [{"id": PL, "title": "Rhymes", "description": "", "item_count": len(members)}]
    page = {"items": [{"id": f"item-{v}", "contentDetails": {"videoId": v}} for v in members],
            "nextPageToken": None}
    with patch.object(ps, "supabase", return_value=sb), \
         patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb), \
         patch.object(ps, "youtube_for_channel", return_value=MagicMock()), \
         patch.object(ps, "yt_playlists_list", return_value=yt_playlists), \
         patch.object(ps, "yt_playlist_items_page", return_value=page):
        return ps.sync_playlists(CH)


def _human(sb):
    return [r for r in sb.rows("interventions") if r["origin"] == "human"]


def test_a_new_human_membership_is_recorded_once():
    sb = _sb(assignments=[_sync_row("v1")])
    _walk(sb, ["v1", "v2"])

    [row] = _human(sb)
    assert row["video_id"] == "v2"
    assert row["channel_id"] == CH
    assert row["lever"] == "playlist"
    assert row["arm"] == "n/a"
    assert row["status"] == "applied"
    assert row["detected_at"] and row["applied_at"] is None
    assert row["payload"]["playlist_id"] == PL
    assert row["payload"]["video_id"] == "v2"
    assert row["payload"]["playlist_item_id"] == "item-v2"
    assert "detected_at is when" in row["payload"]["timing"]
    assert row["ledger_key"] == f"playlist:{PL}:v2:item-v2"
    # The walk still seeds its own membership row, as before B3b.
    assert ("v2", "sync") in {(a["video_id"], a["decision_source"])
                              for a in sb.rows("playlist_assignments")}


def test_reruns_are_idempotent():
    sb = _sb(assignments=[_sync_row("v1")])
    _walk(sb, ["v1", "v2"])
    _walk(sb, ["v1", "v2"])
    assert len(_human(sb)) == 1


def test_the_ledger_itself_is_idempotent_when_the_walk_rereads_a_membership():
    """The ledger writes before the walk seeds its row: if that seed fails, the
    next walk sees the same membership again, and the ledger key dedupes it."""
    sb = _sb()
    with patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb):
        first = he.record_playlist_additions(CH, PL, [("v2", "item-v2")])
        second = he.record_playlist_additions(CH, PL, [("v2", "item-v2")])
    assert (first, second) == (1, 0)
    assert len(_human(sb)) == 1


def test_a_re_add_after_removal_is_a_new_membership_to_the_ledger():
    """The ledger's contract only: today's walk never hands it a re-add, since
    it keeps any assignment row for the pair and doesn't see removals."""
    sb = _sb()
    with patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb):
        he.record_playlist_additions(CH, PL, [("v2", "item-v2")])
        he.record_playlist_additions(CH, PL, [("v2", "item-v2-again")])
    assert len(_human(sb)) == 2


def test_a_membership_midas_added_by_assignment_is_not_recorded():
    midas = {**_sync_row("v2"), "decision_source": "embedding"}
    sb = _sb(assignments=[_sync_row("v1"), midas])
    _walk(sb, ["v1", "v2"])
    assert _human(sb) == []

    # And the ledger's own check, for a membership the walk hands it.
    with patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb):
        assert he.record_playlist_additions(CH, PL, [("v2", "item-v2")]) == 0
    assert _human(sb) == []


def test_a_membership_from_an_executed_proposal_is_not_recorded():
    """An approved 'add' proposal executed through Midas, even if its
    assignment row is missing (the decide route writes it after the insert)."""
    sb = _sb(assignments=[_sync_row("v1")], proposals=[
        {"id": 1, "video_id": "v2", "playlist_id": PL, "action": "add",
         "decision_source": "embedding", "status": "approved"},
    ])
    _walk(sb, ["v1", "v2"])
    assert _human(sb) == []


def test_a_proposal_that_was_not_executed_does_not_make_it_midas():
    sb = _sb(assignments=[_sync_row("v1")], proposals=[
        {"id": 1, "video_id": "v2", "playlist_id": PL, "action": "add",
         "decision_source": "embedding", "status": "pending"},
        {"id": 2, "video_id": "v2", "playlist_id": PL, "action": "add",
         "decision_source": "embedding", "status": "rejected"},
        {"id": 3, "video_id": "v2", "playlist_id": PL, "action": "remove",
         "decision_source": "llm_confirmed", "status": "approved"},
    ])
    _walk(sb, ["v1", "v2"])
    assert [r["video_id"] for r in _human(sb)] == ["v2"]


def test_a_midas_removal_does_not_make_a_later_add_midas():
    """The ledger's contract only (see the re-add test above)."""
    removed = {**_sync_row("v2"), "action": "removed", "decision_source": "llm_confirmed"}
    sb = _sb(assignments=[removed])
    with patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb):
        assert he.record_playlist_additions(CH, PL, [("v2", "item-v2b")]) == 1


def test_a_discovery_created_playlist_is_judged_by_its_assignments_not_its_origin():
    """playlist_discovery stores the playlists it creates as origin='inherited'.
    Its members are Midas's (decision_source='discovery'); a video the team adds
    later is human. Neither verdict comes from `origin`."""
    discovered = [{**_sync_row(v), "decision_source": "discovery"} for v in ("v1", "v2")]
    sb = _sb(playlists=[_playlist(origin="inherited", item_count=2)], assignments=discovered)
    _walk(sb, ["v1", "v2", "v3"])
    assert [r["video_id"] for r in _human(sb)] == ["v3"]

    with patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb):
        assert he.record_playlist_additions(CH, PL, [("v1", "item-v1")]) == 0


def test_the_first_walk_of_a_playlist_records_a_baseline_not_interventions():
    sb = _sb(playlists=[_playlist(walked_at=None, item_count=None)])
    result = _walk(sb, ["v1", "v2"])

    assert _human(sb) == []
    assert result["memberships_seeded"] == 2
    assert sb.rows("playlists")[0]["membership_walked_at"] is not None

    # From the baseline on, a new membership counts.
    _walk(sb, ["v1", "v2", "v3"])
    assert [r["video_id"] for r in _human(sb)] == ["v3"]


def test_a_playlist_new_to_the_db_is_a_baseline_too():
    sb = _sb(playlists=[])
    _walk(sb, ["v1", "v2"])
    assert _human(sb) == []
    assert len(sb.rows("playlist_assignments")) == 2


def test_a_ledger_error_never_fails_the_walk(caplog):
    sb = FakeSupabase({
        "playlists": [_playlist()],
        "videos": [{"id": v, "channel_id": CH} for v in ("v1", "v2")],
        "playlist_assignments": [_sync_row("v1")],
        # No playlist_proposals / interventions: every ledger query raises.
    })
    result = _walk(sb, ["v1", "v2"])

    assert result["walked"] == 1
    assert result["memberships_seeded"] == 1
    assert "human-edit ledger failed; walk continues" in caplog.text
