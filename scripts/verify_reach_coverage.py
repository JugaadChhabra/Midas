"""Phase 0/0.5 exit-gate check: is a channel's CTR coverage certified?

Read-only. Prints the coverage report from `reach.certify` (>=7 contiguous
ingested reach data-days = "≥1 week of trustworthy CTR", the Phase 0 exit
gate). Use this before flipping `measurement_enabled` on a channel —
the PATCH /channels/{id} endpoint enforces the same check, this is the ops view.

Exits non-zero when a named channel is NOT certified, so it can gate a deploy
step. With --all it reports every analytics_authorized channel and exits 0.

Usage:
    PYTHONPATH=. python scripts/verify_reach_coverage.py <channel_id>
    PYTHONPATH=. python scripts/verify_reach_coverage.py --all
"""

from __future__ import annotations

import sys


def _report(channel_id: str) -> dict:
    from app.reach import certify

    cov = certify(channel_id)
    mark = "OK " if cov["certified"] else "NOT"
    print(
        f"[{mark}] {channel_id}: "
        f"contiguous={cov['contiguous_days']}/{cov['min_days']}d "
        f"covered_total={cov['covered_total']} latest={cov['latest_day']}"
    )
    return cov


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    try:
        from app.db import supabase
    except Exception as e:  # pragma: no cover - import-time config guard
        print(f"cannot load app config (missing creds?): {e}")
        return 2

    arg = sys.argv[1]
    if arg == "--all":
        try:
            rows = (
                supabase().table("channels").select("id")
                .eq("analytics_authorized", True).execute().data or []
            )
        except Exception as e:
            print(f"cannot reach Supabase (missing creds?): {e}")
            return 2
        if not rows:
            print("no analytics_authorized channels")
            return 0
        for r in rows:
            _report(r["id"])
        return 0

    try:
        cov = _report(arg)
    except Exception as e:
        print(f"cannot reach Supabase (missing creds?): {e}")
        return 2
    return 0 if cov["certified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
