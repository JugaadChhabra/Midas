"""GET /channels/{id}/seo: the channel page's read of what Midas did."""

from contextlib import contextmanager
from unittest.mock import patch

from app import channel_seo
from app.config import settings
from tests.fakes import FakeSupabase

CH = "UCr5-YUqBiW7PUmeAtxUWuRg"


@contextmanager
def db(interventions=(), channel=None, verdicts=()):
    ch = {"id": CH, "agent_enabled": True, "default_language": "mr", "autopilot_daily_cap": 15}
    ch.update(channel or {})
    sb = FakeSupabase({
        "channels": [ch],
        "interventions": list(interventions),
        "lever_verdicts": list(verdicts),
        "videos": [{"id": "v1", "title": "One", "thumbnail_url": "t1", "is_short": False},
                   {"id": "v2", "title": "Two", "thumbnail_url": "t2", "is_short": False}],
    })
    with patch.object(channel_seo, "supabase", return_value=sb), \
         patch.object(channel_seo.agent_tick, "backlinks_stopped", return_value=False), \
         patch.object(channel_seo.titles, "stopped", return_value=False), \
         patch.object(channel_seo.autopilot, "_applies_today", return_value=3), \
         patch.multiple(settings, BACKLINK_APPLY_ENABLED=True, TITLE_APPLY_ENABLED=True,
                        TITLE_CHANNELS={CH}):
        yield sb


def _row(id_, created, **kw):
    row = {"id": id_, "channel_id": CH, "video_id": "v1", "lever": "title", "origin": "midas",
           "arm": "treated", "status": "measuring", "applied_at": None, "detected_at": None,
           "created_at": f"2026-11-{created:02d}T08:00:00+00:00", "measurement_status": None,
           "measurement_result": None, "payload": {}}
    row.update(kw)
    return row


def test_trims_rows_and_joins_video_titles(authed_client):
    rows = [
        _row(1, 10, payload={"title": "New", "title_before": "Old", "path": "pipeline",
                             "candidates": [{"title": "x"}]},
             measurement_result={"delta": 0.2, "pre": 120, "post": 150}),
        _row(2, 12, lever="backlinks",
             payload={"targets": [{"video_id": "v2", "title": "Two", "similarity": 0.9}]}),
        _row(3, 11, status="cancelled", payload={"error": {"reason": "title_changed"}}),
    ]
    with db(rows):
        j = authed_client().get(f"/channels/{CH}/seo").json()
    assert [r["id"] for r in j["interventions"]] == [2, 3, 1]       # newest first
    title = j["interventions"][2]
    assert (title["title"], title["title_before"], title["delta"]) == ("New", "Old", 0.2)
    assert "candidates" not in title and "payload" not in title
    assert j["interventions"][0]["targets"] == [{"video_id": "v2", "title": "Two"}]
    assert j["interventions"][1]["error"] == "title_changed"
    assert set(j["videos"]) == {"v1", "v2"}
    assert j["today"] == {"written": 3, "cap": 15}
    assert j["levers"]["backlinks"] == {"on": True, "reason": None}


def test_lever_reasons():
    with db():
        assert channel_seo._lever_states({"id": CH, "agent_enabled": False})["title"]["on"] is False
        off = channel_seo._lever_states({"id": "other", "agent_enabled": True,
                                         "default_language": "xx"})
    assert off["backlinks"]["reason"] == "no heading written for this channel's language"
    assert off["title"]["reason"] == "not switched on for this channel"


def test_latest_verdict_per_lever_and_scope(authed_client):
    v = lambda lever, week, verdict: {
        "channel_id": CH, "lever": lever, "arm_scope": "treated_vs_holdout", "week_start": week,
        "n_treated": 1, "n_holdout": 1, "lift": 0, "cumulative_lift": 0, "windows_judged": 1,
        "verdict": verdict, "stop_rule_triggered": False}
    with db(verdicts=[v("backlinks", "2026-11-02", "worse"), v("backlinks", "2026-11-09", "helped")]):
        j = authed_client().get(f"/channels/{CH}/seo").json()
    assert [(r["lever"], r["verdict"]) for r in j["verdicts"]] == [("backlinks", "helped")]
