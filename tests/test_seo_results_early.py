"""The early read on the Results page (SEO results 05, #172), through the HTTP
seam: TestClient over the app, with interventions, traffic, reach and the
ingest ledger in a FakeSupabase.

A title or backlinks cell, and the fleet row, carry ``early``: treated vs
holdout over the rows still inside their window, from the post data-days
already ingested. Never a verdict, never written.
"""
import math
from datetime import date, timedelta

import pytest

from tests.test_seo_results import (  # noqa: F401  (the `use` fixture)
    ADMIN, CH_A, CH_A2, CH_B, MANAGER_A, _as, _cell, _iv, _results, _store, _title, use,
)

#: The traffic frontier: the last ingested data-day.
FRONTIER = date(2026, 11, 20)
_ids = iter(range(1, 10_000_000))


def _days(start: date, end: date):
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _ingested(channel_id, start=date(2026, 10, 20), end=FRONTIER,
              report_type="channel_traffic_source_a3"):
    return [{"report_id": f"{channel_id}-{report_type}-{d}", "channel_id": channel_id,
             "data_date": d, "report_type": report_type, "job_id": "j", "row_count": 1}
            for d in _days(start, end)]


def _views(video, days, views, source_type=3, detail="", channel_id=CH_A):
    return [{"id": next(_ids), "video_id": video, "channel_id": channel_id, "date": d,
             "source_type": source_type, "source_detail": detail, "views": views,
             "engaged_views": views, "watch_time_minutes": 1.0, "report_id": "r"}
            for d in days]


def _reach(video, days, impressions, ctr, channel_id=CH_A):
    return [{"id": next(_ids), "video_id": video, "channel_id": channel_id, "date": d,
             "impressions": impressions, "ctr": ctr, "report_id": "r"} for d in days]


def _open_title(channel_id, path, arm, video, d0: date):
    """A `midas` title row still in its window, its d0 the given data-day
    (15:00 UTC is that day in Pacific time)."""
    at = f"{d0.isoformat()}T15:00:00+00:00"
    if arm == "holdout":
        row = _title(channel_id, None, "holdout", "holdout", applied=False, created=at)
    else:
        row = _title(channel_id, path, "treated", "measuring", applied=True, created=at)
        row["applied_at"] = at
    row["video_id"] = video
    row["measurement_status"] = "awaiting_window"
    return row


def _open_backlink(channel_id, arm, video, targets, d0: date):
    at = f"{d0.isoformat()}T15:00:00+00:00"
    payload = {"targets": [{"video_id": t, "channel_id": channel_id, "title": t} for t in targets]}
    row = _iv(channel_id, arm, "measuring" if arm == "treated" else "holdout", video=video,
              applied=arm == "treated", payload=payload)
    row["created_at"] = at
    row["applied_at"] = at if arm == "treated" else None
    return row


def _videos(*ids, shorts=()):
    return [{"id": v, "channel_id": CH_A, "title": v, "thumbnail_url": None,
             "is_short": v in shorts} for v in ids]


D0 = FRONTIER - timedelta(days=5)                       # 11-15: post days 11-16 … 11-20
PRE = _days(D0 - timedelta(days=14), D0 - timedelta(days=1))
POST = _days(D0 + timedelta(days=1), FRONTIER)


def _title_world(extra_traffic=(), **kw):
    """A treated title (v1) and a holdout (v2), both d0 five data-days before
    the frontier, with a day past the frontier that isn't ingested yet."""
    rows = [_open_title(CH_A, "pipeline", "treated", "v1", D0),
            _open_title(CH_A, None, "holdout", "v2", D0)]
    traffic = (_views("v1", PRE, 10)                                 # browse: 10 / day
               + _views("v1", POST, 12, source_type=5)               # search
               + _views("v1", POST, 8, source_type=7)                # suggested: 20 / day
               + _views("v2", PRE, 10) + _views("v2", POST, 10, source_type=7)
               + _views("v1", ["2026-11-21"], 5000)                  # not ingested yet
               + list(extra_traffic))
    return _store(rows, videos=_videos("v1", "v2"), traffic=traffic,
                  ingested=_ingested(CH_A), **kw)


# ── titles ──────────────────────────────────────────────────────────────────

def test_a_title_five_data_days_before_the_frontier_uses_five_post_days_and_daily_means(use):
    use(_title_world())

    early = _cell(_results(), CH_A, "title")["early"]

    assert (early["post_days_min"], early["post_days_max"]) == (5, 5)
    assert (early["n_treated"], early["n_holdout"]) == (1, 1)
    # Per-day means: pre 10 a day over 14 days, post 20 a day over 5.
    assert early["treated_mean_delta"] == pytest.approx(math.log(21 / 11))
    assert early["holdout_mean_delta"] == pytest.approx(0.0)
    assert early["lift"] == pytest.approx(math.log(21 / 11))


def test_the_early_read_counts_the_verdicts_source_types_only(use):
    # Playlists (14) and the Shorts feed (24) aren't where a title is read.
    use(_title_world(extra_traffic=_views("v1", POST, 1000, source_type=14)
                     + _views("v1", POST, 1000, source_type=24)))

    early = _cell(_results(), CH_A, "title")["early"]

    assert early["treated_mean_delta"] == pytest.approx(math.log(21 / 11))


def test_treated_and_holdout_stay_separate(use):
    rows = [_open_title(CH_A, "pipeline", "treated", "v1", D0),
            _open_title(CH_A, "agent", "treated", "v3", D0),
            _open_title(CH_A, None, "holdout", "v2", D0)]
    traffic = (_views("v1", PRE, 10) + _views("v1", POST, 32)        # ln(33/11)
               + _views("v3", PRE, 10) + _views("v3", POST, 10)      # 0
               + _views("v2", PRE, 21) + _views("v2", POST, 10))     # ln(11/22)
    use(_store(rows, videos=_videos("v1", "v2", "v3"), traffic=traffic,
               ingested=_ingested(CH_A)))

    early = _cell(_results(), CH_A, "title")["early"]

    assert (early["n_treated"], early["n_holdout"]) == (2, 1)
    assert early["treated_mean_delta"] == pytest.approx(math.log(3) / 2)
    assert early["holdout_mean_delta"] == pytest.approx(math.log(1 / 2))
    assert early["lift"] == pytest.approx(math.log(3) / 2 - math.log(1 / 2))


def test_impressions_and_ctr_before_and_after_come_from_reach(use):
    reach = (_reach("v1", PRE, 100, 0.02) + _reach("v1", POST, 200, 0.05)
             + _reach("v2", PRE, 9999, 0.5))                          # the holdout's: not shown
    use(_title_world(reach=reach))

    early = _cell(_results(), CH_A, "title")["early"]

    assert early["impressions"] == {"pre": pytest.approx(100), "post": pytest.approx(200)}
    assert early["ctr"] == {"pre": pytest.approx(0.02), "post": pytest.approx(0.05)}


def test_judged_rows_have_no_early_read(use):
    rows = [_title(CH_A, "pipeline", delta=0.3), _title(CH_A, None, "holdout", "judged", 0.1,
                                                         applied=False)]
    for r in rows:
        r["video_id"] = "v1"
    use(_store(rows, videos=_videos("v1"), traffic=_views("v1", POST, 50),
               ingested=_ingested(CH_A)))

    body = _results()

    assert _cell(body, CH_A, "title")["early"] is None
    assert body["fleet"]["levers"]["title"]["early"] is None


def test_a_row_with_no_ingested_post_day_yet_has_no_early_read(use):
    row = _open_title(CH_A, "pipeline", "treated", "v1", FRONTIER)    # d0 = the frontier
    use(_store([row], videos=_videos("v1"), traffic=_views("v1", PRE, 10),
               ingested=_ingested(CH_A)))

    assert _cell(_results(), CH_A, "title")["early"] is None


def test_the_post_window_is_capped_at_the_verdicts(use):
    d0 = FRONTIER - timedelta(days=20)                               # window complete, not yet judged
    use(_store([_open_title(CH_A, "pipeline", "treated", "v1", d0)], videos=_videos("v1"),
               ingested=_ingested(CH_A)))

    early = _cell(_results(), CH_A, "title")["early"]

    assert early["post_days_max"] == 14
    assert early["holdout_mean_delta"] is None and early["lift"] is None


# ── backlinks ───────────────────────────────────────────────────────────────

def test_backlinks_early_read_is_pair_views_in_views_per_week(use):
    d0 = FRONTIER - timedelta(days=3)                                # post 11-18 … 11-20
    pre = _days(d0 - timedelta(days=7), d0 - timedelta(days=1))
    post = _days(d0 + timedelta(days=1), FRONTIER)
    rows = [_open_backlink(CH_A, "treated", "v1", ["t1"], d0),
            _open_backlink(CH_A, "holdout", "v2", ["t2"], d0)]
    traffic = (_views("t1", pre, 2, 7, "v1") + _views("t1", post, 5, 7, "v1")
               + _views("t1", post, 900, 7, "other")                 # another source
               + _views("t1", post, 900, 3, "v1")                    # another source type
               + _views("t2", pre, 1, 7, "v2") + _views("t2", post, 1, 7, "v2"))
    use(_store(rows, videos=_videos("v1", "v2", "t1", "t2"), traffic=traffic,
               ingested=_ingested(CH_A)))

    early = _cell(_results(), CH_A)["early"]

    # Treated: 15 post views over 3 days = 35 a week, against 14 the week before.
    assert early["treated_mean_delta"] == pytest.approx(35 - 14)
    assert early["holdout_mean_delta"] == pytest.approx(0.0)
    assert early["lift"] == pytest.approx(21)
    assert (early["post_days_min"], early["post_days_max"]) == (3, 3)
    assert early["impressions"] is None and early["ctr"] is None


def test_backlinks_rows_on_shorts_have_no_early_read(use):
    d0 = FRONTIER - timedelta(days=3)
    rows = [_open_backlink(CH_A, "treated", "s1", ["t1"], d0)]
    use(_store(rows, videos=_videos("s1", "t1", shorts={"s1"}),
               traffic=_views("t1", [FRONTIER.isoformat()], 5, 7, "s1"),
               ingested=_ingested(CH_A)))

    assert _cell(_results(), CH_A)["early"] is None


def test_the_fleet_pools_every_visible_row(use):
    d0 = FRONTIER - timedelta(days=7)
    post = _days(d0 + timedelta(days=1), FRONTIER)
    rows = [_open_backlink(CH_A, "treated", "a1", ["ta"], d0),
            _open_backlink(CH_A, "treated", "a2", ["ta"], d0),
            _open_backlink(CH_A, "holdout", "a3", ["ta"], d0),
            _open_backlink(CH_A2, "treated", "b1", ["tb"], d0),
            _open_backlink(CH_A2, "holdout", "b2", ["tb"], d0 + timedelta(days=4))]
    traffic = (_views("ta", post, 1, 7, "a1")                         # +7
               + _views("ta", post, 3, 7, "a2")                       # +21
               + _views("tb", post, 4, 7, "b1", channel_id=CH_A2))    # +28; holdouts 0
    videos = _videos("a1", "a2", "a3", "ta") + [
        {"id": v, "channel_id": CH_A2, "title": v, "thumbnail_url": None, "is_short": False}
        for v in ("b1", "b2", "tb")]
    use(_store(rows, videos=videos, traffic=traffic,
               ingested=_ingested(CH_A) + _ingested(CH_A2)))

    body = _results()
    a, a2 = _cell(body, CH_A)["early"], _cell(body, CH_A2)["early"]
    fleet = body["fleet"]["levers"]["backlinks"]["early"]

    assert a["lift"] == pytest.approx(14 - 0)
    assert a2["lift"] == pytest.approx(28 - 0)
    # Pooled over all five rows, not the mean of the two channel lifts (21).
    assert (fleet["n_treated"], fleet["n_holdout"]) == (3, 2)
    assert fleet["treated_mean_delta"] == pytest.approx((7 + 21 + 28) / 3)
    assert fleet["holdout_mean_delta"] == pytest.approx(0.0)
    assert fleet["lift"] == pytest.approx(56 / 3)
    assert (fleet["post_days_min"], fleet["post_days_max"]) == (3, 7)


# ── scope and writes ────────────────────────────────────────────────────────

def test_a_manager_gets_an_early_read_over_their_channels_only(use):
    rows = [_open_title(CH_A, "pipeline", "treated", "v1", D0),
            _open_title(CH_B, "pipeline", "treated", "v9", D0)]
    use(_store(rows, videos=_videos("v1", "v9"), ingested=_ingested(CH_A) + _ingested(CH_B)))

    fleet = _results(MANAGER_A)["fleet"]["levers"]["title"]["early"]

    assert fleet["n_treated"] == 1


def test_no_request_writes_a_row(use):
    sb = _title_world(reach=_reach("v1", POST, 200, 0.05))
    backlink = _open_backlink(CH_A, "treated", "v1", ["v2"], FRONTIER - timedelta(days=3))
    sb = use(_store(sb.rows("interventions") + [backlink], videos=_videos("v1", "v2"),
                    traffic=sb.rows("video_traffic_source_daily"),
                    reach=sb.rows("video_reach_daily"), ingested=_ingested(CH_A)))

    for params in ({}, {"channel_id": CH_A}, {"lever": "title"}, {"lever": "backlinks"}):
        assert _as(ADMIN).get("/seo/results", params=params).status_code == 200

    assert sb.writes == []
    assert all(r["measurement_result"] is None for r in sb.rows("interventions"))
