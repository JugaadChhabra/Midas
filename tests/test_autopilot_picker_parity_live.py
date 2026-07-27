"""Read-only live parity guard for next_audit_candidate() (the autopilot picker).

Proves the RPC picks the SAME next-video-to-audit as the in-app scan, per
channel, on real Supabase data. The gate for flipping AUTOPILOT_PICKER_USE_RPC on.

SELECT-only. Skips without live creds or when the RPC isn't migrated yet.
"""
import pytest

from app.config import settings
from app.db import supabase
import app.autopilot as ap

pytestmark = pytest.mark.live


def _has_creds() -> bool:
    return bool((settings.SUPABASE_URL or "").strip() and (settings.SUPABASE_SERVICE_KEY or "").strip())


@pytest.fixture(scope="module", autouse=True)
def _require_creds():
    if not _has_creds():
        pytest.skip("no live Supabase credentials in the environment")


def test_rpc_pick_matches_inapp_per_channel():
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
        with pytest_flag(False):
            inapp = ap._next_video_for_channel(cid)
        with pytest_flag(True):
            rpc = ap._next_video_for_channel(cid)
        assert (rpc or {}).get("id") == (inapp or {}).get("id"), (
            f"picker drift on channel {cid}: rpc={rpc} inapp={inapp}"
        )
        compared += 1

    assert compared > 0


class pytest_flag:
    """Temporarily force AUTOPILOT_PICKER_USE_RPC on/off."""
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self._old = settings.AUTOPILOT_PICKER_USE_RPC
        settings.AUTOPILOT_PICKER_USE_RPC = self.value

    def __exit__(self, *a):
        settings.AUTOPILOT_PICKER_USE_RPC = self._old
