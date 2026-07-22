from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_cut_endpoint_enqueues():
    with patch("app.shorts.routes.enqueue_language_jobs", return_value=7) as enq:
        resp = client.post("/shorts/cut", json={"language": "hindi"})
    assert resp.status_code == 200
    assert resp.json() == {"language": "HINDI", "enqueued": 7}
    enq.assert_called_once_with("HINDI")


def test_cut_endpoint_unknown_language_is_400():
    with patch("app.shorts.routes.enqueue_language_jobs", side_effect=ValueError("nope")):
        resp = client.post("/shorts/cut", json={"language": "KLINGON"})
    assert resp.status_code == 400


def test_languages_endpoint_lists_counts():
    with patch("app.shorts.routes.list_source_languages", return_value=["HINDI", "TAMIL"]), \
         patch("app.shorts.routes.uncut_count", side_effect=[3, 0]):
        resp = client.get("/shorts/languages")
    assert resp.status_code == 200
    assert resp.json() == [{"language": "HINDI", "uncut": 3}, {"language": "TAMIL", "uncut": 0}]
