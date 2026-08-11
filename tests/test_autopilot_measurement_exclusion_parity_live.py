"""Read-only live parity guard for the measurement-exclusion picker rule.

Track 1 Piece 2: a video whose LATEST audit is mid-measurement
(measurement_status in awaiting_window/measuring) must never be picked for a
fresh audit, on EITHER picker path (in-app scan and next_audit_candidate RPC).
This test proves (a) both paths still agree per channel and (b) neither path
ever returns an in-measurement video — so the exclusion can't silently live on
only one side.

SELECT-only. Skips without live creds or when the RPC isn't migrated yet.
"""
import pytest

from app.config import settings
from app.db import supabase
from app.metrics_poll import ACTIVE_MEASUREMENT_STATUSES
import app.autopilot as ap

pytestmark = pytest.mark.live


def _has_creds() -> bool:
    return bool((settings.SUPABASE_URL or "").strip() and (settings.SUPABASE_SERVICE_KEY or "").strip())


@pytest.fixture(scope="module", autouse=True)
def _require_creds():
    if not _has_creds():
        pytest.skip("no live Supabase credentials in the environment")


class pytest_flag:
    """Temporarily force AUTOPILOT_PICKER_USE_RPC on/off."""
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self._old = settings.AUTOPILOT_PICKER_USE_RPC
        settings.AUTOPILOT_PICKER_USE_RPC = self.value

    def __exit__(self, *a):
        settings.AUTOPILOT_PICKER_USE_RPC = self._old


def _in_measurement_video_ids(channel_id: str) -> set[str]:
    """Videos whose LATEST audit is in an active-measurement status."""
    vids = (
        supabase().table("videos").select("id").eq("channel_id", channel_id)
        .execute().data or []
    )
    ids = [v["id"] for v in vids]
    if not ids:
        return set()
    audits = (
        supabase().table("audits")
        .select("video_id,measurement_status,created_at")
        .in_("video_id", ids)
        .order("created_at", desc=True)
        .execute().data or []
    )
    latest: dict[str, str | None] = {}
    for a in audits:
        latest.setdefault(a["video_id"], a.get("measurement_status"))
    return {v for v, ms in latest.items() if ms in ACTIVE_MEASUREMENT_STATUSES}


def test_pickers_agree_and_never_pick_in_measurement():
    channels = supabase().table("channels").select("id").execute().data or []
    if not channels:
        pytest.skip("no channels")

    # Fail fast + skip cleanly if the RPC isn't migrated.
    try:
        supabase().rpc("next_audit_candidate", {"p_channel_id": channels[0]["id"]}).execute()
    except Exception as e:
        pytest.skip(f"next_audit_candidate RPC not available (apply the migration): {e}")

    compared = 0
    for ch in channels:
        cid = ch["id"]
        blocked = _in_measurement_video_ids(cid)

        with pytest_flag(False):
            inapp = ap._next_video_for_channel(cid)
        with pytest_flag(True):
            rpc = ap._next_video_for_channel(cid)

        assert (rpc or {}).get("id") == (inapp or {}).get("id"), (
            f"picker drift on channel {cid}: rpc={rpc} inapp={inapp}"
        )
        for pick in (inapp, rpc):
            pid = (pick or {}).get("id")
            assert pid not in blocked, (
                f"picker returned in-measurement video {pid} on channel {cid}"
            )
        compared += 1

    assert compared > 0
