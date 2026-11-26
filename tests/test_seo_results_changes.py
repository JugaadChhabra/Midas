"""The Results page's drill-down (SEO results 06, #173), through the HTTP seam:
``GET /seo/results/changes?channel_id=&lever=&arm=&order=&limit=&offset=``.

One cell's rows for one channel, trimmed as the channel page trims them, plus
the video behind each and, for rows still inside their window, the early read.
Read-only.
"""
import math
from datetime import date, timedelta

import pytest

from tests.test_seo_results import (  # noqa: F401  (the `use` fixture)
    ADMIN, CH_A, CH_B, EXEC, MANAGER_A, _arm, _as, _iv, _rec, _store, _title, capped, use,
)
from tests.test_seo_results_early import (
    D0, FRONTIER, POST, PRE, _ingested, _open_backlink, _open_title, _reach, _views,
)


def _changes(uid=ADMIN, expect=200, **params):
    r = _as(uid).get("/seo/results/changes", params=params)
    assert r.status_code == expect, r.text
    return r.json()


def _videos():
    return [{"id": v, "channel_id": CH_A, "title": f"Title {v}", "thumbnail_url": f"http://t/{v}",
             "is_short": v == "short1"} for v in ("v1", "v2", "v3", "v4", "v5", "short1", "t1", "t2")]


def _judged(video, delta, arm="treated", payload=None, **kw):
    row = _iv(CH_A, arm, "judged", video=video, delta=delta, payload=payload,
              applied=arm == "treated", **kw)
    return row


def _ids(body):
    return [c["video_id"] for c in body["changes"]]


# ── rows ────────────────────────────────────────────────────────────────────

def test_a_row_carries_the_trimmed_change_and_its_video(use):
    payload = {"targets": [{"video_id": "t1", "title": "Target one"}]}
    use(_store([_judged("v1", 4.0, payload=payload)], videos=_videos()))

    body = _changes(channel_id=CH_A, lever="backlinks")

    (row,) = body["changes"]
    assert row["video_id"] == "v1" and row["delta"] == 4.0
    assert (row["pre"], row["post"]) == (1, 5.0)
    assert row["targets"] == [{"video_id": "t1", "title": "Target one"}]
    assert row["video"] == {"title": "Title v1", "thumbnail_url": "http://t/v1", "is_short": False}
    assert row["early"] is None and "trajectory" not in row
    assert (body["limit"], body["offset"], body["next_offset"]) == (100, 0, None)


def test_a_title_row_shows_before_after_and_path(use):
    payload = {"path": "agent", "title": "New", "title_before": "Old"}
    use(_store([_iv(CH_A, "treated", "judged", delta=0.2, payload=payload, lever="title")],
               videos=_videos()))

    (row,) = _changes(channel_id=CH_A, lever="title")["changes"]

    assert (row["title_before"], row["title"], row["path"]) == ("Old", "New", "agent")


def test_reverts_are_tagged_midas_or_a_person(use):
    auto = _iv(CH_A, "treated", "cancelled", video="v1", delta=-0.5, lever="title",
               payload={"revert": {"auto": True, "reverted_at": "2026-11-12T00:00:00+00:00"}})
    hand = _iv(CH_A, "treated", "cancelled", video="v2", delta=-0.4, lever="title",
               payload={"revert": {"auto": False, "reverted_at": "2026-11-12T00:00:00+00:00"}})
    plain = _iv(CH_A, "treated", "judged", video="v3", delta=0.1, lever="title")
    use(_store([auto, hand, plain], videos=_videos()))

    by_video = {c["video_id"]: c for c in _changes(channel_id=CH_A, lever="title")["changes"]}

    assert by_video["v1"]["reverted_by"] == "midas"
    assert by_video["v2"]["reverted_by"] == "person"
    assert by_video["v3"]["reverted_by"] is None


# ── order and paging ────────────────────────────────────────────────────────

def _spread():
    rows = [_judged("v1", 2.0), _judged("v2", 5.0), _judged("v3", -1.0), _judged("v4", -4.0)]
    pending = _iv(CH_A, "treated", "measuring", video="v5", applied=True)
    pending["created_at"] = "2026-11-20T00:00:00+00:00"
    return rows + [pending]


def test_delta_order_is_gains_best_first_then_losses_worst_first_then_the_rest(use):
    use(_store(_spread(), videos=_videos()))

    body = _changes(channel_id=CH_A, lever="backlinks")          # order=delta is the default

    assert _ids(body) == ["v2", "v1", "v4", "v3", "v5"]


def test_recent_order_is_newest_first(use):
    rows = _spread()
    for i, r in enumerate(rows):
        r["created_at"] = f"2026-11-{10 + i:02d}T00:00:00+00:00"
    use(_store(rows, videos=_videos()))

    assert _ids(_changes(channel_id=CH_A, lever="backlinks", order="recent")) == [
        "v5", "v4", "v3", "v2", "v1"]


def test_insufficient_data_rows_are_not_judged_for_the_order(use):
    weak = _iv(CH_A, "treated", "insufficient_data", video="v5", delta=99.0)
    use(_store([_judged("v1", -1.0), weak], videos=_videos()))

    assert _ids(_changes(channel_id=CH_A, lever="backlinks")) == ["v1", "v5"]


def test_paging_sets_next_offset_when_a_page_is_full(use):
    use(_store(_spread(), videos=_videos()))

    first = _changes(channel_id=CH_A, lever="backlinks", limit=2)
    last = _changes(channel_id=CH_A, lever="backlinks", limit=2, offset=4)

    assert _ids(first) == ["v2", "v1"] and first["next_offset"] == 2
    assert _ids(last) == ["v5"] and last["next_offset"] is None


def test_a_limit_over_1000_is_refused(use):
    use(_store(videos=_videos()))

    _changes(channel_id=CH_A, lever="backlinks", limit=1001, expect=422)


def test_every_row_of_a_big_channel_is_reachable(use, capped):
    rows = [_iv(CH_A, "treated", "measuring", video="v1") for _ in range(1500)]
    use(_store(rows, videos=_videos()))

    body = _changes(channel_id=CH_A, lever="backlinks", limit=1000, offset=1000)

    assert len(body["changes"]) == 500


# ── held back ───────────────────────────────────────────────────────────────

def test_the_arm_filter_picks_treated_or_held_back(use):
    use(_store([_judged("v1", 1.0), _judged("v2", 0.0, arm="holdout"),
                _iv(CH_A, "n/a", "declined", video="v3", applied=False)], videos=_videos()))

    assert _ids(_changes(channel_id=CH_A, lever="backlinks", arm="treated")) == ["v1"]
    assert _ids(_changes(channel_id=CH_A, lever="backlinks", arm="holdout")) == ["v2"]
    assert sorted(_ids(_changes(channel_id=CH_A, lever="backlinks"))) == ["v1", "v2", "v3"]


def test_an_unknown_lever_arm_or_order_is_400(use):
    use(_store(videos=_videos()))

    _changes(channel_id=CH_A, lever="nope", expect=400)
    _changes(channel_id=CH_A, lever="backlinks", arm="nope", expect=400)
    _changes(channel_id=CH_A, lever="backlinks", order="nope", expect=400)


# ── the early read ──────────────────────────────────────────────────────────

def test_an_open_title_row_has_the_early_read_and_a_judged_one_has_none(use):
    open_row = _open_title(CH_A, "pipeline", "treated", "v1", D0)
    open_row["payload"] = {**open_row["payload"], "title": "New", "title_before": "Old"}
    done = _iv(CH_A, "treated", "judged", video="v2", delta=0.3, lever="title",
               payload={"path": "pipeline"})
    traffic = _views("v1", PRE, 10) + _views("v1", POST, 12, source_type=5) \
        + _views("v1", POST, 8, source_type=7)
    reach = _reach("v1", PRE, 100, 0.02) + _reach("v1", POST, 200, 0.05)
    sb = use(_store([open_row, done], videos=_videos(), traffic=traffic, reach=reach,
                    ingested=_ingested(CH_A)))
    before = {t: list(rows) for t, rows in sb._tables.items()}

    by_video = {c["video_id"]: c for c in _changes(channel_id=CH_A, lever="title")["changes"]}

    early = by_video["v1"]["early"]
    assert early["post_days"] == 5
    assert early["delta"] == pytest.approx(math.log(21 / 11))
    assert early["impressions"] == {"pre": pytest.approx(100), "post": pytest.approx(200)}
    assert early["ctr"] == {"pre": pytest.approx(0.02), "post": pytest.approx(0.05)}
    assert by_video["v2"]["early"] is None
    assert {t: list(rows) for t, rows in sb._tables.items()} == before     # no row written


def test_an_open_backlinks_row_has_the_early_read_in_views_per_week(use):
    row = _open_backlink(CH_A, "treated", "v1", ["t1"], D0)
    pairs = [{"id": 900 + i, "video_id": "t1", "channel_id": CH_A, "date": d, "source_type": 7,
              "source_detail": "v1", "views": 2, "engaged_views": 2, "watch_time_minutes": 1.0,
              "report_id": "r"} for i, d in enumerate(POST)]
    use(_store([row], videos=_videos(), traffic=pairs, ingested=_ingested(CH_A)))

    (change,) = _changes(channel_id=CH_A, lever="backlinks")["changes"]

    assert change["early"]["post_days"] == 5
    assert change["early"]["delta"] == pytest.approx(2 * 7)       # 10 views / 5 days × 7, pre 0


# ── playlist arms and Short-link recommendations ────────────────────────────

def test_the_playlist_lever_lists_arms_with_their_playlists(use):
    sb = use(_store(videos=_videos()))
    sb._tables["playlist_arms"] = [_arm(CH_A, "PL1", "treated", "dosed"),
                                   _arm(CH_A, "PL2", "holdout", "holdout"),
                                   _arm(CH_B, "PL3", "treated", "dosed")]
    sb._tables["playlists"] = [{"id": "PL1", "channel_id": CH_A, "title": "Rhymes"}]

    body = _changes(channel_id=CH_A, lever="playlist")
    treated = _changes(channel_id=CH_A, lever="playlist", arm="treated")

    assert sorted(c["playlist_id"] for c in body["changes"]) == ["PL1", "PL2"]
    assert [c["playlist_id"] for c in treated["changes"]] == ["PL1"]
    assert treated["changes"][0]["playlist"]["title"] == "Rhymes"
    assert treated["changes"][0]["status"] == "dosed"


def test_the_short_link_lever_lists_recommendations_with_both_videos(use):
    sb = use(_store(videos=_videos()))
    mine, theirs = _rec(CH_A, "set", seen=True), _rec(CH_B, "pending")
    mine["target_video_id"] = "t1"
    sb._tables["short_link_recommendations"] = [mine, theirs]

    (row,) = _changes(channel_id=CH_A, lever="short_link")["changes"]

    assert row["status"] == "set" and row["seen_at"]
    assert row["video"]["title"] == "Title short1" and row["video"]["is_short"] is True
    assert row["target"]["title"] == "Title t1"


# ── scope ───────────────────────────────────────────────────────────────────

def test_a_manager_reads_their_channel_and_gets_404_for_anothers(use):
    use(_store([_judged("v1", 1.0), _iv(CH_B, "treated", "judged", video="v2", delta=1.0)],
               videos=_videos()))

    assert _ids(_changes(MANAGER_A, channel_id=CH_A, lever="backlinks")) == ["v1"]
    r = _changes(MANAGER_A, channel_id=CH_B, lever="backlinks", expect=404)
    assert r == {"detail": "channel_not_found"}
    assert _changes(MANAGER_A, channel_id="nope", lever="backlinks", expect=404) == r


def test_exec_and_admin_read_any_channel(use):
    use(_store([_iv(CH_B, "treated", "judged", video="v2", delta=1.0)], videos=_videos()))

    assert _ids(_changes(EXEC, channel_id=CH_B, lever="backlinks")) == ["v2"]
    assert _ids(_changes(ADMIN, channel_id=CH_B, lever="backlinks")) == ["v2"]


def test_a_channel_is_required(use):
    use(_store(videos=_videos()))

    _changes(lever="backlinks", expect=422)
