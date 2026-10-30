"""Slice 3 · S3.1 (#115): the title-only write and its revert.

These drive the real apply/revert, the real yt_* helpers and the real quota
gate against FakeSupabase; only the YouTube client is faked, and it records
every update body it is sent (tests/test_backlinks_apply.py FakeYouTube).
"""
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import autopilot as ap, backlinks, backlinks_apply as ba, channel_audits, main, quota
from app import titles_apply as ta
from app.apply_outcome import ApplyError, ApplyOutcome
from tests.fakes import FakeSupabase
from tests.test_backlinks_apply import FakeYouTube

CH = "UCmarathi1"
VID = "srcVideo001"
OLD = "Twinkle Twinkle | Marathi Rhymes"
NEW = "Twinkle Twinkle Little Star | मराठी बालगीत"

with patch.dict(backlinks.HEADINGS, {"mr": "आणखी गाणी पहा:"}):
    DESCRIPTION = backlinks.render(
        "Twinkle twinkle\nLyrics and more\n#rhymes",
        [{"video_id": "tgtVideo001", "title": "Rhyme one"},
         {"video_id": "tgtVideo002", "title": "Rhyme two"}], "mr")

SNIPPET = {
    "title": OLD,
    "description": DESCRIPTION,
    "tags": ["live", "tags", "मराठी"],
    "categoryId": "27",
    "defaultLanguage": "mr",
    "defaultAudioLanguage": "mr",
    "localized": {"title": OLD, "description": DESCRIPTION},
    "thumbnails": {"default": {"url": "https://i.ytimg.com/vi/x/default.jpg"}},
    "channelId": CH,
    "channelTitle": "Marathi",
    "liveBroadcastContent": "none",
    "publishedAt": "2026-01-01T00:00:00Z",
}


def _intervention(**kw):
    return {"id": 9, "video_id": VID, "channel_id": CH, "lever": "title",
            "origin": "midas", "arm": "treated", "status": "planned",
            "payload": {"title": NEW, "title_before": OLD}, "before_state": None,
            "applied_at": None, "created_at": "2026-10-30T00:00:00+00:00", **kw}


def _applied(**kw):
    return _intervention(**{"status": "measuring", "applied_at": "2026-10-30T01:00:00+00:00",
                            "before_state": {"title": OLD}, **kw})


def _db(*, interventions=None, quota_log=(), title=OLD):
    return FakeSupabase({
        "channels": [{"id": CH, "default_language": "mr"}],
        "videos": [{"id": VID, "channel_id": CH, "title": title, "description": DESCRIPTION}],
        "interventions": [_intervention()] if interventions is None else list(interventions),
        "audits": [],
        "quota_log": list(quota_log),
    })


@pytest.fixture
def edges():
    """Install the fake DB and YouTube, with title writes enabled and DRY_RUN off."""
    with ExitStack() as stack:
        def install(sb, yt, *, enabled=True, dry_run=False, backlinks_enabled=True):
            for mod in (ba, ta, quota, ap, channel_audits):
                stack.enter_context(patch.object(mod, "supabase", return_value=sb))
            stack.enter_context(patch.object(ba, "youtube_for_channel", return_value=yt))
            stack.enter_context(patch.object(ta.settings, "TITLE_APPLY_ENABLED", enabled))
            stack.enter_context(patch.object(ta.settings, "BACKLINK_APPLY_ENABLED",
                                             backlinks_enabled))
            stack.enter_context(patch.object(ta.settings, "DRY_RUN", dry_run))
            return sb, yt
        yield install


def _spent_today():
    """A quota_log row that leaves less than one apply's worth today."""
    return {"units": quota.settings.YT_DAILY_QUOTA, "operation": "videos.update",
            "occurred_at": datetime.now(timezone.utc).isoformat(), "channel_id": CH,
            "success": True, "id": 1}


def _changed(sent: dict, fetched: dict) -> set[str]:
    return {k for k in set(sent) | set(fetched) if sent.get(k) != fetched.get(k)}


def _client():
    return TestClient(main.app, raise_server_exceptions=False)


def _title_of(sb):
    return {v["id"]: v["title"] for v in sb.rows("videos")}[VID]


# ── apply ────────────────────────────────────────────────────────────────

def test_only_the_title_differs_from_the_fetched_snippet(edges):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}))
    ta.apply_title(_intervention())

    assert len(yt.lists) == 1 and len(yt.updates) == 1
    part, body = yt.updates[0]
    assert part == "snippet"                       # no status part
    assert set(body) == {"id", "snippet"}          # no status body
    assert body["id"] == VID
    sent = body["snippet"]
    assert _changed(sent, SNIPPET) == {"title"}
    assert sent["title"] == NEW
    # Byte-identical, the backlink block included.
    for field in ("description", "tags", "categoryId", "defaultLanguage",
                  "defaultAudioLanguage", "localized", "thumbnails"):
        assert sent[field] == SNIPPET[field]
    assert backlinks.find(sent["description"]) is not None


def test_success_records_the_intervention_and_the_video_row(edges):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}))
    out = ta.apply_title(_intervention())

    row = sb.rows("interventions")[0]
    assert row["status"] == "measuring"
    assert row["applied_at"]
    assert row["before_state"] == {"title": OLD}
    assert row["payload"] == {"title": NEW, "title_before": OLD}
    assert _title_of(sb) == NEW
    assert {v["id"]: v["description"] for v in sb.rows("videos")}[VID] == DESCRIPTION
    assert out == {"status": "measuring", "title": NEW}
    assert sum(r["units"] for r in sb.rows("quota_log")) == quota.cost_of(*quota.APPLY)


def test_apply_disabled_sends_nothing(edges):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}), enabled=False)
    with pytest.raises(ApplyError) as exc:
        ta.apply_title(_intervention())
    assert exc.value.outcome is ApplyOutcome.APPLY_DISABLED
    assert exc.value.detail == "apply_disabled"
    assert yt.lists == [] and yt.updates == []
    assert sb.writes == []


def test_the_backlinks_switch_does_not_enable_titles(edges):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}), enabled=False, backlinks_enabled=True)
    with pytest.raises(ApplyError):
        ta.apply_title(_intervention())
    assert yt.lists == []


def test_apply_is_off_by_default(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv("TITLE_APPLY_ENABLED", raising=False)
    assert Settings().TITLE_APPLY_ENABLED is False


def test_dry_run_sends_nothing(edges):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}), dry_run=True)
    with patch.object(ba, "youtube_for_channel") as client:
        out = ta.apply_title(_intervention())
    client.assert_not_called()
    assert yt.lists == [] and yt.updates == []
    assert sb.writes == []
    assert out == {"status": "dry_run", "title": NEW}


def test_a_quota_refusal_sends_nothing(edges):
    sb, yt = edges(_db(quota_log=[_spent_today()]), FakeYouTube({VID: SNIPPET}))
    with pytest.raises(ApplyError) as exc:
        ta.apply_title(_intervention())
    assert exc.value.outcome is ApplyOutcome.QUOTA_INSUFFICIENT
    assert exc.value.detail.startswith("quota_insufficient: title apply needs 51 units")
    assert yt.lists == [] and yt.updates == []
    assert [w for w in sb.writes if w[0] != "quota_log"] == []


def test_a_title_changed_since_triage_refuses_and_sends_nothing(edges):
    sb, yt = edges(_db(), FakeYouTube({VID: {**SNIPPET, "title": "Edited by the team"}}))
    with pytest.raises(ApplyError) as exc:
        ta.apply_title(_intervention())
    assert exc.value.outcome is ApplyOutcome.FAILED
    assert exc.value.detail == "title_changed"
    assert len(yt.lists) == 1 and yt.updates == []
    assert sb.rows("interventions")[0]["status"] == "planned"
    assert _title_of(sb) == OLD


@pytest.mark.parametrize("change", [
    {"origin": "human", "arm": "n/a"},
    {"lever": "backlinks"},
    {"arm": "holdout", "status": "holdout"},
    {"status": "measuring", "applied_at": "2026-10-20T00:00:00+00:00"},
    {"payload": {"title_before": OLD}},
    {"payload": {"title": NEW}},
])
def test_only_a_planned_treated_midas_title_row_is_applied(edges, change):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}))
    with pytest.raises(ValueError):
        ta.apply_title(_intervention(**change))
    assert yt.lists == [] and yt.updates == []


@pytest.mark.parametrize("error,outcome", [
    (RuntimeError("quotaExceeded"), ApplyOutcome.QUOTA_EXCEEDED),
    (RuntimeError("backendError"), ApplyOutcome.FAILED),
])
def test_a_youtube_failure_is_typed_and_records_nothing(edges, error, outcome):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}, fail=error))
    with pytest.raises(ApplyError) as exc:
        ta.apply_title(_intervention())
    assert exc.value.outcome is outcome
    assert sb.rows("interventions")[0]["status"] == "planned"
    assert _title_of(sb) == OLD


def test_a_video_gone_from_youtube_fails_without_an_update(edges):
    sb, yt = edges(_db(), FakeYouTube({}))
    with pytest.raises(ApplyError) as exc:
        ta.apply_title(_intervention())
    assert exc.value.outcome is ApplyOutcome.FAILED
    assert yt.updates == []


def test_an_applied_title_counts_toward_the_daily_cap(edges):
    """The cap already counts applied Midas interventions of any lever."""
    row = _intervention(created_at=datetime.now(timezone.utc).isoformat())
    sb, yt = edges(_db(interventions=[row]), FakeYouTube({VID: SNIPPET}))
    assert ap._applies_today(CH) == 1          # the planned treated row, unsent
    ta.apply_title(row)
    assert ap._applies_today(CH) == 1          # now applied: counted once


# ── revert ───────────────────────────────────────────────────────────────

def test_revert_restores_only_the_title(edges):
    sb, yt = edges(_db(), FakeYouTube({VID: SNIPPET}))
    ta.apply_title(_intervention())
    # The team edits the description after the apply; the revert keeps it.
    yt.snippets[VID]["description"] = DESCRIPTION + "\nAdded by the team"
    fetched = dict(yt.snippets[VID])

    r = _client().post("/interventions/9/revert")

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "cancelled", "title": OLD}
    part, body = yt.updates[-1]
    assert part == "snippet" and set(body) == {"id", "snippet"}
    assert _changed(body["snippet"], fetched) == {"title"}
    assert body["snippet"]["title"] == OLD
    row = sb.rows("interventions")[0]
    assert row["status"] == "cancelled"
    revert = row["payload"]["revert"]
    assert revert["title"] == OLD and revert["live_before"] == NEW
    assert revert["auto"] is False and revert["reverted_at"]
    assert row["payload"]["title"] == NEW
    assert _title_of(sb) == OLD


def test_revert_title_records_an_automatic_revert(edges):
    sb, yt = edges(_db(interventions=[_applied()], title=NEW),
                   FakeYouTube({VID: {**SNIPPET, "title": NEW}}))
    out = ta.revert_title(_applied(), auto=True)
    assert out == {"status": "cancelled", "title": OLD}
    assert sb.rows("interventions")[0]["payload"]["revert"]["auto"] is True
    assert yt.snippets[VID]["title"] == OLD


def test_a_revert_refuses_a_title_the_team_changed(edges):
    sb, yt = edges(_db(interventions=[_applied()], title=NEW),
                   FakeYouTube({VID: {**SNIPPET, "title": "The team's own title"}}))

    r = _client().post("/interventions/9/revert")

    assert r.status_code == 409
    assert r.json()["detail"] == "title_changed"
    assert yt.updates == []
    assert sb.rows("interventions")[0]["status"] == "measuring"
    assert _title_of(sb) == NEW


def test_an_unaffordable_revert_is_409_and_sends_nothing(edges):
    sb, yt = edges(_db(interventions=[_applied()], quota_log=[_spent_today()]),
                   FakeYouTube({VID: {**SNIPPET, "title": NEW}}))
    r = _client().post("/interventions/9/revert")
    assert r.status_code == 409
    assert r.json()["detail"].startswith("quota_insufficient: revert needs 51 units")
    assert yt.lists == [] and yt.updates == []
    assert sb.rows("interventions")[0]["status"] == "measuring"


def test_a_revert_while_title_writes_are_disabled_is_409_and_sends_nothing(edges):
    sb, yt = edges(_db(interventions=[_applied()]), FakeYouTube({VID: SNIPPET}),
                   enabled=False, backlinks_enabled=True)
    r = _client().post("/interventions/9/revert")
    assert r.status_code == 409
    assert r.json()["detail"] == "apply_disabled"
    assert yt.lists == [] and sb.writes == []


def test_a_title_revert_does_not_need_the_backlinks_switch(edges):
    sb, yt = edges(_db(interventions=[_applied()], title=NEW),
                   FakeYouTube({VID: {**SNIPPET, "title": NEW}}), backlinks_enabled=False)
    assert _client().post("/interventions/9/revert").status_code == 200
    assert yt.snippets[VID]["title"] == OLD


def test_a_dry_run_revert_sends_nothing(edges):
    sb, yt = edges(_db(interventions=[_applied()]), FakeYouTube({VID: SNIPPET}),
                   dry_run=True)
    r = _client().post("/interventions/9/revert")
    assert r.status_code == 200
    assert r.json() == {"status": "dry_run", "title": OLD}
    assert yt.lists == [] and sb.writes == []


@pytest.mark.parametrize("row", [
    _intervention(),                                               # never applied
    _applied(status="cancelled"),
    _applied(origin="human", arm="n/a"),
    _applied(before_state=None),
])
def test_only_an_applied_midas_title_intervention_can_be_reverted(edges, row):
    sb, yt = edges(_db(interventions=[row]), FakeYouTube({VID: SNIPPET}))
    assert _client().post("/interventions/9/revert").status_code == 400
    with pytest.raises(ValueError):
        ta.revert_title(row, auto=False)
    assert yt.updates == []


def test_a_backlinks_revert_does_not_need_the_title_switch(edges):
    """The backlinks revert is unchanged: it reads BACKLINK_APPLY_ENABLED only."""
    from tests.test_backlinks_apply import _intervention as backlinks_row
    row = backlinks_row(status="measuring", applied_at="2026-10-30T01:00:00+00:00")
    with patch.dict(backlinks.HEADINGS, {"mr": "आणखी गाणी पहा:"}):
        stripped = backlinks.strip(DESCRIPTION)
    sb, yt = edges(_db(interventions=[row]), FakeYouTube({row["video_id"]: SNIPPET}),
                   enabled=False, backlinks_enabled=True)
    r = _client().post(f"/interventions/{row['id']}/revert")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "cancelled", "description": stripped}
    assert yt.snippets[row["video_id"]]["title"] == OLD
