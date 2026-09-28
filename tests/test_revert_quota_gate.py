"""A10: manual revert checks the quota ledger before it writes to YouTube.

A revert is a videos.update (50u). Without the gate it only learned the day was
spent from YouTube's quotaExceeded, surfaced as a 500.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from tests.fakes import FakeSupabase

import app.audits as audits
from app import quota


def _store():
    return FakeSupabase({
        "audits": [{"id": 1, "video_id": "v1", "status": "applied",
                    "title_before": "old", "description_before": "old desc",
                    "tags_before": ["t"], "measurement_status": "not_applicable"}],
        "videos": [{"id": "v1", "channel_id": "UC1", "title": "new",
                    "description": "new desc", "category_id": "1"}],
        "channels": [{"id": "UC1", "default_language": "hi"}],
    })


def test_revert_that_cannot_afford_the_write_returns_409_and_makes_no_call():
    sb = _store()
    with patch.object(audits, "supabase", return_value=sb), \
         patch.object(audits.settings, "DRY_RUN", False), \
         patch.object(quota, "units_remaining", return_value=12), \
         patch.object(quota, "can_afford", return_value=False) as afford, \
         patch.object(audits, "youtube_for_channel") as yt, \
         patch.object(audits, "yt_videos_update") as update:
        with pytest.raises(HTTPException) as exc:
            audits.revert_audit(1)
    assert exc.value.status_code == 409
    assert "12" in str(exc.value.detail)                    # the remaining units
    assert "quota_insufficient" in str(exc.value.detail)
    afford.assert_called_once_with(quota.cost(quota.Op.VIDEOS_UPDATE))
    yt.assert_not_called()
    update.assert_not_called()
    assert sb.rows("audits")[0]["status"] == "applied"      # nothing recorded as reverted
    assert sb.writes == []


def test_revert_that_can_afford_the_write_pushes_it():
    sb = _store()
    with patch.object(audits, "supabase", return_value=sb), \
         patch.object(audits.settings, "DRY_RUN", False), \
         patch.object(quota, "can_afford", return_value=True), \
         patch.object(audits, "youtube_for_channel") as yt, \
         patch.object(audits, "yt_videos_update") as update:
        audits.revert_audit(1)
    update.assert_called_once()
    assert sb.rows("audits")[0]["status"] == "reverted"
