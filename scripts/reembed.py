"""One-off (B6): re-embed channels with the title + description + tags recipe,
then calibrate their playlist thresholds. Not a scheduled job.

Estimate first, and record the figure: it reads the DB and prints each channel's
video count, the videos still to embed, a token estimate and the cost at the
OpenRouter price you pass. It calls no API.

    PYTHONPATH=. python scripts/reembed.py --channels UCr5-YUqBiW7PUmeAtxUWuRg \\
        --estimate --usd-per-mtok <OpenRouter price of EMBED_MODEL per 1M input tokens>

The real run embeds every video of each channel not yet under
`app.reembed.MODEL_VERSION`, then calibrates and stores each channel's
thresholds on `channels.playlist_thresholds`. Rerun after a failure: videos
already embedded are skipped.

    PYTHONPATH=. python scripts/reembed.py --channels UCr5-YUqBiW7PUmeAtxUWuRg

Writes: `video_embeddings` rows under the new model_version, and
`channels.playlist_thresholds` (needs migration 20261006060000). No YouTube
call, and the production vectors (model_version = EMBED_MODEL) are untouched.
"""

from __future__ import annotations

import argparse
import json

from app import reembed


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--channels", required=True,
                   help="comma-separated channel ids (B6: the rollout channel and its siblings)")
    p.add_argument("--estimate", action="store_true",
                   help="print counts, tokens and cost; call no API")
    p.add_argument("--usd-per-mtok", type=float, default=None,
                   help="OpenRouter price of EMBED_MODEL per 1M input tokens (required with --estimate)")
    p.add_argument("--skip-calibrate", action="store_true",
                   help="embed only; don't recompute the thresholds")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    if not channels:
        parser.error("--channels is empty")
    print(f"model_version: {reembed.MODEL_VERSION}")

    if args.estimate:
        if args.usd_per_mtok is None:
            parser.error("--estimate needs --usd-per-mtok")
        total = 0.0
        for cid in channels:
            e = reembed.estimate_channel(cid, args.usd_per_mtok)
            total += e["usd"]
            print(f"{cid}: {e['videos']} videos, {e['remaining']} to embed, "
                  f"~{e['tokens']:,} tokens, ~${e['usd']:.4f}")
        print(f"total: ~${total:.4f} at ${args.usd_per_mtok}/M tokens")
        return 0

    failed = calibration_failed = 0
    for cid in channels:
        r = reembed.reembed_channel(cid)
        failed += r["failed"]
        print(json.dumps(r))
        if args.skip_calibrate:
            continue
        try:
            thresholds = reembed.calibrate_channel(cid)
        except Exception as e:
            calibration_failed += 1
            print(json.dumps({"channel_id": cid, "calibration_error": f"{type(e).__name__}: {e}"}))
            continue
        print(json.dumps({"channel_id": cid, "thresholds": thresholds}))
    if failed:
        print(f"{failed} videos failed to embed; rerun to retry them")
    if calibration_failed:
        print(f"{calibration_failed} channels failed to calibrate; rerun to retry them")
    return 1 if failed or calibration_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
