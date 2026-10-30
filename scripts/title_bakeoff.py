"""Bake-off (S3.2): the same N title answers through each writer model, blind.

For the first N warm long videos by impressions that triage would send to
titles (the pick's exclusions ignored: a video already in a backlinks
experiment is still a fair sample of the channel's titles), asks `titles.write_candidates` once per model and
writes one CSV row per (video, model): the current title, the model's top
candidate passing the checks (or none, with the failures), shuffled, the
model behind a code. The key file beside it maps codes to models. The SEO team
fills `score_1_3` ("would a parent tap this on the home page?") and
`wrong_or_broken_script` (yes/no) (spec Part 6 S3.2, S3.7, F9).

    PYTHONPATH=. python scripts/title_bakeoff.py --channel UCr5-YUqBiW7PUmeAtxUWuRg \\
        --n 20 --models anthropic/claude-haiku-4.5,google/gemini-3.7-flash,openai/gpt-5-mini

Writes nothing to the database (transcripts from the cache only), calls no
YouTube; it does call each model (OpenRouter). Default output
logs/title_bakeoff_<channel>.csv and logs/title_bakeoff_<channel>.key.csv.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from app import titles
from app.short_links import _cell

COLUMNS = ["row", "code", "video_id", "current_title", "candidate", "checks",
           "score_1_3", "wrong_or_broken_script"]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--channel", required=True, help="channel id")
    p.add_argument("--n", type=int, default=20, help="how many title answers (default 20)")
    p.add_argument("--models", required=True, help="comma list of OpenRouter models")
    p.add_argument("--out", help="CSV path (default logs/title_bakeoff_<channel>.csv)")
    p.add_argument("--seed", type=int, help="shuffle seed (default random)")
    return p


def _top(ctx: dict, video: dict, model: str) -> tuple[str, str]:
    """(the top candidate passing the checks or "", its checks)."""
    try:
        found = titles.write_candidates(ctx, model=model)
    except Exception as e:
        return "", f"writer failed: {type(e).__name__}"
    failures = []
    for c in found:
        failure = titles.check(c["title"], video)
        if failure is None:
            return c["title"], "pass" + (f" (after {len(failures)} failing)" if failures else "")
        failures.append(f"{c['title']!r}: {failure}")
    return "", "; ".join(failures) or titles.MALFORMED


def key_path(out: Path) -> Path:
    return out.with_name(out.stem + ".key.csv")


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rng = random.Random(args.seed)
    codes = [f"W{i}" for i in range(1, len(models) + 1)]
    rng.shuffle(codes)
    code_of = dict(zip(models, codes))

    channel, videos = titles.title_answers(args.channel, args.n, pick=False)
    rows = []
    for video in videos:
        ctx = titles.context(video, channel=channel, cache_only=True)
        subject = {**video, "default_language": ctx["default_language"]}
        for model in models:
            candidate, checks = _top(ctx, subject, model)
            rows.append({"code": code_of[model], "video_id": video["id"],
                         "current_title": video.get("title") or "", "candidate": candidate,
                         "checks": checks, "score_1_3": "", "wrong_or_broken_script": ""})
    rng.shuffle(rows)

    out = Path(args.out or f"logs/title_bakeoff_{args.channel}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows({"row": i, **{k: _cell(v) for k, v in r.items()}}
                    for i, r in enumerate(rows, 1))
    with key_path(out).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "model"])
        w.writerows(sorted((c, m) for m, c in code_of.items()))
    print(f"{len(videos)} videos x {len(models)} models: wrote {out} and {key_path(out)}")


if __name__ == "__main__":
    main()
