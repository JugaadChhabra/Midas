"""One-time backfill: correct videos.is_short using the Shorts-URL probe.

The old classifier flagged every sub-3-min upload as a Short purely by
duration, mislabeling regular short videos. This re-derives is_short from the
authoritative signal — youtube.com/shorts/<id> serves 200 for a real Short and
30x-redirects to /watch for a regular video (see app.sync.is_actually_short).

Only videos in the ambiguous band (duration <= 180s, or unknown duration) are
probed; anything longer can never be a Short and is corrected to False without
a network call. Only rows whose value actually changes are written, so the
script is idempotent and safe to re-run / resume after an interruption.

Usage:
    python -m scripts.backfill_is_short              # all channels
    python -m scripts.backfill_is_short UC8oC7...    # one channel
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.db import supabase
from app.sync import SHORTS_MAX_SECONDS, _SHORTS_PROBE_UA

WORKERS = 8              # keep modest — youtube.com soft-blocks rapid bursts
MAX_CONSECUTIVE_FAILS = 25   # circuit breaker if YouTube starts blocking us


def _probe_is_short(video_id: str) -> bool | None:
    """True/False from the Shorts URL, or None if the probe failed (unknown)."""
    try:
        resp = httpx.get(
            f"https://www.youtube.com/shorts/{video_id}",
            follow_redirects=False,
            timeout=10.0,
            headers={"User-Agent": _SHORTS_PROBE_UA},
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return None


def _all_videos(channel_id: str) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        chunk = (
            supabase().table("videos").select("id,duration_seconds,is_short")
            .eq("channel_id", channel_id).range(start, start + 999).execute().data or []
        )
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        start += 1000
    return rows


def backfill_channel(channel_id: str, name: str = "") -> tuple[int, int, int]:
    videos = _all_videos(channel_id)
    print(f"\n== {name or channel_id} — {len(videos)} videos ==", flush=True)

    # Split: long videos are corrected without a probe; the rest are probed.
    to_probe: list[dict] = []
    flips = probed = failed = 0
    pending_updates: dict[bool, list[str]] = {True: [], False: []}

    for v in videos:
        dur = v.get("duration_seconds")
        if dur is not None and dur > SHORTS_MAX_SECONDS:
            if v.get("is_short") is not False:
                pending_updates[False].append(v["id"])
        else:
            to_probe.append(v)

    consecutive_fails = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for v, verdict in zip(to_probe, pool.map(lambda x: _probe_is_short(x["id"]), to_probe)):
            probed += 1
            if verdict is None:
                failed += 1
                consecutive_fails += 1
                if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                    print(f"!! {consecutive_fails} consecutive probe failures — "
                          f"YouTube may be blocking us. Stopping this channel.", flush=True)
                    break
                continue
            consecutive_fails = 0
            if verdict is not v.get("is_short"):
                pending_updates[verdict].append(v["id"])
            if probed % 200 == 0:
                print(f"  probed {probed}/{len(to_probe)} …", flush=True)

    for verdict, ids in pending_updates.items():
        for i in range(0, len(ids), 100):
            batch = ids[i:i+100]
            supabase().table("videos").update({"is_short": verdict}).in_("id", batch).execute()
            flips += len(batch)

    print(f"  done: probed={probed} failed={failed} flipped={flips}", flush=True)
    return probed, failed, flips


def main() -> None:
    if len(sys.argv) > 1:
        channels = [{"id": sys.argv[1], "name": ""}]
    else:
        channels = supabase().table("channels").select("id,name").execute().data or []
    t0 = time.monotonic()
    totals = [0, 0, 0]
    for ch in channels:
        p, f, fl = backfill_channel(ch["id"], ch.get("name", ""))
        totals[0] += p; totals[1] += f; totals[2] += fl
    print(f"\nALL DONE in {time.monotonic()-t0:.0f}s — "
          f"probed={totals[0]} failed={totals[1]} flipped={totals[2]}", flush=True)


if __name__ == "__main__":
    main()
