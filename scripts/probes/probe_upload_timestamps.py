"""Live probe: which timestamp says when a scheduled video was UPLOADED?

Team upload tracking counts a video on the IST day it was uploaded, not the day
it goes public. That needs a field that (a) exists while the video is still
private/scheduled and (b) does not move when the video goes live. The docs are
vague on both, so this probe asks the API. For each recent upload it prints:

  pi.snippet.publishedAt          when the item was added to the uploads playlist
  pi.contentDetails.videoPublishedAt
  video.snippet.publishedAt       documented to become the go-live time
  video.status.publishAt          the scheduled go-live time (scheduled only)
  video.status.privacyStatus / uploadStatus

It also answers whether a private/scheduled video shows up in the uploads
playlist at all under the channel owner's token (`app/sync.py` currently skips
private videos after fetching them, so they should).

Run it twice against a channel with a scheduled video:

  1. While it is still scheduled:
       ... probe_upload_timestamps.py <channel_id> --save before.json
  2. After it has gone public:
       ... probe_upload_timestamps.py <channel_id> --compare before.json

Step 2 prints every timestamp field that changed per video. The field we want
is present in step 1 and unchanged in step 2, and its value matches the real
upload time in YouTube Studio.

Read-only against YouTube. Cost: 1u (channels.list) + 1u per playlist page +
1u per 50 videos, charged to the `quota_log` ledger like a sync. The only DB
write besides the ledger is `youtube_for_channel` saving a refreshed token.

Usage:
    PYTHONPATH=. venv/bin/python scripts/probes/probe_upload_timestamps.py <channel_id>
        [--pages N] [--video-id ID ...] [--save FILE] [--compare FILE]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from app import quota
from app.youtube_client import youtube_for_channel

IST = ZoneInfo("Asia/Kolkata")

#: Fields of a merged record that are compared between runs.
FIELDS = (
    "pi_published_at",
    "pi_video_published_at",
    "video_published_at",
    "status_publish_at",
    "privacy_status",
    "upload_status",
)


def _ist_day(ts: str | None) -> str:
    if not ts:
        return "-"
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST).strftime("%Y-%m-%d %H:%M")


def merge(playlist_items: list[dict], videos: list[dict]) -> dict[str, dict]:
    """One record per video id, from playlistItems + videos.list responses."""
    by_id = {v["id"]: v for v in videos}
    out: dict[str, dict] = {}
    for pi in playlist_items:
        vid = (pi.get("contentDetails") or {}).get("videoId")
        if not vid:
            continue
        v = by_id.get(vid) or {}
        vsn, vst = v.get("snippet") or {}, v.get("status") or {}
        out[vid] = {
            "title": vsn.get("title") or (pi.get("snippet") or {}).get("title"),
            "pi_published_at": (pi.get("snippet") or {}).get("publishedAt"),
            "pi_video_published_at": (pi.get("contentDetails") or {}).get("videoPublishedAt"),
            "video_published_at": vsn.get("publishedAt"),
            "status_publish_at": vst.get("publishAt"),
            "privacy_status": vst.get("privacyStatus") or (pi.get("status") or {}).get("privacyStatus"),
            "upload_status": vst.get("uploadStatus"),
        }
    return out


def diff(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    """Human-readable lines for every field that changed between two runs."""
    lines = []
    for vid, old in before.items():
        new = after.get(vid)
        if new is None:
            lines.append(f"{vid}  missing from this run (outside --pages, or deleted)")
            continue
        changed = [f for f in FIELDS if old.get(f) != new.get(f)]
        head = f"{vid}  {(new.get('title') or '')[:50]!r}"
        if not changed:
            lines.append(f"{head}\n    no timestamp/status change")
            continue
        lines.append(head)
        for f in changed:
            lines.append(f"    {f:24} {old.get(f)!s:28} -> {new.get(f)}")
    return lines


def _print_table(records: dict[str, dict]) -> None:
    for vid, r in records.items():
        flag = "SCHEDULED" if r["status_publish_at"] else r["privacy_status"] or "?"
        print(f"\n{vid}  [{flag}]  {(r['title'] or '')[:60]!r}")
        for f in FIELDS[:4]:
            print(f"    {f:24} {r[f]!s:28} IST {_ist_day(r[f])}")
        print(f"    upload_status            {r['upload_status']}")


def _fetch(yt, channel_id: str, pages: int) -> dict[str, dict]:
    ok = False
    try:
        resp = yt.channels().list(part="contentDetails", id=channel_id).execute()
        ok = True
    finally:
        quota.charge(channel_id, quota.Op.CHANNELS_LIST, ok)
    uploads = resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    items: list[dict] = []
    token = None
    for _ in range(pages):
        ok = False
        try:
            # snippet+status cost nothing extra; sync.py only asks for contentDetails.
            page = yt.playlistItems().list(
                part="snippet,contentDetails,status",
                playlistId=uploads, maxResults=50, pageToken=token,
            ).execute()
            ok = True
        finally:
            quota.charge(channel_id, quota.Op.PLAYLIST_ITEMS_LIST, ok)
        items.extend(page.get("items") or [])
        token = page.get("nextPageToken")
        if not token:
            break

    ids = [(i.get("contentDetails") or {}).get("videoId") for i in items]
    ids = [i for i in ids if i]
    videos: list[dict] = []
    for start in range(0, len(ids), 50):
        ok = False
        try:
            videos.extend(yt.videos().list(
                part="snippet,status", id=",".join(ids[start:start + 50]),
            ).execute().get("items") or [])
            ok = True
        finally:
            quota.charge(channel_id, quota.Op.VIDEOS_LIST, ok)
    return merge(items, videos)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("channel_id")
    p.add_argument("--pages", type=int, default=1, help="uploads-playlist pages of 50 (default 1)")
    p.add_argument("--video-id", action="append", default=[],
                   help="a scheduled video's id; reports whether it is in the uploads playlist")
    p.add_argument("--save", help="write this run's records to a JSON file")
    p.add_argument("--compare", help="diff this run against a JSON file from --save")
    args = p.parse_args()

    yt = youtube_for_channel(args.channel_id)
    try:
        records = _fetch(yt, args.channel_id, args.pages)
    except HttpError as e:
        print(f"HttpError {e.resp.status}: {e.content!r}")
        return 1

    _print_table(records)

    scheduled = [v for v, r in records.items() if r["status_publish_at"]]
    private = [v for v, r in records.items() if r["privacy_status"] == "private"]
    print(f"\n{len(records)} uploads read; {len(private)} private, {len(scheduled)} scheduled")
    for vid in args.video_id:
        print(f"--video-id {vid}: {'IN' if vid in records else 'NOT in'} the uploads playlist pages read")

    if args.compare:
        with open(args.compare) as f:
            before = json.load(f)
        print("\n── changes since", args.compare, "─" * 30)
        print("\n".join(diff(before, records)) or "(nothing to compare)")

    if args.save:
        with open(args.save, "w") as f:
            json.dump(records, f, indent=2)
        print(f"\nsaved {len(records)} records to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
