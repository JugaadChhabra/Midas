"""Live probe (Phase A2): does the Data API expose a Short's related-video link?

Studio lets a Short link to a related video. This probe asks whether that
link is readable: it calls `videos.list` on one Short with every readable part
(`snippet,contentDetails,status,topicDetails,recordingDetails,localizations,
player`), writes the raw JSON to the file you name with `--out`, and prints
every JSON path whose value contains `--linked-video-id` (the video the team
set in Studio).

Reading the result:
  - one or more paths printed -> readable; note the path(s) in the findings.
  - none                      -> not exposed on any readable part.
Whether it is *writable* is a docs question (the `videos.update` reference),
not something this probe tests. It never attempts a write.

Quota: 1 Data API unit (`videos.list`). It is not charged to the quota_log
ledger: the call goes straight to the client, like the i18n probe.

Read-only. Nothing is written to YouTube or to the DB, except that
`youtube_for_channel` stores a refreshed access token if the old one expired.
`--out` writes the raw response to a local file.

Usage:
    PYTHONPATH=. venv/bin/python scripts/probes/probe_short_link.py <channel_id> <short_id>
        --linked-video-id VIDEO_ID --out PATH
"""

from __future__ import annotations

import argparse
import json

from googleapiclient.errors import HttpError

from app.youtube_client import youtube_for_channel

PARTS = "snippet,contentDetails,status,topicDetails,recordingDetails,localizations,player"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Search a Short's videos.list JSON for its linked video id.",
    )
    p.add_argument("channel_id", help="channel whose stored token makes the call")
    p.add_argument("short_id", help="the Short with a related video set in Studio")
    p.add_argument("--linked-video-id", required=True, help="the video id the Short links to")
    p.add_argument("--out", required=True, metavar="PATH", help="file to write the raw JSON to")
    return p


def find_paths(node, needle: str, path: str = "$") -> list[tuple[str, str]]:
    """Every (path, value) in `node` whose key or string value contains `needle`."""
    hits: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{path}.{k}"
            if needle in str(k):
                hits.append((child, f"<key> {k}"))
            hits.extend(find_paths(v, needle, child))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            hits.extend(find_paths(v, needle, f"{path}[{i}]"))
    elif needle in str(node):
        hits.append((path, str(node)))
    return hits


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    yt = youtube_for_channel(args.channel_id)
    print(f"── videos.list id={args.short_id} part={PARTS} ──")
    try:
        resp = yt.videos().list(part=PARTS, id=args.short_id).execute()
    except HttpError as e:
        print(f"HttpError {e.resp.status}: {e.content!r}")
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(resp, f, indent=2, ensure_ascii=False)
    print(f"raw JSON written to {args.out}")

    items = resp.get("items") or []
    if not items:
        print(f"no item returned for {args.short_id} (wrong id, deleted, or not visible to this token)")
        return 1

    hits = find_paths(resp, args.linked_video_id)
    print(f"\n=== paths containing {args.linked_video_id} ({len(hits)}) ===")
    for path, value in hits:
        print(f"  {path} = {value[:200]}")
    if not hits:
        print("  none: the linked video id is not in any readable part")
    print("\n── done ─────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
