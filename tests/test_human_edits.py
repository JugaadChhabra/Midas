"""Phase B · B3a (#33): the human-edit ledger, description links.

When a sync re-reads a description, a link to one of our videos that the SEO
team added becomes one `human` backlinks intervention. These tests drive the
real ledger and the real sync_channel against FakeSupabase; only YouTube is
faked.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import human_edits as he
from app import interventions as iv
from app import sync
from tests.fakes import FakeSupabase

SRC = "srcVideo001"        # the video whose description changes
OURS_A = "ourVideoAAA"     # 11-character ids of videos in `videos`
OURS_B = "ourVideoBBB"
OURS_C = "ourVideoCCC"
CH = "UCchan"


def _url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def _videos(*extra):
    return [{"id": v, "channel_id": CH} for v in (SRC, OURS_A, OURS_B, OURS_C, *extra)]


def _sb(*, interventions=(), audits=(), videos=None):
    return FakeSupabase({
        "videos": videos if videos is not None else _videos(),
        "audits": list(audits),
        "interventions": list(interventions),
    })


def _run(sb, before, after, video_id=SRC):
    with patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb):
        return he.record_description_edits(CH, [(video_id, before, after)])


# ── link extraction ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    f"watch https://www.youtube.com/watch?v={OURS_A} now",
    f"https://youtube.com/watch?feature=share&v={OURS_A}",
    f"https://m.youtube.com/watch?v={OURS_A}&list=PLxyz",
    f"https://youtu.be/{OURS_A}?si=abc",
    f"youtube.com/shorts/{OURS_A}",
    f"https://www.youtube.com/embed/{OURS_A}",
    f"https://www.youtube.com/live/{OURS_A}",
    f"(https://youtu.be/{OURS_A})",
])
def test_link_forms_are_extracted(text):
    assert he.video_links(text) == {OURS_A}


@pytest.mark.parametrize("text", [
    "https://youtu.be/tooShort1",                      # 9 characters
    "https://www.youtube.com/watch?v=twelveCharsX1",   # 12: not a video id
    "https://www.youtube.com/playlist?list=PLabcdefghijk",
    "https://www.youtube.com/@channelhandle",
    "https://example.com/watch?v=ourVideoAAA",         # not YouTube
    "",
    None,
])
def test_non_video_links_are_ignored(text):
    assert he.video_links(text) == set()


# ── the ledger ───────────────────────────────────────────────────────────

def test_an_added_link_creates_exactly_one_intervention():
    sb = _sb()
    n = _run(sb, "Rhyme lyrics", f"Rhyme lyrics\nWatch next: {_url(OURS_A)} and {_url(OURS_A)}")
    rows = sb.rows("interventions")
    assert n == 1 and len(rows) == 1
    row = rows[0]
    assert (row["video_id"], row["channel_id"]) == (SRC, CH)
    assert (row["origin"], row["lever"], row["arm"], row["status"]) == \
        ("human", "backlinks", "n/a", "applied")
    assert row["detected_at"] and row["applied_at"] is None
    assert row["payload"]["source_video_id"] == SRC
    assert row["payload"]["target_video_id"] == OURS_A
    # Detection timing is said in the row: detected_at is not the edit time.
    assert "FULL_SYNC_INTERVAL" in row["payload"]["timing"]
    assert row["ledger_key"]


def test_each_added_link_is_its_own_intervention():
    sb = _sb()
    _run(sb, "", f"{_url(OURS_A)} {_url(OURS_B)}")
    assert sorted(r["payload"]["target_video_id"] for r in sb.rows("interventions")) == \
        [OURS_A, OURS_B]


def test_an_unchanged_description_creates_none():
    desc = f"Lyrics\n{_url(OURS_A)}"
    sb = _sb()
    assert _run(sb, desc, desc) == 0
    assert sb.rows("interventions") == []


def test_an_edit_that_keeps_the_same_links_creates_none():
    sb = _sb()
    assert _run(sb, f"Old intro {_url(OURS_A)}", f"New intro {_url(OURS_A)}") == 0
    assert sb.rows("interventions") == []


def test_a_removed_link_is_in_the_payload_with_no_intervention_for_it():
    """The team swapped A for B: one intervention (for B), carrying A as removed."""
    sb = _sb()
    _run(sb, f"Next: {_url(OURS_A)}", f"Next: {_url(OURS_B)}")
    rows = sb.rows("interventions")
    assert len(rows) == 1
    assert rows[0]["payload"]["target_video_id"] == OURS_B
    assert rows[0]["payload"]["removed_targets"] == [OURS_A]


def test_a_removal_marks_the_links_earlier_intervention():
    sb = _sb()
    _run(sb, "", f"Next: {_url(OURS_A)}")
    assert _run(sb, f"Next: {_url(OURS_A)}", "Next: nothing") == 0
    rows = sb.rows("interventions")
    assert len(rows) == 1                               # no intervention for a removal
    assert rows[0]["payload"]["removed_detected_at"]


def test_a_pure_removal_with_no_earlier_row_creates_none():
    sb = _sb()
    assert _run(sb, f"Next: {_url(OURS_A)}", "Next: nothing") == 0
    assert sb.rows("interventions") == []
    assert [w for w in sb.writes if w[0] == "interventions"] == []


def test_a_midas_apply_creates_none():
    after = f"House-format description {_url(OURS_A)}"
    sb = _sb(audits=[{"id": 9, "video_id": SRC, "status": "applied",
                      "applied_at": "2026-09-20T00:00:00+00:00",
                      "suggested_description": after, "description_before": "old"}])
    assert _run(sb, "old", after) == 0
    assert sb.rows("interventions") == []


def test_a_midas_revert_creates_none():
    """A revert restores description_before: that write was Midas's too."""
    restored = f"The team's original {_url(OURS_A)}"
    sb = _sb(audits=[{"id": 9, "video_id": SRC, "status": "reverted",
                      "applied_at": "2026-09-20T00:00:00+00:00",
                      "suggested_description": "house format", "description_before": restored}])
    assert _run(sb, "house format", restored) == 0


def test_a_midas_match_ignores_whitespace_differences():
    after = f"Line one\r\n\r\nWatch {_url(OURS_A)}  "
    sb = _sb(audits=[{"id": 9, "video_id": SRC, "status": "applied",
                      "applied_at": "2026-09-20T00:00:00+00:00",
                      "suggested_description": f"Line one\n\nWatch {_url(OURS_A)}",
                      "description_before": ""}])
    assert _run(sb, "", after) == 0


def test_an_unapplied_audit_does_not_make_it_a_midas_change():
    after = f"Suggested but never applied {_url(OURS_A)}"
    sb = _sb(audits=[{"id": 9, "video_id": SRC, "status": "pending", "applied_at": None,
                      "suggested_description": after, "description_before": None}])
    assert _run(sb, "", after) == 1


def test_a_human_edit_on_a_video_midas_once_changed_is_recorded():
    sb = _sb(audits=[{"id": 9, "video_id": SRC, "status": "applied",
                      "applied_at": "2026-09-20T00:00:00+00:00",
                      "suggested_description": "house format", "description_before": "old"}])
    assert _run(sb, "house format", f"house format\n{_url(OURS_A)}") == 1


def test_detection_is_idempotent_across_reruns():
    """The same edit seen again (a rerun, a racing sync, or a sync whose videos
    upsert failed after the ledger wrote) does not add a second row."""
    sb = _sb()
    before, after = "Lyrics", f"Lyrics {_url(OURS_A)}"
    assert _run(sb, before, after) == 1
    assert _run(sb, before, after) == 0
    assert len(sb.rows("interventions")) == 1


def test_the_next_sync_after_detection_creates_none():
    sb = _sb()
    after = f"Lyrics {_url(OURS_A)}"
    _run(sb, "Lyrics", after)
    assert _run(sb, after, after) == 0                  # stored description now has it
    assert len(sb.rows("interventions")) == 1


def test_links_to_videos_that_are_not_ours_are_ignored():
    sb = _sb()
    after = (f"{_url('notOursXYZ1')} https://youtu.be/ExampleURL3 "
             f"https://youtu.be/tooShort1 {_url('twelveCharsX1')}")
    assert _run(sb, "", after) == 0
    assert sb.rows("interventions") == []


def test_ours_means_any_channel_in_the_fleet():
    """Sibling channels route traffic into each other (P2): a link to another
    channel's video in `videos` counts."""
    sb = _sb(videos=_videos() + [{"id": "siblingVid1", "channel_id": "UCother"}])
    assert _run(sb, "", _url("siblingVid1")) == 1


def test_a_link_to_the_video_itself_is_ignored():
    sb = _sb()
    assert _run(sb, "", _url(SRC)) == 0


def test_one_bad_video_does_not_stop_the_others(caplog):
    sb = _sb()
    real_record = iv.record

    def flaky(**kw):
        if kw["video_id"] == SRC:
            raise RuntimeError("boom")
        return real_record(**kw)

    with patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb), \
         patch.object(he.interventions, "record", side_effect=flaky):
        n = he.record_description_edits(CH, [
            (SRC, "", _url(OURS_A)),
            (OURS_C, "", _url(OURS_B)),
        ])
    assert n == 1
    assert [r["video_id"] for r in sb.rows("interventions")] == [OURS_C]
    assert "boom" in caplog.text


# ── wired into sync ──────────────────────────────────────────────────────

def _item(vid: str, description: str) -> dict:
    return {
        "id": vid,
        "snippet": {"title": f"t-{vid}", "description": description, "tags": [],
                    "categoryId": "22", "publishedAt": "2026-01-01T00:00:00Z"},
        "statistics": {"viewCount": "1", "likeCount": "0", "commentCount": "0"},
        "contentDetails": {"duration": "PT5M"},
        "status": {"privacyStatus": "public"},
    }


def _sync_sb(stored_description: str):
    return FakeSupabase({
        "channels": [{"id": CH, "default_language": "mr", "sync_shorts": True}],
        "videos": [
            {"id": SRC, "channel_id": CH, "is_short": False, "description": stored_description},
            {"id": OURS_A, "channel_id": CH, "is_short": False, "description": ""},
        ],
        "audits": [],
        "interventions": [],
    })


def _sync(sb, youtube_description: str, *, full: bool = True):
    with patch.object(sync, "supabase", return_value=sb), \
         patch.object(he, "supabase", return_value=sb), \
         patch.object(iv, "supabase", return_value=sb), \
         patch.object(sync, "youtube_for_channel", return_value=MagicMock()), \
         patch.object(sync, "yt_channels_list_uploads",
                      return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch.object(sync, "yt_playlist_items_page",
                      return_value={"items": [{"contentDetails": {"videoId": v}}
                                              for v in (SRC, OURS_A)]}), \
         patch.object(sync, "yt_videos_list_full",
                      side_effect=lambda yt, cid, ids: [
                          _item(v, youtube_description if v == SRC else "") for v in ids]):
        return sync.sync_channel(CH, full=full)


def test_full_sync_records_a_link_the_team_added():
    sb = _sync_sb("Lyrics")
    _sync(sb, f"Lyrics\n{_url(OURS_A)}")
    rows = sb.rows("interventions")
    assert [(r["video_id"], r["payload"]["target_video_id"]) for r in rows] == [(SRC, OURS_A)]
    stored = {v["id"]: v["description"] for v in sb.rows("videos")}
    assert stored[SRC] == f"Lyrics\n{_url(OURS_A)}"


def test_rerunning_the_full_sync_does_not_duplicate():
    sb = _sync_sb("Lyrics")
    _sync(sb, f"Lyrics\n{_url(OURS_A)}")
    _sync(sb, f"Lyrics\n{_url(OURS_A)}")
    assert len(sb.rows("interventions")) == 1


def test_a_ledger_error_never_fails_the_sync(caplog):
    sb = _sync_sb("Lyrics")
    with patch.object(he.interventions, "record", side_effect=RuntimeError("ledger down")), \
         patch.object(he, "_our_videos", side_effect=RuntimeError("db down")):
        result = _sync(sb, f"Lyrics\n{_url(OURS_A)}")
    assert result == {"synced": 2}
    stored = {v["id"]: v["description"] for v in sb.rows("videos")}
    assert stored[SRC] == f"Lyrics\n{_url(OURS_A)}"      # the sync still wrote
    assert "db down" in caplog.text


def test_incremental_sync_reads_no_stored_descriptions():
    """Only a full sync re-reads old videos; the incremental one never fetches
    them, so it has nothing to diff and shouldn't pull every description."""
    sb = _sync_sb("Lyrics")
    with patch.object(he, "record_description_edits") as ledger:
        _sync(sb, f"Lyrics\n{_url(OURS_A)}", full=False)
    ledger.assert_not_called()
