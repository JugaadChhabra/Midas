"""A video's transcript is fetched from YouTube once, then read from the database.

`fetch_transcript` makes two network calls (list, then fetch) and nothing cached
the result, so the same text was re-downloaded by every path that touched the
video: the audit, the embedding pass, each re-audit of a quarantined row, and once
per shadow audit. Shadow audits are the sharpest case — they replay a candidate
prompt over videos that were already audited, so the transcript is guaranteed to
have been fetched before.

Two behaviours carry the weight here:

  * The negative cache. A video with captions disabled has no transcript and never
    will within a run; without recording that, it gets re-probed on every audit
    forever — the exact cost this is meant to remove, on the videos where there is
    nothing to gain.

  * Never failing the audit. The cache is an optimisation. A broken table, a
    missing migration, or a write that races another worker must degrade to the
    old behaviour (fetch from YouTube) rather than take down auditing.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import transcripts


@pytest.fixture
def store():
    """A fake video_transcripts table backed by a dict."""
    rows: dict[str, dict] = {}

    def _select(video_id):
        return rows.get(video_id)

    def _upsert(row):
        rows[row["video_id"]] = row

    with patch.object(transcripts, "_cache_read", side_effect=_select) as r, \
         patch.object(transcripts, "_cache_write", side_effect=_upsert) as w:
        yield {"rows": rows, "read": r, "write": w}


@pytest.fixture
def youtube():
    """Stub the network fetch so we can count calls to it."""
    with patch.object(transcripts, "_fetch_from_youtube",
                      return_value=("मछली जल की रानी है", "hi")) as m:
        yield m


def test_first_call_fetches_and_stores(store, youtube):
    assert transcripts.fetch_transcript("v1") == ("मछली जल की रानी है", "hi")
    youtube.assert_called_once()
    assert store["rows"]["v1"]["available"] is True
    assert store["rows"]["v1"]["text"] == "मछली जल की रानी है"


def test_second_call_does_not_touch_youtube(store, youtube):
    transcripts.fetch_transcript("v1")
    transcripts.fetch_transcript("v1")
    transcripts.fetch_transcript("v1")
    youtube.assert_called_once()          # three audits, one download


def test_a_video_with_no_transcript_is_negative_cached(store):
    """The whole point: stop re-probing videos that have nothing to give."""
    with patch.object(transcripts, "_fetch_from_youtube",
                      return_value=(None, None)) as yt:
        assert transcripts.fetch_transcript("v2") == (None, None)
        assert transcripts.fetch_transcript("v2") == (None, None)
        yt.assert_called_once()
    assert store["rows"]["v2"]["available"] is False
    assert store["rows"]["v2"]["text"] is None


def test_a_stale_negative_is_re_probed(store):
    """A video can gain auto-captions later, so 'unavailable' must not be forever."""
    store["rows"]["v3"] = {
        "video_id": "v3", "text": None, "lang": None, "available": False,
        "fetched_at": "2020-01-01T00:00:00+00:00",
    }
    with patch.object(transcripts, "_fetch_from_youtube",
                      return_value=("now it has one", "hi")) as yt:
        assert transcripts.fetch_transcript("v3") == ("now it has one", "hi")
        yt.assert_called_once()
    assert store["rows"]["v3"]["available"] is True


def test_a_fresh_negative_is_not_re_probed(store):
    from datetime import datetime, timezone

    store["rows"]["v4"] = {
        "video_id": "v4", "text": None, "lang": None, "available": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    with patch.object(transcripts, "_fetch_from_youtube") as yt:
        assert transcripts.fetch_transcript("v4") == (None, None)
        yt.assert_not_called()


def test_a_broken_cache_read_still_returns_a_transcript(youtube):
    """Degrade to the old behaviour — an unmigrated database must not stop audits."""
    with patch.object(transcripts, "_cache_read", side_effect=RuntimeError("no table")), \
         patch.object(transcripts, "_cache_write"):
        assert transcripts.fetch_transcript("v5") == ("मछली जल की रानी है", "hi")
    youtube.assert_called_once()


def test_a_broken_cache_write_still_returns_a_transcript(youtube):
    with patch.object(transcripts, "_cache_read", return_value=None), \
         patch.object(transcripts, "_cache_write", side_effect=RuntimeError("readonly")):
        assert transcripts.fetch_transcript("v6") == ("मछली जल की रानी है", "hi")


def test_channel_id_is_passed_through_for_the_captions_fallback(store):
    """fetch_transcript's captions-API fallback needs channel_id for OAuth."""
    with patch.object(transcripts, "_fetch_from_youtube",
                      return_value=("t", "hi")) as yt:
        transcripts.fetch_transcript("v7", channel_id="ch1")
    assert yt.call_args.kwargs.get("channel_id") == "ch1" or yt.call_args[0][1] == "ch1"
