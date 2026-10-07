"""Read-only live parity guard for warm_pool() (B4, #35).

Proves the RPC ranks the SAME warm pool as the in-app twin, per channel, on the
real data. The gate for flipping WARM_POOL_USE_RPC on; the offline twin of this
is test_warm_pool_parity.py.

SELECT-only. Skips without live creds or when the RPC isn't migrated yet.
"""
import pytest

from app import warm
from app.config import settings
from app.db import supabase

pytestmark = pytest.mark.live


def _has_creds() -> bool:
    return bool((settings.SUPABASE_URL or "").strip() and (settings.SUPABASE_SERVICE_KEY or "").strip())


@pytest.fixture(scope="module", autouse=True)
def _require_creds():
    if not _has_creds():
        pytest.skip("no live Supabase credentials in the environment")


def test_rpc_pool_matches_inapp_per_channel():
    channels = supabase().table("channels").select("id").execute().data or []
    if not channels:
        pytest.skip("no channels")

    try:
        warm._ranked_pool_rpc(channels[0]["id"])
    except Exception as e:
        pytest.skip(f"warm_pool RPC not available (apply the migration): {e}")

    for ch in channels:
        cid = ch["id"]
        rpc, inapp = warm._ranked_pool_rpc(cid), warm._ranked_pool_inapp(cid)
        assert rpc == inapp, f"warm pool drift on channel {cid}: {len(rpc)} rpc vs {len(inapp)} in-app"
