"""Preview (S1.4b): what the agent tick would do to a channel's next N warm videos.

Runs pick → triage → candidates → render, read-only, and prints each video's
rules answer, arm, targets and description before and after. The owner reads
it before writes are enabled (spec Part 4 S1.7).

    PYTHONPATH=. python scripts/preview_backlinks.py --channel UCr5-YUqBiW7PUmeAtxUWuRg --n 20

Writes nothing: no interventions, no decision_log rows (the triage rules are
asked directly, with no backend call), no YouTube call. A video whose block
can't be rendered (no heading for the channel's language yet, S1.2) prints the
refusal instead of an after.
"""

from __future__ import annotations

import argparse
import json

from app import agent_tick


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--channel", required=True, help="channel id")
    p.add_argument("--n", type=int, default=20, help="how many warm videos (default 20)")
    return p


def _print(item: dict, i: int) -> None:
    print(f"=== {i}. {item['video_id']} {item['title']!r}")
    print(f"answer: {item['answer']}  arm: {item['arm'] or '-'}  explore: {item['explore']}")
    if item["rationale"]:
        print(f"rationale: {item['rationale']}")
    for t in item["targets"]:
        print(f"  target {t['video_id']} ({t['channel_id']}) sim {t['similarity']:.4f} "
              f"imp {t['impressions']}: {t['title']}")
    print("context: " + json.dumps(
        {k: v for k, v in item["context"].items() if k != "recent_interventions"},
        ensure_ascii=False, sort_keys=True, default=str))
    print("--- before")
    print(item["before"])
    if item["refused"]:
        print(f"--- render refused: {item['refused']}")
    elif item["after"] is not None:
        print("--- after" + (" (holdout: would not be written)" if item["arm"] == "holdout" else ""))
        print(item["after"])
    print()


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    items = agent_tick.preview(args.channel, args.n)
    if not items:
        print(f"{args.channel}: the warm pool is empty (reach not certified, or every video held)")
    for i, item in enumerate(items, 1):
        _print(item, i)


if __name__ == "__main__":
    main()
