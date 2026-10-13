"""#57: a Reporting API report download retries a dropped connection before the
report counts as failed, and keeps its one-time token refresh on a 401.

Tested at the download function: only the HTTP client it opens and the creds'
refresh are faked. No sleeping, no network.
"""
from unittest.mock import patch

import httpx
import pytest
from google.auth.exceptions import TransportError

import app.reporting_client as rc

URL = "https://youtubereporting.googleapis.com/v1/media/CHANNEL/x/jobs/j/reports/r?alt=media"


def _resp(status: int, body: str = "") -> httpx.Response:
    return httpx.Response(status, text=body, request=httpx.Request("GET", URL))


def _dropped() -> httpx.RemoteProtocolError:
    return httpx.RemoteProtocolError("Server disconnected without sending a response.")


class _Creds:
    def __init__(self, refresh_outcomes=()):
        self.token = "t0"
        self.refreshes = 0
        self._outcomes = list(refresh_outcomes)

    def refresh(self, _request):
        self.refreshes += 1
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        self.token = f"t{self.refreshes}"


def _download(answers, creds=None):
    """Run the real download_report_csv. `answers`: one per GET, in order, each an
    httpx.Response to return or an exception to raise."""
    answers = list(answers)
    sent = []
    creds = creds or _Creds()

    class _Client:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers):
            sent.append(headers["Authorization"])
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a

    out = {"sent": sent, "creds": creds}
    with patch.object(rc.httpx, "Client", _Client), \
         patch.object(rc, "_sleep") as sleep, \
         patch.object(rc, "_log_quota") as quota:
        try:
            out["body"] = rc.download_report_csv(rc.ReportingHandle(None, creds), "UC1", URL)
        except Exception as e:
            out["error"] = e
    out["sleeps"] = [c.args[0] for c in sleep.call_args_list]
    out["quota"] = [c.args for c in quota.call_args_list]
    return out


def test_first_try_succeeds_without_pausing():
    r = _download([_resp(200, "csv")])
    assert r["body"] == "csv" and len(r["sent"]) == 1 and r["sleeps"] == []
    assert r["quota"] == [("UC1", "youtubeReporting.media.download", True)]


def test_a_dropped_connection_is_retried_and_the_body_returned(caplog):
    r = _download([_dropped(), _resp(200, "csv")])
    assert r["body"] == "csv" and len(r["sent"]) == 2
    assert r["sleeps"] == [1.0]
    assert "attempt 1/3" in caplog.text and "UC1" in caplog.text
    assert r["quota"] == [("UC1", "youtubeReporting.media.download", True)]


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("boom"), httpx.ConnectTimeout("slow"), httpx.ReadTimeout("slow"),
])
def test_other_connection_failures_are_retried(exc):
    assert _download([exc, _resp(200, "csv")])["body"] == "csv"


def test_dropping_on_every_attempt_fails_after_three_tries():
    r = _download([_dropped(), _dropped(), _dropped()])
    assert isinstance(r["error"], httpx.RemoteProtocolError)
    assert len(r["sent"]) == rc.DOWNLOAD_ATTEMPTS == 3
    assert r["sleeps"] == [1.0, 2.0]
    assert r["quota"] == [("UC1", "youtubeReporting.media.download", False)]


@pytest.mark.parametrize("status", [403, 404, 500])
def test_an_http_error_answer_fails_at_once(status):
    r = _download([_resp(status)])
    assert isinstance(r["error"], httpx.HTTPStatusError)
    assert len(r["sent"]) == 1 and r["sleeps"] == []
    assert r["quota"] == [("UC1", "youtubeReporting.media.download", False)]


def test_a_401_refreshes_once_and_retries_with_the_new_token():
    r = _download([_resp(401), _resp(200, "csv")])
    assert r["body"] == "csv" and r["creds"].refreshes == 1
    assert r["sent"] == ["Bearer t0", "Bearer t1"]
    assert r["sleeps"] == []


def test_a_second_401_after_the_refresh_fails():
    r = _download([_resp(401), _resp(401)])
    assert isinstance(r["error"], httpx.HTTPStatusError)
    assert r["creds"].refreshes == 1 and len(r["sent"]) == 2


def test_a_dropped_connection_during_the_refresh_is_retried():
    creds = _Creds([TransportError("('Connection aborted.', RemoteDisconnected('Remote end closed'))")])
    r = _download([_resp(401), _resp(401), _resp(200, "csv")], creds)
    assert r["body"] == "csv"
    assert creds.refreshes == 2          # the failed refresh, then the one that worked
    assert r["sleeps"] == [1.0]


def test_a_blip_and_a_401_in_one_download_both_recover():
    r = _download([_dropped(), _resp(401), _resp(200, "csv")])
    assert r["body"] == "csv" and r["creds"].refreshes == 1 and r["sleeps"] == [1.0]
