"""Free disk by deleting shorts-cutter cache folders nothing needs any more.

    python scripts/clean_shorts_cache.py --dry-run     # list what would go
    python scripts/clean_shorts_cache.py               # delete it
    python scripts/clean_shorts_cache.py --days 2      # keep URL-job clips 2 days

On the Mac mini (inside the container, where SHORTS_CACHE_DIR points):
    docker compose exec midas python scripts/clean_shorts_cache.py --dry-run

Rules: app/shorts/cache_cleanup.py. Never touches a queued or running job.
The same sweep runs daily at 03:15 (the shorts_cache_cleanup job).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.shorts.cache_cleanup import clean_cache  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="list, delete nothing")
    ap.add_argument("--days", type=float, default=settings.SHORTS_CACHE_KEEP_DAYS,
                    help="keep YouTube-URL/AutoShorts clips this many days "
                         f"(default {settings.SHORTS_CACHE_KEEP_DAYS:g})")
    args = ap.parse_args()
    result = clean_cache(keep_days=args.days, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    for item in result["removed"]:
        print(f"{verb}  {item['name']:<12} {item['bytes'] / 1e6:9.1f} MB  {item['reason']}")
    print(f"{settings.SHORTS_CACHE_DIR}: {verb} {len(result['removed'])}, "
          f"kept {result['kept']}, {result['freed_bytes'] / 1e9:.2f} GB freed"
          + (" (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
