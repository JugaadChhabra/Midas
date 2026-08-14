"""First-boot provisioning: an empty database restores itself from the NAS.

Self-hosting put the database on the machine that runs the container, and
`./pgdata` starts empty on a machine that has never run Midas before. Postgres
happily creates a blank cluster, PostgREST happily serves it, and the app comes
up 404-ing on every table — which looks like a broken deploy rather than an
unprovisioned one.

So the container provisions itself: on startup, if the database has no data, it
pulls last night's snapshot off the NAS and restores it. Deploying to a new
machine is then `docker compose up` plus a `.env`, which is the point — the tool
is meant to be run by someone who should never have to know what psql is.

FAIL CLOSED, deliberately. If the database is empty and the NAS is unreachable,
this raises and the app does not start. Starting anyway would be far worse than
not starting: the app would serve an empty catalogue as if it were real, and at
midnight `app/backup.py` would dump that empty database over the last good
snapshot on the NAS — turning a missing mount into permanent data loss. An
unreachable NAS is not a reason to skip the restore; it is the reason to stop.

The same rule guards the other direction: `snapshot_to_nas()` refuses to publish
a dump of an empty database (see `assert_populated`).
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.config import settings

log = logging.getLogger("midas.provision")

#: The table whose presence means "this database has been provisioned". Any of
#: the big ones would do; `videos` is the one nothing else can be populated
#: without.
SENTINEL_TABLE = "videos"

#: Restoring 366 MB takes a couple of minutes. This is a backstop against a
#: hung psql, not a target.
RESTORE_TIMEOUT_SECONDS = 60 * 60


class ProvisionError(RuntimeError):
    """The database is empty and could not be restored. The app must not start."""


def _connect():
    import psycopg
    if not settings.DATABASE_URL:
        raise ProvisionError("DATABASE_URL is not set — cannot check the database")
    return psycopg.connect(settings.DATABASE_URL)


def is_populated(conn) -> bool:
    """True if the sentinel table exists AND has at least one row.

    Both halves matter: a machine that has only ever run apply_migrations has
    the table and no data, and that is just as unprovisioned as no schema at all.
    """
    with conn.cursor() as cur:
        cur.execute("select to_regclass(%s)", (f"public.{SENTINEL_TABLE}",))
        if cur.fetchone()[0] is None:
            return False
        # `limit 1`, not count(*): this runs on every boot and only the presence
        # of a row is being asked about.
        cur.execute(f"select 1 from {SENTINEL_TABLE} limit 1")
        return cur.fetchone() is not None


def assert_populated(context: str) -> None:
    """Raise unless the database has data.

    Guards the nightly backup: a dump taken while the database is empty is a
    valid, complete, useless file, and publishing it destroys the only real
    snapshot. `_verify`'s completion marker cannot catch that — the dump *did*
    complete.
    """
    with _connect() as conn:
        if not is_populated(conn):
            raise ProvisionError(
                f"{context}: the database is empty. Refusing — publishing this "
                f"would overwrite the last good snapshot with nothing."
            )


BOOTSTRAP_DIR = Path(__file__).resolve().parents[1] / "supabase" / "bootstrap"
#: Run before the restore. The rest of the bootstrap runs after it.
ROLES_SQL = "000_roles.sql"


def _apply_sql(conn, *names: str) -> None:
    for name in names:
        log.info("provision: applying %s", name)
        with conn.cursor() as cur:
            cur.execute((BOOTSTRAP_DIR / name).read_text())
        conn.commit()


def _bootstrap_roles(conn) -> None:
    """Create the roles the dump's GRANT statements reference.

    A plain pg_dump carries schemas but NOT roles — roles are cluster-level, so
    they are absent from the snapshot while `anon`/`service_role` are named all
    through it. They have to exist before the restore starts.
    """
    _apply_sql(conn, ROLES_SQL)


def _bootstrap_rest(conn) -> None:
    """Everything else, after the restore.

    Not before: the dump contains its own `CREATE SCHEMA storage`, which
    collides with a pre-created one and stops the restore dead. And the object
    grants are meaningless until there are objects to grant on.
    """
    rest = sorted(p.name for p in BOOTSTRAP_DIR.glob("*.sql") if p.name != ROLES_SQL)
    _apply_sql(conn, *rest)


def has_planner_stats(conn) -> bool:
    """True if the sentinel table has been analyzed at least once.

    A psql restore replays INSERTs and CREATE INDEXes but carries no planner
    statistics — those are computed, not dumped. Until something analyzes the
    tables, `pg_statistic` is empty and the planner falls back to hardcoded
    guesses, which on tables this size means sequential scans over the indexes
    the dump just built. Every read is slow, nothing is broken, and no error is
    logged anywhere — the failure presents as "the app is inexplicably sluggish".

    Autovacuum does get there eventually, which is why it looks fine on a machine
    that has been up for days and terrible on one restored an hour ago.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select coalesce(last_analyze, last_autoanalyze) is not null "
            "from pg_stat_user_tables where relname = %s",
            (SENTINEL_TABLE,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def _analyze(conn) -> None:
    """ANALYZE the whole database, so the planner has numbers to work with.

    Minutes on a 1.5M-row database, once. Deliberately not VACUUM ANALYZE: the
    rows are freshly inserted so there is nothing dead to reclaim, and VACUUM
    cannot run inside the transaction this connection is already in.
    """
    log.warning("provision: no planner statistics — running ANALYZE (minutes, once)")
    with conn.cursor() as cur:
        cur.execute("analyze")
    conn.commit()
    log.info("provision: ANALYZE complete")


def _restore(dump: Path) -> None:
    """Replay `dump` into DATABASE_URL with psql."""
    binary = settings.RESTORE_PSQL
    try:
        proc = subprocess.run(
            [binary, settings.DATABASE_URL, "-v", "ON_ERROR_STOP=1",
             "--quiet", "--file", str(dump)],
            capture_output=True, text=True, timeout=RESTORE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        raise ProvisionError(
            f"{binary} not found — set RESTORE_PSQL to a psql binary"
        ) from e
    if proc.returncode != 0:
        # ON_ERROR_STOP is what makes this reachable. Without it psql reports
        # failures on stderr and still exits 0, which is how a half-restored
        # database gets mistaken for a good one.
        raise ProvisionError(f"psql restore failed ({proc.returncode}): "
                             f"{proc.stderr.strip()[:2000]}")


def _latest_snapshot(nas) -> str:
    """Name of the most recent snapshot on the NAS.

    BACKUP_SLOTS=2 alternates between `midas.0.sql` and `midas.1.sql` by
    day-of-year, so there is no single fixed filename to restore — and right
    after the setting is raised from 1 the only backup that exists is still the
    old `midas.sql`. Pick by modification time across whatever is actually
    there, which is correct under every slot configuration including a change of
    one.
    """
    from app.backup import NAS_SUBDIR, is_snapshot_name
    names = [n for n in nas.list_files(NAS_SUBDIR) if is_snapshot_name(n)]
    if not names:
        raise ProvisionError(
            f"database is empty and the NAS has no snapshot in {NAS_SUBDIR}. "
            f"Not starting: there is nothing to restore from."
        )
    return max(names, key=lambda n: nas.modified_at(f"{NAS_SUBDIR}/{n}"))


def _reload_postgrest(conn) -> None:
    """Tell PostgREST to re-read the schema.

    It caches the schema at startup and both services are gated only on the
    database being *healthy*, so PostgREST has already cached the EMPTY schema
    by the time this runs. Without this every request 404s until it is
    restarted — the restore would look like it had not worked.
    """
    with conn.cursor() as cur:
        cur.execute("notify pgrst, 'reload schema'")
    conn.commit()


def ensure_database_populated() -> dict:
    """Restore from the NAS if the database is empty. Returns a summary dict.

    Raises ProvisionError if the database is empty and cannot be restored —
    the caller must let that propagate and keep the app down.
    """
    if not settings.RESTORE_ON_EMPTY:
        log.info("provision: skipped (RESTORE_ON_EMPTY=false)")
        return {"restored": False, "reason": "disabled"}

    with _connect() as conn:
        if is_populated(conn):
            # Not just "nothing to do": a database restored by an earlier boot of
            # an older image, or by hand from a host checkout, has the data and no
            # statistics. Checking here rather than only after a restore is what
            # repairs those machines — the restore branch below never runs again
            # once the data is in.
            if not has_planner_stats(conn):
                _analyze(conn)
                return {"restored": False, "reason": "already_populated",
                        "analyzed": True}
            log.info("provision: database already has data; nothing to do")
            return {"restored": False, "reason": "already_populated"}

    log.warning("provision: database is EMPTY — restoring from the NAS snapshot")

    # Imported here so a machine that never provisions does not pay for the SMB
    # stack, and so app.backup's constants stay the single definition of where
    # the snapshot lives.
    from app.backup import NAS_SUBDIR, SNAPSHOT_NAME, _verify
    from app.services.nas_service import NASService

    work_dir = Path(settings.BACKUP_WORK_DIR)
    work_dir.mkdir(parents=True, exist_ok=True)
    local = work_dir / f"restore-{SNAPSHOT_NAME}"

    try:
        try:
            nas = NASService()
            snapshot = _latest_snapshot(nas)
            log.info("provision: restoring from %s", snapshot)
            nas.copy_to_local(f"{NAS_SUBDIR}/{snapshot}", local)
        except ProvisionError:
            raise
        except Exception as e:
            raise ProvisionError(
                f"database is empty and the NAS snapshot could not be fetched "
                f"({type(e).__name__}: {e}). Not starting: an empty database "
                f"would be served as real and dumped over the snapshot tonight."
            ) from e

        size = _verify(local)          # same completion-marker check the dump gets
        log.info("provision: restoring %.1f MB snapshot", size / 1_048_576)

        with _connect() as conn:
            _bootstrap_roles(conn)
        _restore(local)
        with _connect() as conn:
            if not is_populated(conn):
                raise ProvisionError(
                    "restore reported success but the database is still empty"
                )
            _bootstrap_rest(conn)
            # Before PostgREST is told to serve it: the app starts taking traffic
            # the moment the schema reloads, and the first thing it does is the
            # dashboard's whole-table reads. Analyzing after that point means the
            # first minutes of every fresh deploy run on guessed plans.
            _analyze(conn)
            _reload_postgrest(conn)
    finally:
        local.unlink(missing_ok=True)

    log.warning("provision: restored from the NAS snapshot (%.1f MB)", size / 1_048_576)
    return {"restored": True, "bytes": size}
