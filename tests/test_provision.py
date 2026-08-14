"""First boot restores from the NAS, and never guesses when it can't.

A machine that has never run Midas starts with an empty ./pgdata. The container
provisions itself so that deploying is `docker compose up` plus a `.env` — but
the failure mode being guarded here is the one that costs data, not the one that
costs a deploy:

    empty DB + unreachable NAS -> app serves an empty catalogue as if real
                               -> 00:00 backup dumps it OVER the good snapshot
                               -> the data is gone, and nothing said so

So an unreachable NAS stops the app rather than being shrugged off, and the
nightly backup independently refuses to publish a dump of an empty database.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import provision
from app.provision import ProvisionError

GOOD_DUMP = "-- PostgreSQL database dump\nCOPY x FROM stdin;\n--\n-- PostgreSQL database dump complete\n--\n"


@pytest.fixture
def conn():
    """A psycopg connection stub usable as a context manager."""
    c = MagicMock()
    c.__enter__.return_value = c
    c.cursor.return_value.__enter__.return_value = c.cursor.return_value
    return c


def _rows(conn, table_exists=True, has_row=True):
    cur = conn.cursor.return_value
    cur.fetchone.side_effect = [
        ("public.videos",) if table_exists else (None,),
        (1,) if has_row else None,
    ]


# ── is_populated ──────────────────────────────────────────────────────────

def test_missing_table_is_not_populated(conn):
    _rows(conn, table_exists=False)
    assert provision.is_populated(conn) is False


def test_table_with_no_rows_is_not_populated(conn):
    """A machine that only ran apply_migrations has the schema and no data.
    That is just as unprovisioned as having no schema at all."""
    _rows(conn, has_row=False)
    assert provision.is_populated(conn) is False


def test_table_with_rows_is_populated(conn):
    _rows(conn)
    assert provision.is_populated(conn) is True


# ── ensure_database_populated ─────────────────────────────────────────────

def _run(tmp_path, *, populated_before, populated_after=True, nas=None,
         dump=GOOD_DUMP, has_stats=True):
    """Drive the whole path with the database and NAS mocked out."""
    states = iter([populated_before, populated_after, populated_after])
    nas = nas or MagicMock()
    order: list[str] = []

    def fake_copy(remote, dest):
        Path(dest).write_text(dump)
        return dest

    if not hasattr(nas.copy_to_local, "side_effect") or nas.copy_to_local.side_effect is None:
        nas.copy_to_local.side_effect = fake_copy
    # One snapshot on the NAS unless a test says otherwise; _latest_snapshot
    # picks from a real listing now that BACKUP_SLOTS can be >1.
    if not isinstance(nas.list_files.return_value, list):
        nas.list_files.return_value = ["midas.sql"]
        nas.modified_at.return_value = 100.0

    with patch.object(provision.settings, "RESTORE_ON_EMPTY", True), \
         patch.object(provision.settings, "BACKUP_WORK_DIR", str(tmp_path)), \
         patch.object(provision, "_connect") as connect, \
         patch.object(provision, "is_populated", lambda c: next(states)), \
         patch.object(provision, "_bootstrap_roles",
                      side_effect=lambda c: order.append("roles")) as bootstrap, \
         patch.object(provision, "_bootstrap_rest",
                      side_effect=lambda c: order.append("shim")), \
         patch.object(provision, "_restore",
                      side_effect=lambda p: order.append("restore")) as restore, \
         patch.object(provision, "_reload_postgrest",
                      side_effect=lambda c: order.append("reload")) as reload_, \
         patch.object(provision, "_analyze",
                      side_effect=lambda c: order.append("analyze")), \
         patch.object(provision, "has_planner_stats", lambda c: has_stats), \
         patch("app.services.nas_service.NASService", return_value=nas):
        connect.return_value.__enter__.return_value = MagicMock()
        result = provision.ensure_database_populated()
    return result, bootstrap, restore, reload_, nas, order


def test_populated_database_is_left_alone(tmp_path):
    result, bootstrap, restore, _, nas, _order = _run(tmp_path, populated_before=True)
    assert result["restored"] is False
    restore.assert_not_called()
    bootstrap.assert_not_called()
    nas.copy_to_local.assert_not_called()   # no NAS round-trip on every boot


def test_empty_database_restores_from_the_nas(tmp_path):
    result, bootstrap, restore, reload_, nas, _order = _run(tmp_path, populated_before=False)
    assert result["restored"] is True
    nas.copy_to_local.assert_called_once()
    bootstrap.assert_called_once()          # roles are NOT in the dump
    restore.assert_called_once()
    reload_.assert_called_once()            # PostgREST cached the empty schema


def test_bootstrap_runs_before_the_restore(tmp_path):
    """Roles before, everything else after — a plain pg_dump carries schemas but
    NOT roles, so `anon`/`service_role` must pre-exist for its GRANTs, while
    pre-creating the storage schema collides with the dump's own CREATE SCHEMA
    and stops the restore dead."""
    *_, order = _run(tmp_path, populated_before=False)
    assert order == ["roles", "restore", "shim", "analyze", "reload"]


def test_a_restore_is_analyzed_before_postgrest_serves_it(tmp_path):
    """A psql restore carries no planner statistics, so the planner guesses and
    every read seq-scans the indexes the dump just built. Nothing errors; the app
    is simply slow until autovacuum catches up hours later. ANALYZE has to land
    before the schema reload, because that is when traffic starts."""
    *_, order = _run(tmp_path, populated_before=False)
    assert order.index("analyze") < order.index("reload")


def test_a_populated_database_with_no_statistics_is_analyzed(tmp_path):
    """The repair path for machines already restored by an older image.

    Those never re-enter the restore branch — they have the data — so analyzing
    only after a restore would leave them permanently slow.
    """
    result, _b, restore, _r, nas, order = _run(
        tmp_path, populated_before=True, has_stats=False)
    assert result == {"restored": False, "reason": "already_populated",
                      "analyzed": True}
    assert order == ["analyze"]
    restore.assert_not_called()             # the data is fine; only stats are missing
    nas.copy_to_local.assert_not_called()   # and no NAS round-trip to fix them


def test_a_populated_database_with_statistics_is_left_alone(tmp_path):
    """ANALYZE takes minutes on 1.5M rows — it must not run on every boot."""
    result, *_rest, order = _run(tmp_path, populated_before=True, has_stats=True)
    assert result == {"restored": False, "reason": "already_populated"}
    assert order == []


def test_unreachable_nas_stops_the_app(tmp_path):
    """The whole point: no NAS, no guessing. Starting empty would serve a fake
    catalogue and then overwrite the real snapshot at midnight."""
    nas = MagicMock()
    nas.copy_to_local.side_effect = OSError("host is down")
    with pytest.raises(ProvisionError, match="NAS snapshot could not be fetched"):
        _run(tmp_path, populated_before=False, nas=nas)


def test_truncated_snapshot_is_refused(tmp_path):
    """A dump with no completion marker is a partial file; restoring it would
    silently produce a partial database."""
    with pytest.raises(Exception) as e:
        _run(tmp_path, populated_before=False, dump="-- PostgreSQL database dump\nCOPY")
    assert "completion marker" in str(e.value)


def test_restore_that_leaves_the_db_empty_is_an_error(tmp_path):
    with pytest.raises(ProvisionError, match="still empty"):
        _run(tmp_path, populated_before=False, populated_after=False)


def test_the_downloaded_snapshot_is_not_left_on_disk(tmp_path):
    """366 MB of the entire database, in a bind-mounted directory."""
    _run(tmp_path, populated_before=False)
    assert not list(tmp_path.glob("restore-*")), "snapshot left on local disk"


def test_failure_still_cleans_up_the_download(tmp_path):
    with pytest.raises(ProvisionError):
        _run(tmp_path, populated_before=False, populated_after=False)
    assert not list(tmp_path.glob("restore-*"))


def test_can_be_switched_off(tmp_path):
    with patch.object(provision.settings, "RESTORE_ON_EMPTY", False), \
         patch.object(provision, "_connect") as connect:
        result = provision.ensure_database_populated()
    assert result == {"restored": False, "reason": "disabled"}
    connect.assert_not_called()


# ── the other direction: never dump an empty DB over a good snapshot ──────

def test_assert_populated_raises_on_an_empty_database():
    with patch.object(provision, "_connect") as connect, \
         patch.object(provision, "is_populated", return_value=False):
        connect.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(ProvisionError, match="overwrite the last good snapshot"):
            provision.assert_populated("nightly backup")


def test_assert_populated_passes_on_a_real_database():
    with patch.object(provision, "_connect") as connect, \
         patch.object(provision, "is_populated", return_value=True):
        connect.return_value.__enter__.return_value = MagicMock()
        provision.assert_populated("nightly backup")      # does not raise


def test_nightly_backup_refuses_to_publish_from_an_empty_database(tmp_path):
    """pg_dump of an empty DB completes successfully — the completion marker
    cannot tell it apart from a real snapshot."""
    from app import backup
    nas = MagicMock()
    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump") as dump, \
         patch("app.provision._connect") as connect, \
         patch("app.provision.is_populated", return_value=False):
        connect.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(ProvisionError):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path)
    dump.assert_not_called()                 # refused before spending the dump
    nas.copy_from_local.assert_not_called()  # and before touching the NAS


# ── which snapshot to restore, under BACKUP_SLOTS ─────────────────────────

def _nas_with(files: dict[str, float]):
    """A NAS stub holding {name: mtime} under the backup directory."""
    nas = MagicMock()
    nas.list_files.return_value = sorted(files)
    nas.modified_at.side_effect = lambda p: files[p.rsplit("/", 1)[-1]]
    return nas


def test_single_slot_restores_the_one_snapshot():
    assert provision._latest_snapshot(_nas_with({"midas.sql": 100.0})) == "midas.sql"


def test_two_slots_restore_the_newer_one():
    """BACKUP_SLOTS=2 alternates by day-of-year, so there is no fixed filename —
    yesterday's slot sits right beside today's."""
    nas = _nas_with({"midas.0.sql": 100.0, "midas.1.sql": 200.0})
    assert provision._latest_snapshot(nas) == "midas.1.sql"
    nas = _nas_with({"midas.0.sql": 300.0, "midas.1.sql": 200.0})
    assert provision._latest_snapshot(nas) == "midas.0.sql"


def test_a_legacy_single_slot_file_is_still_found_after_raising_slots():
    """Raising BACKUP_SLOTS from 1 to 2 leaves midas.sql as the ONLY backup
    until the next nightly run. A restore in that window must still find it."""
    assert provision._latest_snapshot(_nas_with({"midas.sql": 100.0})) == "midas.sql"


def test_the_staged_upload_is_never_restored():
    """A .tmp is a half-uploaded file by definition, and it is the newest thing
    in the directory while it is being written."""
    nas = _nas_with({"midas.sql": 100.0, "midas.sql.tmp": 999.0})
    assert provision._latest_snapshot(nas) == "midas.sql"


def test_unrelated_files_are_ignored():
    nas = _nas_with({"midas.sql": 100.0, "notes.txt": 999.0, "midas.sql.gz": 999.0})
    assert provision._latest_snapshot(nas) == "midas.sql"


def test_no_snapshot_at_all_stops_the_app():
    with pytest.raises(ProvisionError, match="no snapshot"):
        provision._latest_snapshot(_nas_with({}))
