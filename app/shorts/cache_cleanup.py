"""Delete shorts-cutter cache folders that nothing needs any more.

Each job works in SHORTS_CACHE_DIR/<job id>/. A NAS job removes its own folder
when it ends (app/shorts/runner.py); this sweeps what is left:

- folders of NAS jobs (their clips are on the NAS), e.g. from before the
  runner cleaned up after itself, or from a process killed mid-job;
- folders of jobs no longer in the database;
- folders of YouTube-URL / AutoShorts jobs untouched for `keep_days`: their
  clips are served from disk by GET /shorts/clips/{id}/file and uploaded from
  disk by POST /shorts/clips/{id}/upload, so they are kept that long;
- anything else in the cache (stray files, old layouts) untouched for `keep_days`.

A folder whose job is still queued or running is never touched.
Run daily by the `shorts_cache_cleanup` job and by scripts/clean_shorts_cache.py.
"""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from app.config import settings
from app.db import supabase
from app.rows import rows_for_ids
from app.shorts.status import WORKING_STATUSES

log = logging.getLogger("midas.shorts.cache_cleanup")

DEFAULT_KEEP_DAYS = 7


def _size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        return path.lstat().st_size
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _last_touched(path: Path) -> float:
    """Newest mtime of the entry or anything under it."""
    newest = path.lstat().st_mtime
    if path.is_dir() and not path.is_symlink():
        for p in path.rglob("*"):
            try:
                newest = max(newest, p.lstat().st_mtime)
            except OSError:
                pass
    return newest


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _jobs(ids: list[int]) -> dict[int, dict]:
    rows = rows_for_ids(
        lambda c: supabase().table("shorts_jobs")
        .select("id,status,source_nas_path").in_("id", c),
        ids,
    )
    return {int(r["id"]): r for r in rows}


def clean_cache(*, keep_days: float = DEFAULT_KEEP_DAYS, dry_run: bool = False,
                cache_dir: str | Path | None = None, now: float | None = None) -> dict:
    """Delete what the rules above allow. Returns
    {"removed": [{name, reason, bytes}], "kept": n, "freed_bytes": n, "dry_run"}."""
    root = Path(cache_dir or settings.SHORTS_CACHE_DIR).resolve()
    # A misconfigured SHORTS_CACHE_DIR must not turn this into rm -rf of home.
    if root in (Path("/").resolve(), Path.home().resolve()) or len(root.parts) < 3:
        raise ValueError(f"refusing to clean {root}: not a cache directory")
    result = {"removed": [], "kept": 0, "freed_bytes": 0, "dry_run": dry_run}
    if not root.is_dir():
        return result

    entries = sorted(root.iterdir())
    job_ids = [int(e.name) for e in entries if e.is_dir() and e.name.isdigit()]
    jobs = _jobs(job_ids)
    cutoff = (now if now is not None else time.time()) - keep_days * 86400

    for entry in entries:
        reason = None
        if entry.is_dir() and entry.name.isdigit():
            job = jobs.get(int(entry.name))
            if job is None:
                reason = "job not in database"
            elif (job.get("status") or "").upper() in WORKING_STATUSES:
                reason = None                      # queued or running: hands off
            elif job.get("source_nas_path"):
                reason = "NAS job: clips are on the NAS"
            elif _last_touched(entry) < cutoff:
                reason = f"untouched for {keep_days:g}+ days"
        elif _last_touched(entry) < cutoff:
            reason = f"untouched for {keep_days:g}+ days"

        if reason is None:
            result["kept"] += 1
            continue
        size = _size(entry)
        if not dry_run:
            _remove(entry)
        result["removed"].append({"name": entry.name, "reason": reason, "bytes": size})
        result["freed_bytes"] += size

    log.info("Shorts cache cleanup%s: %d removed (%.1f MB), %d kept",
             " (dry run)" if dry_run else "", len(result["removed"]),
             result["freed_bytes"] / 1e6, result["kept"])
    return result


def run_daily() -> None:
    """The `shorts_cache_cleanup` job."""
    clean_cache(keep_days=settings.SHORTS_CACHE_KEEP_DAYS)
