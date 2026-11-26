"""The Results page's "This week" (SEO results 07, #174), through the HTTP seam:
``GET /seo/results/timeline?days=`` and ``today`` on ``GET /seo/results``.
Read-only.
"""
from datetime import datetime, timedelta, timezone

from tests.test_seo_results import (  # noqa: F401  (the `use` fixture)
    ADMIN, CH_A, CH_A2, CH_B, EXEC, MANAGER_A, _as, _iv, _results, _store, _verdict, use,
)


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def _timeline(uid=ADMIN, expect=200, **params):
    r = _as(uid).get("/seo/results/timeline", params=params)
    assert r.status_code == expect, r.text
    return r.json()


def _row(channel, *, applied=None, judged=None, revert=None, status="measuring", error=None,
         created=None, video="v1", arm="treated", origin="midas", lever="backlinks"):
    iv = _iv(channel, arm, status, origin=origin, video=video, lever=lever, applied=False)
    iv["applied_at"] = applied
    iv["created_at"] = created or _ago(days=30)
    payload = {}
    if revert:
        payload["revert"] = revert
    if error:
        payload["error"] = {"reason": error}
    iv["payload"] = payload
    if judged:
        iv["measurement_result"] = {"delta": 1.5, "judged_at": judged}
    return iv


def test_each_kind_is_an_event(use):
    stop = _verdict(CH_A, "2026-11-09", stop=True, lever="title", scope="agent_vs_holdout")
    stop["computed_at"] = _ago(hours=2)
    sb = use(_store([
        _row(CH_A, applied=_ago(hours=5), video="v1"),
        _row(CH_A, judged=_ago(hours=4), status="judged", video="v2"),
        _row(CH_A, revert={"reverted_at": _ago(hours=3), "auto": True}, status="cancelled",
             applied=_ago(days=40), video="v3", lever="title"),
        _row(CH_A, status="cancelled", error="dry_run", created=_ago(hours=1), video="v4"),
    ], [stop]))

    events = _timeline()["events"]

    assert [e["kind"] for e in events] == ["cancelled", "stopped", "reverted", "judged", "written"]
    by = {e["kind"]: e for e in events}
    assert by["written"]["video_id"] == "v1" and by["written"]["lever"] == "backlinks"
    assert by["judged"]["detail"]["delta"] == 1.5
    assert by["reverted"]["detail"]["by"] == "midas" and by["reverted"]["lever"] == "title"
    assert by["cancelled"]["detail"]["reason"] == "dry_run"
    assert by["stopped"]["video_id"] is None and by["stopped"]["lever"] == "title"
    assert by["stopped"]["detail"]["arm_scope"] == "agent_vs_holdout"
    assert by["written"]["channel_id"] == CH_A and by["written"]["at"]
    assert sb.writes == []


def test_only_the_first_firing_of_a_stop_is_an_event(use):
    old = _verdict(CH_A, "2026-11-02", stop=True)
    old["computed_at"] = _ago(days=20)
    later = _verdict(CH_A, "2026-11-09", stop=True)
    later["computed_at"] = _ago(hours=1)
    use(_store([], [old, later]))

    assert _timeline()["events"] == []


def test_the_day_window_and_the_422(use):
    use(_store([
        _row(CH_A, applied=_ago(hours=1), video="v1"),
        _row(CH_A, applied=_ago(days=3), video="v2"),
        _row(CH_A, applied=_ago(days=10), video="v3"),
    ]))

    assert [e["video_id"] for e in _timeline()["events"]] == ["v1", "v2"]
    assert [e["video_id"] for e in _timeline(days=1)["events"]] == ["v1"]
    assert [e["video_id"] for e in _timeline(days=31)["events"]] == ["v1", "v2", "v3"]
    _timeline(days=32, expect=422)
    _timeline(days=0, expect=422)


def test_events_come_newest_first(use):
    use(_store([
        _row(CH_A, applied=_ago(hours=9), video="v1"),
        _row(CH_A, applied=_ago(hours=1), video="v2"),
        _row(CH_A, applied=_ago(hours=5), video="v3"),
    ]))

    assert [e["video_id"] for e in _timeline(days=2)["events"]] == ["v2", "v3", "v1"]


def test_the_teams_rows_are_not_midas_events(use):
    use(_store([_row(CH_A, applied=_ago(hours=1), origin="human", arm="n/a")]))

    assert _timeline()["events"] == []


def test_a_manager_sees_only_their_channels(use):
    use(_store([
        _row(CH_A, applied=_ago(hours=1), video="v1"),
        _row(CH_B, applied=_ago(hours=2), video="v2"),
    ]))

    assert [e["channel_id"] for e in _timeline(MANAGER_A)["events"]] == [CH_A]
    assert {e["channel_id"] for e in _timeline(EXEC)["events"]} == {CH_A, CH_B}


def test_today_equals_the_channel_page(use):
    use(_store([
        _row(CH_A, applied=_ago(seconds=1), video="v1"),
        _row(CH_A, applied=_ago(seconds=1), video="v2"),
        _row(CH_A2, applied=_ago(days=3), video="v3"),
    ]))

    today = {c["id"]: c["today"] for c in _results()["channels"]}

    for cid in (CH_A, CH_A2):
        assert today[cid] == _as(ADMIN).get(f"/channels/{cid}/seo").json()["today"]
    assert today[CH_A]["cap"] == 10
    assert today[CH_A2]["written"] == 0
