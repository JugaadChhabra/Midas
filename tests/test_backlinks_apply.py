"""Slice 1 · S1.3 (#64): the description-only backlinks write, its revert, and
the ledger recognising Midas's own block.

These drive the real apply/revert, the real yt_* helpers, the real quota gate
and the real human-edit ledger against FakeSupabase; only the YouTube client is
faked, and it records every update body it is sent.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import backlinks, backlinks_apply as ba, human_edits as he
from app import interventions as iv, main, quota, sync
from app.apply_outcome import ApplyError, ApplyOutcome
from tests.fakes import FakeSupabase

CH = "UCmarathi1"
SRC = "srcVideo001"
T1, T2 = "tgtVideo001", "tgtVideo002"
HUMAN = "humanLink01"
HEADING = "Watch next"

LIVE = "Twinkle twinkle\nLyrics and more\n#rhymes"
SNIPPET = {
    "title": "Live title",
    "description": LIVE,
    "tags": ["live", "tags"],
    "categoryId": "27",
    "defaultLanguage": "mr",
    "defaultAudioLanguage": "mr",
    "channelId": CH,
    "publishedAt": "2026-01-01T00:00:00Z",
}
TARGETS = [{"video_id": T1, "title": "Rhyme one"}, {"video_id": T2, "title": "Rhyme two"}]


def _rendered(description=LIVE):
    with patch.dict(backlinks.HEADINGS, {"mr": HEADING}):
        return backlinks.render(description, TARGETS, "mr")


class _Request:
    def __init__(self, respond):
        self._respond = respond

    def execute(self):
        return self._respond()


class FakeYouTube:
    """videos.list answers from `snippets`; videos.update records (part, body)
    and makes the new snippet the live one. `fail` makes update raise."""

    def __init__(self, snippets: dict[str, dict], fail: Exception | None = None):
        self.snippets = {k: dict(v) for k, v in snippets.items()}
        self.fail = fail
        self.lists: list[dict] = []
        self.updates: list[tuple[str, dict]] = []

    def videos(self):
        yt = self

        class _Videos:
            def list(self, **kw):
                def go():
                    yt.lists.append(kw)
                    return {"items": [{"id": v, "snippet": dict(yt.snippets[v])}
                                      for v in kw["id"].split(",") if v in yt.snippets]}
                return _Request(go)

            def update(self, part, body):
                def go():
                    if yt.fail is not None:
                        raise yt.fail
                    yt.updates.append((part, body))
                    yt.snippets[body["id"]] = dict(body["snippet"])
                    return body
                return _Request(go)

        return _Videos()


def _intervention(**kw):
    return {"id": 7, "video_id": SRC, "channel_id": CH, "lever": "backlinks",
            "origin": "midas", "arm": "treated", "status": "planned",
            "payload": {"targets": TARGETS}, "before_state": None,
            "applied_at": None, "created_at": "2026-10-23T00:00:00+00:00", **kw}


def _db(*, stored=LIVE, interventions=None, quota_log=()):
    return FakeSupabase({
        "channels": [{"id": CH, "default_language": "mr", "sync_shorts": True}],
        "videos": [{"id": SRC, "channel_id": CH, "is_short": False, "description": stored},
                   {"id": T1, "channel_id": CH, "is_short": False, "description": ""},
                   {"id": T2, "channel_id": CH, "is_short": False, "description": ""},
                   {"id": HUMAN, "channel_id": CH, "is_short": False, "description": ""}],
        "interventions": [_intervention()] if interventions is None else list(interventions),
        "audits": [],
        "quota_log": list(quota_log),
    })


@pytest.fixture
def edges():
    """Install the fake DB and YouTube, with writes enabled and DRY_RUN off."""
    with ExitStack() as stack:
        def install(sb, yt, *, enabled=True, dry_run=False):
            for mod in (ba, quota, he, iv, sync):
                stack.enter_context(patch.object(mod, "supabase", return_value=sb))
            stack.enter_context(patch.object(ba, "youtube_for_channel", return_value=yt))
            stack.enter_context(patch.object(ba.settings, "BACKLINK_APPLY_ENABLED", enabled))
            stack.enter_context(patch.object(ba.settings, "DRY_RUN", dry_run))
            stack.enter_context(patch.dict(backlinks.HEADINGS, {"mr": HEADING}))
            return sb, yt
        yield install


def _spent_today():
    """A quota_log row that leaves less than one apply's worth today."""
    return {"units": quota.settings.YT_DAILY_QUOTA, "operation": "videos.update",
            "occurred_at": datetime.now(timezone.utc).isoformat(), "channel_id": CH,
            "success": True, "id": 1}


# ── apply ────────────────────────────────────────────────────────────────

def test_only_the_description_differs_from_the_fetched_snippet(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    ba.apply_backlinks(_intervention())

    assert len(yt.updates) == 1
    part, body = yt.updates[0]
    assert part == "snippet"                       # no status part
    assert set(body) == {"id", "snippet"}          # no status body
    assert body["id"] == SRC
    sent = body["snippet"]
    assert {k for k in set(sent) | set(SNIPPET) if sent.get(k) != SNIPPET.get(k)} == {"description"}
    assert sent["description"] == _rendered()
    assert len(yt.lists) == 1


def test_the_live_description_is_used_not_the_stale_stored_one(edges):
    sb, yt = edges(_db(stored="An old description the team has since edited"),
                   FakeYouTube({SRC: SNIPPET}))
    ba.apply_backlinks(_intervention())
    assert yt.updates[0][1]["snippet"]["description"] == _rendered(LIVE)
    row = sb.rows("interventions")[0]
    assert row["before_state"] == {"description": LIVE}


def test_success_records_the_intervention_and_the_video_row(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    out = ba.apply_backlinks(_intervention())

    row = sb.rows("interventions")[0]
    assert row["status"] == "measuring"
    assert row["applied_at"]
    assert row["before_state"] == {"description": LIVE}
    assert row["payload"]["targets"] == TARGETS
    assert row["payload"]["description"] == _rendered()
    stored = {v["id"]: v["description"] for v in sb.rows("videos")}
    assert stored[SRC] == _rendered()
    assert out["status"] == "measuring"
    # 1u list + 50u update, through the ledger.
    assert sum(r["units"] for r in sb.rows("quota_log")) == quota.cost_of(*quota.APPLY)


def test_a_quota_refusal_sends_nothing(edges):
    sb, yt = edges(_db(quota_log=[_spent_today()]), FakeYouTube({SRC: SNIPPET}))
    with pytest.raises(ApplyError) as exc:
        ba.apply_backlinks(_intervention())
    assert exc.value.outcome is ApplyOutcome.QUOTA_INSUFFICIENT
    assert exc.value.status_code == 409
    assert yt.lists == [] and yt.updates == []
    assert [w for w in sb.writes if w[0] != "quota_log"] == []


def test_apply_disabled_sends_nothing(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}), enabled=False)
    with pytest.raises(ApplyError) as exc:
        ba.apply_backlinks(_intervention())
    assert exc.value.outcome is ApplyOutcome.APPLY_DISABLED
    assert exc.value.detail == "apply_disabled"
    assert yt.lists == [] and yt.updates == []
    assert sb.writes == []


def test_apply_is_off_by_default(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv("BACKLINK_APPLY_ENABLED", raising=False)
    assert Settings().BACKLINK_APPLY_ENABLED is False


def test_dry_run_sends_nothing(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}), dry_run=True)
    with patch.object(ba, "youtube_for_channel") as client:
        out = ba.apply_backlinks(_intervention())
    client.assert_not_called()
    assert yt.lists == [] and yt.updates == []
    assert sb.writes == []
    assert out["status"] == "dry_run"
    assert out["description"] == _rendered(LIVE)       # rendered onto the stored text


@pytest.mark.parametrize("change", [
    {"origin": "human", "arm": "n/a"},
    {"lever": "title"},
    {"arm": "holdout", "status": "holdout"},
    {"status": "measuring", "applied_at": "2026-10-20T00:00:00+00:00"},
    {"payload": {}},
])
def test_only_a_planned_treated_midas_backlinks_row_is_applied(edges, change):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    with pytest.raises(ValueError):
        ba.apply_backlinks(_intervention(**change))
    assert yt.lists == [] and yt.updates == []


def test_a_youtube_failure_is_typed_and_records_nothing(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}, fail=RuntimeError("quotaExceeded")))
    with pytest.raises(ApplyError) as exc:
        ba.apply_backlinks(_intervention())
    assert exc.value.outcome is ApplyOutcome.QUOTA_EXCEEDED
    assert sb.rows("interventions")[0]["status"] == "planned"
    assert {v["id"]: v["description"] for v in sb.rows("videos")}[SRC] == LIVE


def test_a_video_gone_from_youtube_fails_without_an_update(edges):
    sb, yt = edges(_db(), FakeYouTube({}))
    with pytest.raises(ApplyError) as exc:
        ba.apply_backlinks(_intervention())
    assert exc.value.outcome is ApplyOutcome.FAILED
    assert yt.updates == []


def test_a_refused_render_fails_without_an_update(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    with patch.dict(backlinks.HEADINGS, {}, clear=True), pytest.raises(ApplyError) as exc:
        ba.apply_backlinks(_intervention())
    assert exc.value.outcome is ApplyOutcome.FAILED
    assert "heading" in exc.value.detail
    assert yt.updates == []


def test_a_team_edit_since_the_last_sync_is_still_recorded(edges):
    """The apply reads past the sync: the team's link in the live description
    goes to the ledger as theirs before the stored row is overwritten."""
    live = f"{LIVE}\nhttps://youtu.be/{HUMAN}"
    sb, yt = edges(_db(stored=LIVE), FakeYouTube({SRC: {**SNIPPET, "description": live}}))
    ba.apply_backlinks(_intervention())
    human = [r for r in sb.rows("interventions") if r["origin"] == "human"]
    assert [r["payload"]["target_video_id"] for r in human] == [HUMAN]


# ── revert, through the endpoint ─────────────────────────────────────────

def _client():
    return TestClient(main.app, raise_server_exceptions=False)


def test_a_revert_restores_the_original_text(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    ba.apply_backlinks(_intervention())
    assert yt.snippets[SRC]["description"] == _rendered()

    r = _client().post("/interventions/7/revert")

    assert r.status_code == 200, r.text
    assert yt.snippets[SRC]["description"] == LIVE
    part, body = yt.updates[-1]
    assert part == "snippet" and set(body) == {"id", "snippet"}
    assert body["snippet"]["title"] == SNIPPET["title"]
    row = sb.rows("interventions")[0]
    assert row["status"] == "cancelled"
    assert row["payload"]["revert"]["description"] == LIVE
    assert row["payload"]["revert"]["reverted_at"]
    assert {v["id"]: v["description"] for v in sb.rows("videos")}[SRC] == LIVE


def test_a_revert_keeps_a_team_edit_made_after_the_apply(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    ba.apply_backlinks(_intervention())
    yt.snippets[SRC]["description"] = _rendered() + "\nAdded by the team"

    assert _client().post("/interventions/7/revert").status_code == 200
    assert yt.snippets[SRC]["description"] == LIVE + "\nAdded by the team"


def test_an_unaffordable_revert_is_409_and_sends_nothing(edges):
    applied = _intervention(status="measuring", applied_at="2026-10-20T00:00:00+00:00",
                            payload={"targets": TARGETS, "description": _rendered()})
    sb, yt = edges(_db(interventions=[applied], quota_log=[_spent_today()]),
                   FakeYouTube({SRC: {**SNIPPET, "description": _rendered()}}))

    r = _client().post("/interventions/7/revert")

    assert r.status_code == 409
    assert r.json()["detail"].startswith("quota_insufficient: revert needs 51 units")
    assert yt.lists == [] and yt.updates == []
    assert sb.rows("interventions")[0]["status"] == "measuring"


@pytest.mark.parametrize("row,status", [
    (_intervention(), 400),                                          # never applied
    (_intervention(status="cancelled", applied_at="2026-10-20T00:00:00+00:00"), 400),
    (_intervention(lever="playlist", status="measuring",
                   applied_at="2026-10-20T00:00:00+00:00"), 400),
    (_intervention(origin="human", arm="n/a", status="applied"), 400),
])
def test_only_an_applied_midas_backlinks_intervention_can_be_reverted(edges, row, status):
    sb, yt = edges(_db(interventions=[row]), FakeYouTube({SRC: SNIPPET}))
    assert _client().post("/interventions/7/revert").status_code == status
    assert yt.updates == []


def test_reverting_an_unknown_intervention_is_404(edges):
    edges(_db(interventions=[]), FakeYouTube({}))
    assert _client().post("/interventions/7/revert").status_code == 404


def test_a_revert_while_writes_are_disabled_is_409_and_sends_nothing(edges):
    applied = _intervention(status="measuring", applied_at="2026-10-20T00:00:00+00:00")
    sb, yt = edges(_db(interventions=[applied]), FakeYouTube({SRC: SNIPPET}), enabled=False)
    r = _client().post("/interventions/7/revert")
    assert r.status_code == 409
    assert r.json()["detail"] == "apply_disabled"
    assert yt.lists == []


def test_a_dry_run_revert_sends_nothing(edges):
    applied = _intervention(status="measuring", applied_at="2026-10-20T00:00:00+00:00")
    sb, yt = edges(_db(stored=_rendered(), interventions=[applied]),
                   FakeYouTube({SRC: SNIPPET}), dry_run=True)
    r = _client().post("/interventions/7/revert")
    assert r.status_code == 200
    assert r.json() == {"status": "dry_run", "description": LIVE}
    assert yt.lists == [] and sb.writes == []


# ── the ledger ───────────────────────────────────────────────────────────

def _item(description):
    return {"id": SRC,
            "snippet": {**SNIPPET, "description": description},
            "statistics": {"viewCount": "1", "likeCount": "0", "commentCount": "0"},
            "contentDetails": {"duration": "PT5M"},
            "status": {"privacyStatus": "public"}}


def _full_sync(sb, description):
    with patch.object(sync, "youtube_for_channel", return_value=MagicMock()), \
         patch.object(sync, "yt_channels_list_uploads",
                      return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch.object(sync, "yt_playlist_items_page",
                      return_value={"items": [{"contentDetails": {"videoId": SRC}}]}), \
         patch.object(sync, "yt_videos_list_full",
                      side_effect=lambda yt, cid, ids: [_item(description)]):
        sync.sync_channel(CH, full=True)


def test_a_sync_after_an_apply_records_no_human_intervention(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    ba.apply_backlinks(_intervention())
    _full_sync(sb, yt.snippets[SRC]["description"])
    assert [r for r in sb.rows("interventions") if r["origin"] == "human"] == []


def test_a_sync_that_missed_the_stored_write_still_sees_midas(edges):
    """The stored description is still the old one (the apply's row write was
    lost, or a sync raced it): the block's links are exactly the
    intervention's targets, so it is Midas's."""
    applied = _intervention(status="measuring", applied_at="2026-10-20T00:00:00+00:00",
                            payload={"targets": TARGETS, "description": _rendered()})
    sb, _ = edges(_db(stored=LIVE, interventions=[applied]), FakeYouTube({}))
    _full_sync(sb, _rendered())
    assert [r for r in sb.rows("interventions") if r["origin"] == "human"] == []
    assert he.made_by_midas(SRC, _rendered()) is True


def test_a_human_link_added_next_to_a_midas_block_still_records_one(edges):
    sb, yt = edges(_db(), FakeYouTube({SRC: SNIPPET}))
    ba.apply_backlinks(_intervention())
    edited = yt.snippets[SRC]["description"] + f"\nAlso watch https://youtu.be/{HUMAN}"
    _full_sync(sb, edited)
    human = [r for r in sb.rows("interventions") if r["origin"] == "human"]
    assert [r["payload"]["target_video_id"] for r in human] == [HUMAN]


@pytest.mark.parametrize("change", [
    {"arm": "holdout", "status": "holdout",      # would-have-got targets: never written
     "applied_at": "2026-10-20T00:00:00+00:00"},
    {"status": "planned"},                        # not applied
])
def test_only_an_applied_treated_block_counts_as_midas(edges, change):
    row = _intervention(**change)
    sb, _ = edges(_db(interventions=[row]), FakeYouTube({}))
    assert he.made_by_midas(SRC, _rendered()) is False
