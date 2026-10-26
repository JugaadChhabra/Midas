"""Slice 2 · S2.6 — Short links seen in the traffic (spec Part 5 S2.6, Part 2
§1.4; #92).

The real detect, interventions.record, reach.coverage and rows paging run
against FakeSupabase. Nothing here talks to YouTube.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

from app import interventions, lever_measurement, reach, short_links
from app.config import settings
from tests.fakes import FakeSupabase
from tests.test_backlink_candidates import postgrest_cap

CH = "UCmarathi1"
S1, S2, LONG, T1, T2 = "short000001", "short000002", "longVid0001", "tgtVideo001", "tgtVideo002"
TRAFFIC = "channel_traffic_source_a3"
LAST = date(2026, 10, 20)


def day(n: int) -> str:
    """LAST − n, as an ISO data-day."""
    return (LAST - timedelta(days=n)).isoformat()


def ledger(days: int = 40) -> list[dict]:
    return [{"report_id": f"r{n}", "channel_id": CH, "report_type": TRAFFIC,
             "data_date": day(n)} for n in range(days)]


def related(target, short, n, views=1, source_type=32) -> dict:
    return {"video_id": target, "channel_id": CH, "date": day(n), "source_type": source_type,
            "source_detail": short, "views": views}


VIDEOS = [
    {"id": S1, "channel_id": CH, "is_short": True},
    {"id": S2, "channel_id": CH, "is_short": True},
    {"id": LONG, "channel_id": CH, "is_short": False},
    {"id": T1, "channel_id": CH, "is_short": False},
    {"id": T2, "channel_id": CH, "is_short": False},
]


def rec(id_, short, target, **kw) -> dict:
    return {"id": id_, "channel_id": CH, "short_id": short, "target_video_id": target,
            "rank": 1, "similarity": 0.9, "status": "pending", "seen_at": None,
            "intervention_id": None, **kw}


@contextmanager
def db(traffic, recs=(), stored=(), ingested=None):
    sb = FakeSupabase({"video_traffic_source_daily": list(traffic),
                       "reporting_reports_ingested": ledger() if ingested is None else ingested,
                       "videos": VIDEOS, "short_link_recommendations": list(recs),
                       "interventions": list(stored)},
                      serial=("interventions",))
    with patch.object(short_links, "supabase", return_value=sb), \
         patch.object(interventions, "supabase", return_value=sb), \
         patch.object(reach, "supabase", return_value=sb):
        yield sb


def inferred(sb) -> list[dict]:
    return sorted((r for r in sb.rows("interventions")
                   if (r["payload"] or {}).get("timing") == "inferred_from_traffic"),
                  key=lambda r: r["ledger_key"])


def test_a_pair_seen_in_type_32_gets_one_inferred_human_intervention():
    rows = [related(T1, S1, 10, 2), related(T1, S1, 5, 3), related(T1, S1, 3, 0)]
    with db(rows, recs=[rec(1, S1, T1)]) as sb:
        counts = short_links.detect(CH)
    [row] = inferred(sb)
    assert {k: row[k] for k in ("video_id", "channel_id", "lever", "origin", "arm", "status",
                                "applied_at", "ledger_key")} == {
        "video_id": T1, "channel_id": CH, "lever": "short_link", "origin": "human",
        "arm": "n/a", "status": "applied", "applied_at": None,
        "ledger_key": f"short_link:{S1}:{T1}"}
    assert row["payload"] == {"short_id": S1, "target_video_id": T1, "recommended": True,
                              "timing": "inferred_from_traffic"}
    # detected_at: the first data-day with views, which measurement reads back as d0.
    assert lever_measurement.as_of(row) == date.fromisoformat(day(10))
    assert counts == {**counts, "pairs": 1, "attempted": 1, "errored": 0, "inferred": 1, "seen": 1}


def test_seen_at_is_the_first_data_day_with_views_and_is_set_once():
    rows = [related(T1, S1, 10), related(T1, S1, 4)]
    with db(rows, recs=[rec(1, S1, T1), rec(2, S1, T2),
                        rec(3, S2, T1, seen_at="2026-09-01T00:00:00-07:00")]) as sb:
        sb._tables["video_traffic_source_daily"].append(related(T1, S2, 2))
        short_links.detect(CH)
    by_id = {r["id"]: r for r in sb.rows("short_link_recommendations")}
    assert lever_measurement._day(by_id[1]["seen_at"]) == date.fromisoformat(day(10))
    assert by_id[2]["seen_at"] is None                          # no type-32 rows for it
    assert by_id[3]["seen_at"] == "2026-09-01T00:00:00-07:00"   # already seen


def test_an_unrecommended_pair_is_recorded_too_as_not_recommended():
    """The team's own links, recommended or not: the §1.4 benchmark."""
    with db([related(T2, S2, 6)]) as sb:
        short_links.detect(CH)
    [row] = inferred(sb)
    assert row["payload"]["recommended"] is False
    assert row["ledger_key"] == f"short_link:{S2}:{T2}"


def test_a_ticked_pair_is_never_duplicated_and_a_later_tick_is_a_no_op():
    ticked = {"id": 50, "video_id": T1, "channel_id": CH, "lever": "short_link",
              "origin": "human", "arm": "n/a", "status": "applied",
              "ledger_key": f"short_link:{S1}:{T1}",
              "payload": {"short_id": S1, "target_video_id": T1, "recommendation_id": 1,
                          "timing": "ticked"}}
    with db([related(T1, S1, 5), related(T2, S1, 5)],
            recs=[rec(1, S1, T1, status="set", intervention_id=50), rec(2, S1, T2)],
            stored=[ticked]) as sb:
        first = short_links.detect(CH)
        again = short_links.detect(CH)
        rows = sb.rows("interventions")
        assert sorted(r["ledger_key"] for r in rows) == [f"short_link:{S1}:{T1}",
                                                         f"short_link:{S1}:{T2}"]
        assert first["inferred"] == 1 and again["inferred"] == 0
        # The page's tick of the inferred pair links the inferred row.
        from fastapi.testclient import TestClient
        from app import main
        body = TestClient(main.app).post("/short-links/2/set").json()
    assert body["recorded"] is False
    assert body["intervention_id"] == inferred(sb)[0]["id"]
    assert len(sb.rows("interventions")) == 2


def test_only_type_32_from_our_shorts_over_the_latest_28_ingested_days_counts():
    rows = [
        related(T1, LONG, 3),                       # the source is a long video
        related(T1, "notOurs0001", 3),              # not in videos
        related(T1, S1, 3, source_type=7),          # suggested, not related video
        related(T1, S1, 28),                        # outside the 28 ingested days
        related(T1, "", 3),                         # the folded blank bucket
        related("notOurs0002", S1, 3),              # a target not in videos
    ]
    with db(rows) as sb:
        counts = short_links.detect(CH)
    assert counts["pairs"] == 0 and sb.rows("interventions") == []


def test_the_seen_floor_follows_the_setting():
    rows = [related(T1, S1, 5, 1), related(T1, S1, 4, 1), related(T2, S1, 5, 1)]
    with db(rows) as sb, patch.object(settings, "SHORT_LINK_SEEN_MIN_VIEWS", 2):
        short_links.detect(CH)
    assert [r["video_id"] for r in inferred(sb)] == [T1]


def test_no_ingested_traffic_means_nothing_to_detect():
    with db([related(T1, S1, 5)], ingested=[]) as sb:
        assert short_links.detect(CH)["pairs"] == 0
    assert sb.writes == []


def test_a_pair_that_fails_is_counted_and_the_others_still_run():
    real = interventions.record

    def record(**kw):
        if kw["video_id"] == T1:
            raise RuntimeError("boom")
        return real(**kw)

    with db([related(T1, S1, 5), related(T2, S1, 5)]) as sb, \
         patch.object(interventions, "record", side_effect=record):
        counts = short_links.detect(CH)
    assert (counts["attempted"], counts["errored"], counts["inferred"]) == (2, 1, 1)
    assert [r["video_id"] for r in inferred(sb)] == [T2]


def test_reads_are_paged_past_the_row_cap():
    rows = [related(T1, S1, i % 20, 1) for i in range(1400)]
    with db(rows) as sb, postgrest_cap(), patch.object(settings, "SHORT_LINK_SEEN_MIN_VIEWS", 1400):
        short_links.detect(CH)
    assert len(inferred(sb)) == 1
