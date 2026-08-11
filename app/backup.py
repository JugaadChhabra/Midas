"""Nightly Postgres snapshot to the NAS.

Self-hosting moved the database onto one machine, which makes this the entire
disaster-recovery story. One snapshot is kept and replaced each night, so the
worst case is losing the current day's work — the accepted trade.

The obvious implementation — dump straight onto yesterday's file — has a hole:
a dump that dies partway through (disk full, container restart, NAS drop)
overwrites the last good backup with a truncated one, and nothing says so until
someone tries to restore. So the snapshot is published in stages:

    pg_dump -> local temp -> verify it completed -> upload as .tmp -> move

A failure at any stage leaves the previous snapshot exactly where it was.

RESIDUAL RISK, worth knowing: this keeps ONE snapshot. If the database is
already corrupt when tonight's dump runs, tonight's good-looking dump replaces
the last healthy copy. Keeping two slots (alternating by day-of-year) costs one
extra file and removes that failure mode; set BACKUP_SLOTS=2 to enable it.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.services.nas_service import NASService

log = logging.getLogger("midas.backup")

#: Directory on the NAS, relative to its root.
NAS_SUBDIR = "midas-db-backups"
#: The single snapshot's name. Deliberately not dated: one file, replaced.
SNAPSHOT_NAME = "midas.sql"
#: pg_dump writes this as its last line. Its absence means a truncated file.
COMPLETION_MARKER = "PostgreSQL database dump complete"

#: pg_dump can outlive a short timeout on a large DB; this is a backstop, not a
#: target. Exceeded means something is wrong, not that the DB is merely big.
DUMP_TIMEOUT_SECONDS = 60 * 60


class BackupError(RuntimeError):
    """The snapshot did not complete. The previous one is still intact."""


def _nas() -> NASService:
    return NASService()


def _run_pg_dump(dsn: str, dest: Path) -> None:
    """Dump `dsn` to `dest`. Raises BackupError on any non-zero exit."""
    binary = settings.BACKUP_PG_DUMP
    try:
        proc = subprocess.run(
            [binary, "--no-owner", "--no-privileges", "--file", str(dest), dsn],
            capture_output=True,
            text=True,
            timeout=DUMP_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        raise BackupError(
            f"{binary} not found — set BACKUP_PG_DUMP to a pg_dump at least as "
            f"new as the server"
        ) from e
    if proc.returncode != 0:
        # The most common failure by far is a client older than the server,
        # which pg_dump reports on stderr and nowhere else.
        raise BackupError(f"pg_dump failed ({proc.returncode}): {proc.stderr.strip()}")


def _verify(dump: Path) -> int:
    """Return the dump's size, or raise if it is not a complete dump."""
    if not dump.is_file():
        raise BackupError("pg_dump produced no file")
    size = dump.stat().st_size
    if size == 0:
        raise BackupError("pg_dump produced an empty file")
    # Reading the tail is enough — the marker is the final line.
    with dump.open("rb") as f:
        f.seek(max(0, size - 4096))
        tail = f.read().decode("utf-8", errors="replace")
    if COMPLETION_MARKER not in tail:
        raise BackupError(
            "dump is incomplete — no completion marker; refusing to publish it "
            "over the last good snapshot"
        )
    return size


def _slot_name(now: datetime, slots: int) -> str:
    """Snapshot filename. One slot => a single replaced file."""
    if slots <= 1:
        return SNAPSHOT_NAME
    stem, _, ext = SNAPSHOT_NAME.rpartition(".")
    return f"{stem}.{now.timetuple().tm_yday % slots}.{ext}"


def snapshot_to_nas(*, dsn: str | None = None, work_dir: Path | None = None,
                    now: datetime | None = None) -> dict:
    """Dump the database and publish it to the NAS. Returns a summary dict."""
    dsn = dsn or settings.DATABASE_URL
    if not dsn:
        raise BackupError("DATABASE_URL is not set — nothing to dump")
    now = now or datetime.now(timezone.utc)
    work_dir = Path(work_dir or settings.BACKUP_WORK_DIR)
    work_dir.mkdir(parents=True, exist_ok=True)

    local = work_dir / f"midas-{now:%Y%m%dT%H%M%S}.sql"
    final = _slot_name(now, settings.BACKUP_SLOTS)
    staged = f"{final}.tmp"

    nas = _nas()
    try:
        _run_pg_dump(dsn, local)
        size = _verify(local)

        nas.makedirs(NAS_SUBDIR)
        # Upload under a temp name, then move: the move is the only step that
        # touches the live snapshot, and it happens after the bytes are there.
        nas.copy_from_local(local, f"{NAS_SUBDIR}/{staged}")
        nas.move(f"{NAS_SUBDIR}/{staged}", f"{NAS_SUBDIR}/{final}")
    finally:
        # Never leave the dump on the app's disk — it is a full copy of the DB
        # and this directory is a bind mount.
        local.unlink(missing_ok=True)

    log.info("DB snapshot published to NAS: %s (%.1f MB)", final, size / 1_048_576)
    return {"ok": True, "file": final, "bytes": size, "at": now.isoformat()}


def run_nightly_backup() -> None:
    """APScheduler entry point. Never raises — a failed backup must not take
    the scheduler down, but it MUST be loud in the log."""
    if not settings.BACKUP_ENABLED:
        log.info("Nightly DB backup skipped (BACKUP_ENABLED=false)")
        return
    try:
        result = snapshot_to_nas()
        log.info("Nightly DB backup ok: %s", result)
    except Exception as e:
        # A silent backup failure is how you discover, months later, that there
        # is no backup. This is the one log line worth alerting on.
        log.exception("NIGHTLY DB BACKUP FAILED — last good snapshot is stale: %s", e)


def _restore_instructions() -> str:
    """Printed by the health endpoint's backup section; also the runbook."""
    return (
        f"Restore: copy {NAS_SUBDIR}/{SNAPSHOT_NAME} from the NAS, then\n"
        f"  docker compose down midas\n"
        f"  psql $DATABASE_URL -f {SNAPSHOT_NAME}\n"
        f"  docker compose up -d midas\n"
        f"The dump is --no-owner --no-privileges, so it restores into a fresh\n"
        f"database without needing the original roles; run\n"
        f"  python scripts/apply_migrations.py\n"
        f"afterwards only if the dump predates a migration."
    )
