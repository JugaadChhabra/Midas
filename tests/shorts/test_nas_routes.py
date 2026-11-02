from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_cut_endpoint_enqueues():
    with patch("app.shorts.routes.list_source_languages", return_value=["HINDI"]), \
         patch("app.shorts.routes.enqueue_language_jobs", return_value=7) as enq:
        resp = client.post("/shorts/cut", json={"language": "hindi"})
    assert resp.status_code == 200
    assert resp.json() == {"language": "HINDI", "enqueued": 7}
    enq.assert_called_once_with("HINDI")


def test_cut_endpoint_uses_the_folders_real_name():
    # The route used to uppercase and compare exactly, so a mixed-case folder
    # failed with "Unknown NAS language folder: '3D SERIES HINDI'".
    with patch("app.shorts.routes.list_source_languages",
               return_value=["HINDI", "3D Series Hindi"]), \
         patch("app.shorts.routes.enqueue_language_jobs", return_value=2) as enq:
        resp = client.post("/shorts/cut", json={"language": "3D SERIES  HINDI"})
    assert resp.status_code == 200
    assert resp.json() == {"language": "3D Series Hindi", "enqueued": 2}
    enq.assert_called_once_with("3D Series Hindi")


def test_cut_endpoint_unknown_language_is_400_and_lists_the_folders():
    with patch("app.shorts.routes.list_source_languages", return_value=["HINDI"]), \
         patch("app.shorts.routes.enqueue_language_jobs") as enq:
        resp = client.post("/shorts/cut", json={"language": "KLINGON"})
    assert resp.status_code == 400
    assert "'HINDI'" in resp.json()["detail"]
    enq.assert_not_called()


def test_cut_endpoint_enqueue_error_is_400():
    with patch("app.shorts.routes.list_source_languages", return_value=["HINDI"]), \
         patch("app.shorts.routes.enqueue_language_jobs", side_effect=ValueError("nope")):
        resp = client.post("/shorts/cut", json={"language": "HINDI"})
    assert resp.status_code == 400


def test_languages_endpoint_lists_counts():
    with patch("app.shorts.routes.list_source_languages", return_value=["HINDI", "TAMIL"]), \
         patch("app.shorts.routes.uncut_count", side_effect=[3, 0]):
        resp = client.get("/shorts/languages")
    assert resp.status_code == 200
    assert resp.json() == [{"language": "HINDI", "uncut": 3}, {"language": "TAMIL", "uncut": 0}]
