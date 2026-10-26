"""The playlist test's draw (S2.1): preview it, then draw it, once per channel.

--preview prints, per eligible playlist, its arm and the videos it would be
proposed (similarity and impressions), and every skipped playlist with why.
It writes nothing. --draw writes the arms and the treated playlists' pending
"Playlist test" proposals, for one review in the dashboard's proposals card
(spec Part 5 S2.7). It asks for no confirmation, and refuses a channel that
is already drawn.

    PYTHONPATH=. python scripts/playlist_test.py --channel UCr5-YUqBiW7PUmeAtxUWuRg --preview
    PYTHONPATH=. python scripts/playlist_test.py --channel UCr5-YUqBiW7PUmeAtxUWuRg --draw

Nothing reaches YouTube: approved adds are sent later by the budgeted daily job.
"""

from __future__ import annotations

import argparse
import sys

from app import playlist_test


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--channel", required=True, help="channel id")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="print the draw; write nothing")
    mode.add_argument("--draw", action="store_true", help="write the arms and proposals")
    return p


def _print_summary(result: dict) -> None:
    arms = result["arms"]
    print(f"{result['channel_id']}: {result['playlists']} playlists, "
          f"{arms['treated']} treated ({arms['no_dose']} with no candidates), "
          f"{arms['holdout']} holdout, {result['proposals']} proposals")
    for s in result["skipped"]:
        print(f"  skipped {s['playlist_id']} ({s['reason']}): {s['title']}")


def _print_preview(result: dict) -> None:
    if result["already_drawn"]:
        print(f"{result['channel_id']}: already drawn; --draw would refuse")
    for i, a in enumerate(result["plan"], 1):
        print(f"=== {i}. {a['playlist_id']} {a['title']!r}")
        print(f"arm: {a['arm']}  status: {a['status']}  "
              f"embedded members: {a['eligible_members']}")
        for v in a["videos"]:
            print(f"  add {v['video_id']} sim {v['similarity']:.4f} "
                  f"imp {v['impressions']}: {v['title']}")
    print()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.preview:
        result = playlist_test.preview(args.channel)
    else:
        try:
            result = playlist_test.draw(args.channel)
        except playlist_test.AlreadyDrawn as e:
            print(f"refused: {e}")
            return 1
    if result["refused"]:
        print(f"{args.channel}: refused ({result['refused']}); nothing "
              + ("would be " if args.preview else "") + "written")
        return 1
    if args.preview:
        _print_preview(result)
    _print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
