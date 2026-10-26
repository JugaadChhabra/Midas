"""Slice 2 · S2.5 — the Short-links page, the tick and the ledger (spec Part 5
S2.5, Part 2 §1.4, §2.5, P4; #91).

The real router, interventions.record and rows paging run against
FakeSupabase. Nothing here talks to YouTube: there is nothing to talk to.
"""
import csv
import io
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import interventions, main, short_links
from app.status_vocab import ALL_SHORT_LINK_STATUSES
from tests.fakes import FakeSupabase

CH, OTHER = "c1", "c2"
CHANNEL_HTML = Path(__file__).resolve().parent.parent / "app" / "static" / "channel.html"


def video(video_id, channel=CH, is_short=False):
    return {"id": video_id, "channel_id": channel, "title": f"Title {video_id}",
            "privacy_status": "public", "is_short": is_short}


def rec(id_, short, target, rank, *, status="pending", feed_views=10, channel=CH, **kw):
    return {"id": id_, "channel_id": channel, "short_id": short, "target_video_id": target,
            "rank": rank, "similarity": 0.9 - rank / 100, "impressions": 1000 * rank,
            "feed_views": feed_views, "decision_log_id": None, "status": status,
            "decided_at": None, "seen_at": None, "intervention_id": None,
            "created_at": "2026-10-26T10:30:00+00:00", **kw}


def short_with_three(short, first_id, **kw):
    return [rec(first_id + i, short, f"{short}-t{i + 1}", i + 1, **kw) for i in range(3)]


@contextmanager
def db(recs=(), videos=(), stored_interventions=()):
    tables = {"short_link_recommendations": list(recs), "videos": list(videos),
              "interventions": list(stored_interventions)}
    sb = FakeSupabase(tables, serial=("interventions",))
    with patch.object(short_links, "supabase", return_value=sb), \
         patch.object(interventions, "supabase", return_value=sb):
        yield sb, TestClient(main.app)


def status_of(sb) -> dict:
    return {r["id"]: r["status"] for r in sb.rows("short_link_recommendations")}


def intervention_writes(sb) -> list:
    return [w for w in sb.writes if w[0] == "interventions"]


# ── the tick ─────────────────────────────────────────────────────────────

def test_set_writes_one_human_short_link_intervention_and_marks_the_others_not_chosen():
    with db(short_with_three("s1", 1) + short_with_three("s2", 4)) as (sb, client):
        r = client.post("/short-links/2/set")
    assert r.status_code == 200
    [row] = sb.rows("interventions")
    assert {k: row[k] for k in ("video_id", "channel_id", "lever", "origin", "arm", "status",
                                "applied_at", "ledger_key")} == {
        "video_id": "s1-t2", "channel_id": CH, "lever": "short_link", "origin": "human",
        "arm": "n/a", "status": "applied", "applied_at": None, "ledger_key": "short_link:s1:s1-t2"}
    assert row["payload"] == {"short_id": "s1", "target_video_id": "s1-t2",
                              "recommendation_id": 2, "timing": "ticked"}
    assert row["detected_at"]
    assert status_of(sb) == {1: "not_chosen", 2: "set", 3: "not_chosen",
                             4: "pending", 5: "pending", 6: "pending"}
    stored = {r["id"]: r for r in sb.rows("short_link_recommendations")}
    assert stored[2]["intervention_id"] == row["id"] and stored[2]["decided_at"]
    assert stored[1]["decided_at"] and stored[4]["decided_at"] is None
    assert r.json()["intervention_id"] == row["id"] and r.json()["recorded"] is True
    assert r.json()["recommendation"]["status"] == "set"


def test_a_second_tick_of_the_same_pair_is_a_no_op():
    with db(short_with_three("s1", 1)) as (sb, client):
        client.post("/short-links/2/set")
        writes = len(sb.writes)
        again = client.post("/short-links/2/set")
    assert again.status_code == 200 and again.json()["recorded"] is False
    assert len(sb.writes) == writes
    assert len(sb.rows("interventions")) == 1


def test_a_pair_already_in_the_ledger_is_linked_not_recorded_twice():
    """A tick after S2.6 inferred the link from the traffic (same ledger key),
    or a retry after a tick that died between the ledger and the row."""
    inferred = {"id": 40, "video_id": "s1-t1", "channel_id": CH, "lever": "short_link",
                "origin": "human", "arm": "n/a", "status": "applied",
                "ledger_key": "short_link:s1:s1-t1"}
    with db(short_with_three("s1", 1), stored_interventions=[inferred]) as (sb, client):
        r = client.post("/short-links/1/set")
    assert r.json()["recorded"] is False and r.json()["intervention_id"] == 40
    assert len(sb.rows("interventions")) == 1
    assert {r["id"]: r["intervention_id"] for r in sb.rows("short_link_recommendations")}[1] == 40


def test_changing_a_shorts_target_moves_set_and_records_a_new_intervention():
    with db(short_with_three("s1", 1)) as (sb, client):
        client.post("/short-links/1/set")
        r = client.post("/short-links/3/set")
    assert r.status_code == 200 and r.json()["recorded"] is True
    assert status_of(sb) == {1: "not_chosen", 2: "not_chosen", 3: "set"}
    keys = sorted(i["ledger_key"] for i in sb.rows("interventions"))
    assert keys == ["short_link:s1:s1-t1", "short_link:s1:s1-t3"]
    # The earlier link's intervention stays as it was: the ledger records what
    # the team did, and they did set it for a while.
    assert {i["status"] for i in sb.rows("interventions")} == {"applied"}


def test_setting_an_earlier_target_back_records_a_new_period():
    """A, then B, then A again: three interventions, the second period of A
    under its own key, so it is measured from its own tick."""
    with db(short_with_three("s1", 1)) as (sb, client):
        first = client.post("/short-links/1/set").json()
        client.post("/short-links/2/set")
        back = client.post("/short-links/1/set").json()
        again = client.post("/short-links/1/set").json()
    assert back["recorded"] is True and back["intervention_id"] != first["intervention_id"]
    assert again["recorded"] is False and again["intervention_id"] == back["intervention_id"]
    keys = [i["ledger_key"] for i in sb.rows("interventions")]
    assert keys == ["short_link:s1:s1-t1", "short_link:s1:s1-t2", "short_link:s1:s1-t1:2"]
    assert status_of(sb) == {1: "set", 2: "not_chosen", 3: "not_chosen"}


def test_a_pair_seen_in_the_traffic_then_ticked_is_still_linked_not_a_new_period():
    stored = [{"id": 40, "ledger_key": "short_link:s1:s1-t1", "video_id": "s1-t1",
               "channel_id": CH, "lever": "short_link", "origin": "human", "arm": "n/a",
               "status": "applied", "payload": {"short_id": "s1", "timing": "inferred_from_traffic"}}]
    with db(short_with_three("s1", 1), stored_interventions=stored) as (sb, client):
        r = client.post("/short-links/1/set").json()
    assert r["recorded"] is False and r["intervention_id"] == 40
    assert len(sb.rows("interventions")) == 1


def test_a_recommendation_without_a_channel_takes_the_shorts():
    recs = short_with_three("s1", 1, channel=None)
    with db(recs, [video("s1", is_short=True)]) as (sb, client):
        r = client.post("/short-links/1/set")
    assert r.status_code == 200
    assert [i["channel_id"] for i in sb.rows("interventions")] == [CH]


def test_set_keeps_a_dismissed_sibling_dismissed():
    recs = short_with_three("s1", 1)
    recs[0]["status"] = "dismissed"
    with db(recs) as (sb, client):
        client.post("/short-links/2/set")
    assert status_of(sb) == {1: "dismissed", 2: "set", 3: "not_chosen"}


def test_dismiss_writes_no_intervention():
    with db(short_with_three("s1", 1)) as (sb, client):
        r = client.post("/short-links/2/dismiss")
    assert r.status_code == 200 and r.json()["recommendation"]["status"] == "dismissed"
    assert status_of(sb) == {1: "pending", 2: "dismissed", 3: "pending"}
    assert intervention_writes(sb) == []
    assert {r["id"]: r["decided_at"] for r in sb.rows("short_link_recommendations")}[2]


def test_a_set_link_is_not_dismissed():
    """Dismissing the target the team set would leave the ledger saying the
    link is on the Short while the page says it was wrong."""
    with db(short_with_three("s1", 1)) as (sb, client):
        client.post("/short-links/1/set")
        r = client.post("/short-links/1/dismiss")
    assert r.status_code == 409
    assert status_of(sb)[1] == "set"


def test_unknown_recommendation_ids_are_404():
    with db(short_with_three("s1", 1)) as (sb, client):
        set_ = client.post("/short-links/99/set")
        dismiss = client.post("/short-links/99/dismiss")
    assert (set_.status_code, dismiss.status_code) == (404, 404)
    assert sb.writes == []


def test_nothing_here_reaches_youtube():
    source = Path(short_links.__file__).read_text()
    assert "youtube_client" not in source


# ── the list ─────────────────────────────────────────────────────────────

def _videos_for(recs):
    ids = {r["short_id"] for r in recs}
    return ([video(s, is_short=True) for s in sorted(ids)]
            + [video(r["target_video_id"]) for r in recs])


def test_the_list_is_shorts_with_their_recommendations_pending_first():
    recs = (short_with_three("s1", 1, feed_views=50, status="not_chosen")
            + short_with_three("s2", 4, feed_views=5)
            + short_with_three("s3", 7, feed_views=20)
            + [rec(20, "x1", "x1-t1", 1, channel=OTHER)])
    recs[1]["status"] = "set"
    with db(recs, _videos_for(recs)) as (_, client):
        body = client.get(f"/channels/{CH}/short-links").json()
    # Shorts with a pending row first, then the rest, each by feed views.
    assert [s["short_id"] for s in body["shorts"]] == ["s3", "s2", "s1"]
    s3 = body["shorts"][0]
    assert s3["title"] == "Title s3" and s3["feed_views"] == 20
    assert s3["youtube_url"] == "https://www.youtube.com/shorts/s3"
    assert s3["studio_url"] == "https://studio.youtube.com/video/s3/edit"
    assert [t["rank"] for t in s3["recommendations"]] == [1, 2, 3]
    first = s3["recommendations"][0]
    assert {k: first[k] for k in ("id", "target_video_id", "title", "youtube_url", "rank",
                                  "similarity", "impressions", "status")} == {
        "id": 7, "target_video_id": "s3-t1", "title": "Title s3-t1",
        "youtube_url": "https://www.youtube.com/watch?v=s3-t1", "rank": 1,
        "similarity": 0.89, "impressions": 1000, "status": "pending"}
    assert (body["limit"], body["offset"], body["next_offset"]) == (100, 0, None)


def test_the_list_pages_by_short():
    recs = [r for i in range(5) for r in short_with_three(f"s{i}", 1 + 3 * i, feed_views=10 - i)]
    with db(recs, _videos_for(recs)) as (_, client):
        first = client.get(f"/channels/{CH}/short-links", params={"limit": 2}).json()
        second = client.get(f"/channels/{CH}/short-links",
                            params={"limit": 2, "offset": first["next_offset"]}).json()
        last = client.get(f"/channels/{CH}/short-links",
                          params={"limit": 2, "offset": second["next_offset"]}).json()
        too_big = client.get(f"/channels/{CH}/short-links", params={"limit": 1001})
    ids = [s["short_id"] for page in (first, second, last) for s in page["shorts"]]
    assert ids == ["s0", "s1", "s2", "s3", "s4"]
    assert (first["next_offset"], second["next_offset"], last["next_offset"]) == (2, 4, None)
    assert all(len(s["recommendations"]) == 3 for s in first["shorts"])
    assert too_big.status_code == 422


def test_the_status_filter_keeps_the_matching_rows_and_their_shorts():
    recs = short_with_three("s1", 1) + short_with_three("s2", 4)
    recs[0]["status"] = "dismissed"
    with db(recs, _videos_for(recs)) as (_, client):
        dismissed = client.get(f"/channels/{CH}/short-links", params={"status": "dismissed"}).json()
        pending = client.get(f"/channels/{CH}/short-links", params={"status": "pending"}).json()
        bad = client.get(f"/channels/{CH}/short-links", params={"status": "nope"})
    assert [(s["short_id"], [t["id"] for t in s["recommendations"]])
            for s in dismissed["shorts"]] == [("s1", [1])]
    assert [(s["short_id"], [t["id"] for t in s["recommendations"]])
            for s in pending["shorts"]] == [("s1", [2, 3]), ("s2", [4, 5, 6])]
    assert bad.status_code == 400


def test_csv_is_the_same_page_one_line_per_recommendation():
    recs = short_with_three("s1", 1, feed_views=9) + short_with_three("s2", 4, feed_views=3)
    with db(recs, _videos_for(recs)) as (_, client):
        r = client.get(f"/channels/{CH}/short-links", params={"format": "csv", "limit": 1})
        bad = client.get(f"/channels/{CH}/short-links", params={"format": "xml"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert f"short-links-{CH}.csv" in r.headers["content-disposition"]
    lines = list(csv.DictReader(io.StringIO(r.text)))
    assert [(l["short_id"], l["rank"], l["target_video_id"]) for l in lines] == [
        ("s1", "1", "s1-t1"), ("s1", "2", "s1-t2"), ("s1", "3", "s1-t3")]
    assert lines[0]["studio_url"] == "https://studio.youtube.com/video/s1/edit"
    assert lines[0]["target_title"] == "Title s1-t1" and lines[0]["status"] == "pending"
    assert bad.status_code == 422


def test_csv_titles_that_a_spreadsheet_would_run_as_formulas_are_escaped():
    recs = short_with_three("s1", 1)
    videos = _videos_for(recs)
    for v in videos:
        if v["id"] == "s1":
            v["title"] = "=HYPERLINK(\"x\")"
        if v["id"] == "s1-t1":
            v["title"] = "-5 little ducks"
        if v["id"] == "s1-t2":
            v["title"] = "Five = five"
    with db(recs, videos) as (_, client):
        r = client.get(f"/channels/{CH}/short-links", params={"format": "csv"})
        js = client.get(f"/channels/{CH}/short-links").json()
    lines = list(csv.DictReader(io.StringIO(r.text)))
    assert {l["short_title"] for l in lines} == {"'=HYPERLINK(\"x\")"}
    assert [l["target_title"] for l in lines][:2] == ["'-5 little ducks", "Five = five"]
    # JSON is not a spreadsheet: titles stay as they are there.
    assert js["shorts"][0]["title"] == "=HYPERLINK(\"x\")"


# ── the card ─────────────────────────────────────────────────────────────

def test_the_card_reads_fields_the_endpoint_returns():
    """A JS-free check of the card: it fetches this endpoint, posts to the two
    actions, links the CSV, and every field it reads off a Short or a
    recommendation is one the endpoint returns."""
    html = CHANNEL_HTML.read_text()
    assert 'id="sl-card"' in html
    assert "/short-links`" in html or "/short-links?" in html
    assert "fetch(`/short-links/${id}/${action}`, { method: 'POST' })" in html
    assert "'set')" in html and "'dismiss')" in html
    assert "format=csv" in html

    recs = short_with_three("s1", 1)
    with db(recs, _videos_for(recs)) as (_, client):
        body = client.get(f"/channels/{CH}/short-links").json()
    short_keys = set(body["shorts"][0])
    rec_keys = set(body["shorts"][0]["recommendations"][0])
    card = html[html.index("// ── Short links"):html.index("// ── end Short links")]
    assert set(re.findall(r"\bs\.(\w+)", card)) <= short_keys
    assert set(re.findall(r"\bt\.(\w+)", card)) <= rec_keys
    assert {"short_id", "studio_url", "recommendations"} <= set(re.findall(r"\bs\.(\w+)", card))
    assert {"id", "status", "title"} <= set(re.findall(r"\bt\.(\w+)", card))
    assert {"shorts", "next_offset"} <= set(body)
    # The card's status labels are the vocabulary's, no more, no fewer.
    labels = card[card.index("const SL_STATUS"):card.index("};", card.index("const SL_STATUS"))]
    assert set(re.findall(r"^\s*(\w+):", labels, re.M)) == ALL_SHORT_LINK_STATUSES
