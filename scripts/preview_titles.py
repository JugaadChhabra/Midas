"""Preview (S3.2): what the title lever would do to a channel's next N title answers.

For the warm pool's first N videos triage would send to titles, prints the
arm and the path, and for a treated video on the path asked the pipeline's
candidates and their checks, or (`--path agent`, S3.4) the agent's run: its
title or decline, the tools it called and its turns, beside the current title. The SEO team signs off
once per channel on it (spec Part 6 S3.7, F12).

    PYTHONPATH=. python scripts/preview_titles.py --channel UCr5-YUqBiW7PUmeAtxUWuRg --n 20
    PYTHONPATH=. python scripts/preview_titles.py --channel ... --csv   # logs/preview_titles_<channel>.csv

Writes nothing: no interventions, no decision_log rows (the title answer is
TRIAGE's rules, `decide.TRIAGE.rules`, asked directly on the tick's context with
the title lever taken as open, so it lists videos before TITLE_APPLY_ENABLED or
TITLE_CHANNELS let the tick title them), no transcript cache rows (cache reads
only), no YouTube call. It does call the writer model (OpenRouter), and with
`--path agent` the agent's reasoning model.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app import titles
from app.agent import loop as agent_loop
from app.short_links import _cell


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--channel", required=True, help="channel id")
    p.add_argument("--n", type=int, default=20, help="how many title answers (default 20)")
    p.add_argument("--path", choices=titles.PATHS, default=titles.PIPELINE,
                   help="whose treated videos to write for (default pipeline)")
    p.add_argument("--csv", nargs="?", const="", default=None, metavar="PATH",
                   help="also write a CSV (default logs/preview_titles_<channel>.csv)")
    return p


def _pct(ctr) -> str:
    return "-" if ctr is None else f"{ctr * 100:.2f}%"


def _print(item: dict, i: int) -> None:
    print(f"=== {i}. {item['video_id']} {item['title']!r}")
    print(f"answer: {item['answer']}  arm: {item['arm']}  path: {item['path'] or '-'}  "
          f"ctr: {_pct(item['ctr'])} (median {_pct(item['channel_median_ctr'])})  "
          f"imp: {item['impressions']}")
    if item["note"]:
        print(f"  {item['note']}")
    if item["error"]:
        print(f"  writer failed: {item['error']}")
    written = item["written"]
    if written:
        for c in written.candidates:
            print(f"  [{c['attempt']}] {c['title']!r}  {c['check'] or 'pass'}  ({c['reason']})")
        print(f"  -> {written.title!r}" if written.title
              else "  -> no passing candidate: " + "; ".join(written.failures))
    ran = item.get("agent")
    if ran:
        print(f"  tools ({ran.trajectory['turns']} turns): "
              + (", ".join(agent_loop.tools_called(ran.trajectory)) or "none"))
        for sub in ran.trajectory["submits"]:
            print(f"  submitted {sub['title']!r}  {sub['check'] or 'pass'}")
        print(f"  -> {ran.title!r}  ({ran.reason})" if ran.kind == agent_loop.TITLE
              else f"  -> {ran.kind}: {ran.reason}")
    print()


_COLUMNS = ["video_id", "current_title", "arm", "path", "ctr", "channel_median_ctr",
            "impressions", "title", "reason", "candidates", "agent_end", "tools", "turns",
            "note"]


def _row(item: dict) -> dict:
    written, ran = item["written"], item.get("agent")
    if ran:
        return {**_row({**item, "agent": None}),
                "title": ran.title or "", "reason": ran.reason or "",
                "candidates": " | ".join(f"{s['title']} ({s['check'] or 'pass'})"
                                         for s in ran.trajectory["submits"]),
                "agent_end": ran.kind, "tools": " ".join(agent_loop.tools_called(ran.trajectory)),
                "turns": ran.trajectory["turns"]}
    return {
        "video_id": item["video_id"], "current_title": item["title"], "arm": item["arm"],
        "path": item["path"] or "", "ctr": item["ctr"],
        "channel_median_ctr": item["channel_median_ctr"], "impressions": item["impressions"],
        "title": (written.title or "") if written else "",
        "reason": (written.reason or "; ".join(written.failures)) if written else "",
        "candidates": " | ".join(f"{c['title']} ({c['check'] or 'pass'})"
                                 for c in written.candidates) if written else "",
        "agent_end": "", "tools": "", "turns": "",
        "note": item["note"] or item["error"] or "",
    }


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    items = titles.preview(args.channel, args.n, path=args.path)
    if not items:
        print(f"{args.channel}: no title answers in the warm pool "
              f"(reach not certified, or no video under the channel median CTR)")
    for i, item in enumerate(items, 1):
        _print(item, i)
    if args.csv is not None:
        out = Path(args.csv or f"logs/preview_titles_{args.channel}.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_COLUMNS)
            w.writeheader()
            w.writerows({k: _cell(v) for k, v in _row(item).items()} for item in items)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
