"""The Results page's CSV exports (SEO results 08, #175), through the HTTP seam:
``GET /seo/results.csv`` and ``GET /seo/results/changes.csv`` equal their JSON twins.
"""
import csv
import io

from tests.test_seo_results import (  # noqa: F401  (the `use` fixture)
    ADMIN, CH_A, CH_B, EXEC, MANAGER_A, _as, _iv, _store, _verdict, use,
)
from tests.test_seo_results_changes import _videos


def _rows(r):
    assert r.status_code == 200, r.text
    return list(csv.DictReader(io.StringIO(r.text)))


def _seed():
    rows = [_iv(CH_A, "treated", "judged", video="v1", delta=4.0),
            _iv(CH_A, "holdout", "holdout", video="v2", applied=False),
            _iv(CH_B, "treated", "judged", video="v3", delta=1.0)]
    return _store(rows, [_verdict(CH_A, "2026-11-09", lift=3.0, cumulative=3.0)], videos=_videos())


def test_results_csv_equals_the_json_and_names_the_file(use):
    use(_seed())
    client = _as(ADMIN)
    body = client.get("/seo/results").json()
    r = client.get("/seo/results.csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="seo-results-')
    assert r.headers["content-disposition"].endswith('.csv"')
    lines = _rows(r)
    for c in body["channels"]:
        for lever, cell in c["levers"].items():
            line = next(x for x in lines if x["channel_id"] == c["id"] and x["lever"] == lever)
            assert line["channel"] == c["name"]
            if cell.get("counts"):
                assert line["written"] == str(cell["counts"]["written"])
            if cell.get("lift") is not None:
                assert float(line["lift"]) == cell["lift"]
    fleet = [x for x in lines if x["channel_id"] == ""]
    assert {x["lever"] for x in fleet} == set(body["fleet"]["levers"])
    assert fleet[0]["channel"] == "All channels"


def test_results_csv_keeps_the_filters_and_scoping(use):
    use(_seed())
    only = _rows(_as(ADMIN).get("/seo/results.csv", params={"channel_id": CH_A, "lever": "backlinks"}))
    assert {(x["channel_id"], x["lever"]) for x in only} == {(CH_A, "backlinks"), ("", "backlinks")}
    mine = _rows(_as(MANAGER_A).get("/seo/results.csv"))
    assert CH_B not in {x["channel_id"] for x in mine}
    assert _as(MANAGER_A).get("/seo/results.csv", params={"channel_id": CH_B}).status_code == 404
    assert _as(ADMIN).get("/seo/results.csv", params={"lever": "nope"}).status_code == 400


def test_changes_csv_lists_every_change_unpaged_and_matches_the_json(use):
    sb = use(_seed())
    client = _as(ADMIN)
    json_rows = client.get("/seo/results/changes",
                           params={"channel_id": CH_A, "lever": "backlinks"}).json()["changes"]
    r = client.get("/seo/results/changes.csv", params={"channel_id": CH_A, "lever": "backlinks"})
    assert r.headers["content-disposition"].startswith('attachment; filename="seo-changes-')
    lines = _rows(r)
    assert [int(x["id"]) for x in lines] == [c["id"] for c in json_rows]
    assert [x["video_title"] for x in lines] == [c["video"]["title"] for c in json_rows]
    assert len(_rows(client.get("/seo/results/changes.csv"))) >= len(lines)
    assert _as(ADMIN).get("/seo/results/changes.csv", params={"arm": "x"}).status_code == 400


def test_changes_csv_scoping_and_formula_escaping(use):
    videos = _videos()
    videos[0]["title"] = "=HYPERLINK(\"http://x\")"
    use(_store([_iv(CH_A, "treated", "judged", video="v1", delta=1.0),
                _iv(CH_B, "treated", "judged", video="v3", delta=1.0)], videos=videos))
    lines = _rows(_as(MANAGER_A).get("/seo/results/changes.csv"))
    assert {x["channel_id"] for x in lines} == {CH_A}
    assert lines[0]["video_title"].startswith("'=")
    assert _as(MANAGER_A).get("/seo/results/changes.csv", params={"channel_id": CH_B}).status_code == 404
    assert _as(EXEC).get("/seo/results/changes.csv").status_code == 200
