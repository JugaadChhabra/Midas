"""Read-only live integration tests against the real Supabase project.

These issue SELECTs only — no writes — and skip automatically when no live
credentials are configured. They guard the class of bug fakes can't catch:
query correctness against Supabase's real behavior (notably the 1000-row cap).

Run just these:   pytest -m live
Skip them:        pytest -m "not live"
"""
import pytest

from app.config import settings
from app.channel_audits import audits_for_channel, fetch_all
from app.db import supabase

pytestmark = pytest.mark.live


def _has_creds() -> bool:
    return bool((settings.SUPABASE_URL or "").strip() and (settings.SUPABASE_SERVICE_KEY or "").strip())


@pytest.fixture(scope="module")
def sb():
    if not _has_creds():
        pytest.skip("no live Supabase credentials in the environment")
    return supabase()


def _channel_ids(sb):
    return [c["id"] for c in (sb.table("channels").select("id").execute().data or [])]


def test_accessor_scopes_every_row_to_the_channel(sb):
    """Every row the accessor returns belongs to the requested channel — i.e. the
    videos!inner(channel_id) join actually scopes, not just decorates."""
    for cid in _channel_ids(sb):
        rows = (
            audits_for_channel(cid, "id,video_id", video_columns="channel_id")
            .limit(25).execute()
        ).data or []
        if not rows:
            continue
        assert all((r.get("videos") or {}).get("channel_id") == cid for r in rows)
        return
    pytest.skip("no channel has any audits to scope-check")


def test_fetch_all_beats_the_1000_row_cap(sb):
    """Regression guard for the channel-audits truncation bug: on a channel with
    >1000 applied audits, a single .execute() caps at 1000 while fetch_all() pages
    through all of them. A fake could never surface this."""
    big = None
    for cid in _channel_ids(sb):
        page2 = (
            audits_for_channel(cid, "id").eq("status", "applied")
            .range(1000, 1999).execute()
        ).data or []
        if page2:
            big = cid
            break
    if big is None:
        pytest.skip("no channel currently has >1000 applied audits to exercise the cap")

    capped = len((audits_for_channel(big, "id").eq("status", "applied").execute()).data or [])
    paged = len(fetch_all(audits_for_channel(big, "id").eq("status", "applied")))

    assert capped == 1000, f"expected the single-page read to cap at 1000, got {capped}"
    assert paged > 1000, f"fetch_all should page past 1000, got {paged}"
