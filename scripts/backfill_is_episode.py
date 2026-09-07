"""One-time backfill: populate videos.is_episode from the title/tag pattern.

New syncs stamp is_episode at ingest (app/sync.py), but rows already in the
database predate the column and read back as NULL (treated as non-episode). This
classifies every existing row with app.content_type.is_episode and writes only
the rows whose value actually changes, so it is idempotent and safe to re-run.

Unlike backfill_is_short, this makes NO network calls — classification is a pure
title/tag check — so it is fast even on large channels.

Run this AFTER filling in the identifier in app/content_type.py; with the
pattern still blank every video classifies as non-episode and the backfill is a
no-op. Per project rules this is a bulk DB mutation — verify the result, then
refresh the NAS snapshot (see CLAUDE.md).

Usage:
    python -m scripts.backfill_is_episode              # all channels
    python -m scripts.backfill_is_episode UC8oC7...    # one channel
"""
from __future__ import annotations

import sys
import time

from app.content_type import is_episode
from app.db import supabase


def _all_videos(channel_id: str) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        chunk = (
            supabase().table("videos").select("id,title,tags,is_episode")
            .eq("channel_id", channel_id).range(start, start + 999).execute().data or []
        )
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        start += 1000
    return rows


def backfill_channel(channel_id: str, name: str = "") -> tuple[int, int]:
    videos = _all_videos(channel_id)
    # Group the ids whose stored value disagrees with the current verdict.
    pending: dict[bool, list[str]] = {True: [], False: []}
    for v in videos:
        verdict = is_episode(v.get("title"), v.get("tags") or [])
        if verdict is not v.get("is_episode"):
            pending[verdict].append(v["id"])

    flipped = 0
    for verdict, ids in pending.items():
        for i in range(0, len(ids), 100):
            batch = ids[i:i + 100]
            supabase().table("videos").update({"is_episode": verdict}).in_("id", batch).execute()
            flipped += len(batch)

    episodes = len(pending[True])
    print(
        f"== {name or channel_id} — {len(videos)} videos: "
        f"flipped={flipped} (now marked episode this run={episodes})",
        flush=True,
    )
    return len(videos), flipped


def main() -> None:
    if len(sys.argv) > 1:
        channels = [{"id": sys.argv[1], "name": ""}]
    else:
        channels = supabase().table("channels").select("id,name").execute().data or []
    t0 = time.monotonic()
    total_videos = total_flipped = 0
    for ch in channels:
        n, fl = backfill_channel(ch["id"], ch.get("name", ""))
        total_videos += n
        total_flipped += fl
    print(
        f"\nALL DONE in {time.monotonic()-t0:.0f}s — "
        f"videos={total_videos} flipped={total_flipped}",
        flush=True,
    )


if __name__ == "__main__":
    main()
