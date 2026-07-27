"""Read-only live parity guard for the playlist_video_sims() RPC.

Proves the pgvector RPC returns the SAME similarity a video gets from the in-app
centroid math (_centroid + _cosine_sim), on real Supabase data. This is the gate
for flipping PLAYLIST_SIMS_USE_RPC on: run it after applying the migration; if it
passes, the RPC is trusted.

SELECT-only, no writes. Skips when there are no live credentials, when the RPC
isn't migrated yet, or when there's no playlist with embedded members to compare.
"""
import pytest

from app.config import settings
from app.db import supabase
from app.openrouter import EMBED_MODEL
from app import playlists

pytestmark = pytest.mark.live

_TOL = 1e-6  # float8 (Postgres) vs Python double: summation-order epsilon


def _has_creds() -> bool:
    return bool((settings.SUPABASE_URL or "").strip() and (settings.SUPABASE_SERVICE_KEY or "").strip())


@pytest.fixture(scope="module", autouse=True)
def _require_creds():
    if not _has_creds():
        pytest.skip("no live Supabase credentials in the environment")


def _first_channel_with_scorable_playlist():
    """Find (channel_id, playlist_id, video_id, member_ids) where the playlist
    has embedded members and there's an embedded candidate to score."""
    channels = supabase().table("channels").select("id").execute().data or []
    for ch in channels:
        cid = ch["id"]
        pls = supabase().table("playlists").select("id").eq("channel_id", cid).execute().data or []
        vids = supabase().table("videos").select("id").eq("channel_id", cid).limit(1000).execute().data or []
        video_ids = [v["id"] for v in vids]
        if not video_ids:
            continue
        for pl in pls:
            members = playlists._current_members(pl["id"])
            member_ids = list(members.keys())
            if not member_ids:
                continue
            # need at least one embedded member (so a centroid exists)
            if playlists._centroid(member_ids) is None:
                continue
            # a candidate embedded video not already a member. Use the cheap
            # existence check (not _get_embedding, whose .single() raises on 0 rows).
            for v in video_ids:
                if v not in members and playlists._has_pooled_embedding(v):
                    return cid, pl["id"], v, member_ids
    return None


def test_rpc_sim_matches_inapp_on_live_data():
    found = _first_channel_with_scorable_playlist()
    if not found:
        pytest.skip("no live playlist with embedded members + an embedded candidate")
    cid, pid, vid, member_ids = found

    # In-app oracle
    emb = playlists._get_embedding(vid)
    centroid = playlists._centroid(member_ids)
    legacy_sim = playlists._cosine_sim(emb, centroid)

    # RPC path (single-video form)
    try:
        rows = supabase().rpc("playlist_video_sims", {
            "p_channel_id": cid, "p_model_version": EMBED_MODEL, "p_video_id": vid,
        }).execute().data or []
    except Exception as e:
        pytest.skip(f"playlist_video_sims RPC not available (apply the migration): {e}")

    rpc_by_pl = {r["playlist_id"]: r["sim"] for r in rows}
    assert pid in rpc_by_pl, f"RPC returned no sim for playlist {pid}"
    assert abs(rpc_by_pl[pid] - legacy_sim) <= _TOL, (
        f"sim drift for ({pid},{vid}): rpc={rpc_by_pl[pid]} legacy={legacy_sim}"
    )
