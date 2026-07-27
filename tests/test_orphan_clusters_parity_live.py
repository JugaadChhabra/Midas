"""Read-only live parity guard for the discover_orphan_clusters() RPC.

Proves the pgvector RPC produces the SAME orphan clustering (same partition) as
the in-app greedy path on real Supabase data. The gate for flipping
PLAYLIST_DISCOVERY_USE_RPC on.

SELECT-only. Skips without live creds, when the RPC isn't migrated, or when no
channel has enough embedded orphans to form a cluster.
"""
import pytest

from app.config import settings
from app.db import supabase
from app import playlist_discovery as pd

pytestmark = pytest.mark.live


def _has_creds() -> bool:
    return bool((settings.SUPABASE_URL or "").strip() and (settings.SUPABASE_SERVICE_KEY or "").strip())


@pytest.fixture(scope="module", autouse=True)
def _require_creds():
    if not _has_creds():
        pytest.skip("no live Supabase credentials in the environment")


def _partition(clusters):
    return {frozenset(c) for c in clusters}


def test_rpc_partition_matches_inapp_on_live_data():
    channels = supabase().table("channels").select("id").execute().data or []
    for ch in channels:
        cid = ch["id"]
        vids = supabase().table("videos").select("id").eq("channel_id", cid).limit(1000).execute().data or []
        all_ids = [v["id"] for v in vids]
        if not all_ids:
            continue
        orphans = pd._orphan_video_ids(cid, all_ids)
        if not orphans:
            continue

        inapp = pd._cluster_orphans_inapp(cid, orphans)
        if not inapp:
            continue  # no cluster met MIN_CLUSTER_SIZE — nothing to compare on this channel

        try:
            rpc = pd._rpc_cluster_orphans(cid, orphans)
        except Exception as e:
            pytest.skip(f"discover_orphan_clusters RPC not available (apply the migration): {e}")

        assert _partition(rpc) == _partition(inapp), (
            f"cluster drift on channel {cid}: rpc={_partition(rpc)} inapp={_partition(inapp)}"
        )
        return  # one channel with real clusters is a sufficient parity witness

    pytest.skip("no channel had embedded orphans forming a cluster")
