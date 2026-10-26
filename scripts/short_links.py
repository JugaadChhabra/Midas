"""Short-link recommendations (S2.4): preview what the weekly refresh would write.

--preview prints, per Short the next `short_link_refresh` run would recommend,
its Shorts-feed views and its targets (rank, similarity, impressions), then the
counts: Shorts listed, already recommended, skipped without a vector, with no
target. It writes nothing and asks no decide backend (spec Part 5 S2.7 step 6).

    PYTHONPATH=. python scripts/short_links.py --channel UCr5-YUqBiW7PUmeAtxUWuRg --preview

Nothing reaches YouTube, ever: the team sets each link in Studio.
"""

from __future__ import annotations

import argparse
import sys

from app import short_links


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--channel", required=True, help="channel id")
    p.add_argument("--preview", action="store_true", required=True,
                   help="print what refresh would write; write nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = short_links.preview(args.channel)
    if result["refused"]:
        print(f"{args.channel}: refused ({result['refused']}); nothing would be written")
        return 1
    for i, s in enumerate(result["plan"], 1):
        print(f"=== {i}. {s['id']} feed views {s['feed_views']}: {s['title']}")
        for rank, t in enumerate(s["targets"], 1):
            print(f"  {rank}. {t['video_id']} sim {t['similarity']:.4f} "
                  f"imp {t['impressions']}: {t['title']}")
    print()
    print(f"{args.channel}: {result['shorts']} Shorts with feed views, "
          f"{result['already']} already recommended, {len(result['plan'])} would be, "
          f"{result['skipped_unembedded']} skipped (no vector), "
          f"{result['no_targets']} with no target; "
          f"{result['targets_unembedded']} warm long videos without a vector")
    return 0


if __name__ == "__main__":
    sys.exit(main())
