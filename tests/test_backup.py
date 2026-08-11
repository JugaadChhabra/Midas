"""The nightly DB snapshot, tested offline through NASService's local mode.

The whole point of self-hosting is that the DB now lives on one machine, so the
snapshot IS the disaster-recovery story. The dangerous shape is the one the plan
started from: dump straight over yesterday's file. A dump that dies halfway
through — disk full, container restart, NAS drop — then leaves a truncated file
where the last good backup was, and nothing says so until a restore is
attempted.

So: dump locally, verify the dump actually completed, upload under a temp name,
and only then move it into place. A failure at any step leaves the previous
snapshot untouched.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import backup

#: Captured before the autouse fixture below patches the module attribute, so
#: the version-match tests can exercise the real function.
_assert_versions_match = backup._assert_pg_dump_matches_server


@pytest.fixture(autouse=True)
def _guards_pass():
    """snapshot_to_nas refuses to run against an empty database or a mismatched
    pg_dump, both of which need a live server. Those two guards have their own
    tests below; here they are satisfied so each test is about its own failure."""
    with patch("app.provision.assert_populated"), \
         patch.object(backup, "_assert_pg_dump_matches_server"):
        yield


@pytest.fixture
def nas(tmp_path):
    """A real NASService in local mode — writes actual bytes to tmp_path."""
    from app.services.nas_service import NASService
    svc = NASService()
    svc.mode = "local"
    svc.local_root = tmp_path
    return svc


def _good_dump(path: Path) -> None:
    path.write_text("-- PostgreSQL database dump\nCREATE TABLE x();\n"
                    "-- PostgreSQL database dump complete\n")


def _fake_pg_dump(writer):
    """Patch _run_pg_dump with something that writes via `writer`."""
    def run(dsn, dest: Path):
        writer(dest)
    return run


# ── the happy path ────────────────────────────────────────────────────────

def test_snapshot_lands_on_the_nas(nas, tmp_path):
    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump", _fake_pg_dump(_good_dump)):
        out = backup.snapshot_to_nas(dsn="postgresql://x", work_dir=tmp_path / "w")

    landed = tmp_path / backup.NAS_SUBDIR / backup.SNAPSHOT_NAME
    assert landed.is_file()
    assert "dump complete" in landed.read_text()
    assert out["ok"] is True
    assert out["bytes"] > 0


def test_a_second_run_replaces_the_first(nas, tmp_path):
    landed = tmp_path / backup.NAS_SUBDIR / backup.SNAPSHOT_NAME

    def first(p): p.write_text("-- PostgreSQL database dump\nOLD\n-- PostgreSQL database dump complete\n")
    def second(p): p.write_text("-- PostgreSQL database dump\nNEW\n-- PostgreSQL database dump complete\n")

    with patch.object(backup, "_nas", return_value=nas):
        with patch.object(backup, "_run_pg_dump", _fake_pg_dump(first)):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path / "w")
        assert "OLD" in landed.read_text()
        with patch.object(backup, "_run_pg_dump", _fake_pg_dump(second)):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path / "w")

    assert "NEW" in landed.read_text()
    # One snapshot, not an accumulating pile — the stated intent.
    assert len(list((tmp_path / backup.NAS_SUBDIR).glob("*"))) == 1


# ── the failure modes that must not destroy the last good snapshot ────────

def test_a_failed_dump_leaves_the_previous_snapshot_intact(nas, tmp_path):
    landed = tmp_path / backup.NAS_SUBDIR / backup.SNAPSHOT_NAME

    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump", _fake_pg_dump(_good_dump)):
        backup.snapshot_to_nas(dsn="x", work_dir=tmp_path / "w")
    good = landed.read_text()

    def explode(dsn, dest):
        raise RuntimeError("pg_dump: connection to server failed")

    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump", explode):
        with pytest.raises(RuntimeError):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path / "w")

    assert landed.read_text() == good


def test_a_truncated_dump_is_rejected_before_it_reaches_the_nas(nas, tmp_path):
    """pg_dump killed mid-write exits non-zero, but belt-and-braces: a dump
    without its completion marker is not a dump."""
    def truncated(p):
        p.write_text("-- PostgreSQL database dump\nCREATE TABLE x();\n")  # no marker

    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump", _fake_pg_dump(truncated)):
        with pytest.raises(backup.BackupError, match="incomplete"):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path / "w")

    assert not (tmp_path / backup.NAS_SUBDIR / backup.SNAPSHOT_NAME).exists()


def test_an_empty_dump_is_rejected(nas, tmp_path):
    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump", _fake_pg_dump(lambda p: p.write_text(""))):
        with pytest.raises(backup.BackupError):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path / "w")


def test_upload_failure_leaves_no_temp_file_behind(nas, tmp_path):
    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump", _fake_pg_dump(_good_dump)), \
         patch.object(nas, "move", side_effect=OSError("NAS dropped")):
        with pytest.raises(OSError):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path / "w")

    # the staged .tmp must not be left masquerading as a backup
    remaining = list((tmp_path / backup.NAS_SUBDIR).glob("*"))
    assert all(not p.name.endswith(backup.SNAPSHOT_NAME) for p in remaining)


def test_local_working_copy_is_cleaned_up(nas, tmp_path):
    work = tmp_path / "w"
    with patch.object(backup, "_nas", return_value=nas), \
         patch.object(backup, "_run_pg_dump", _fake_pg_dump(_good_dump)):
        backup.snapshot_to_nas(dsn="x", work_dir=work)
    assert not any(work.glob("*.sql")), "dump left on local disk"


# ── the pg_dump invocation ────────────────────────────────────────────────

def test_pg_dump_is_invoked_with_the_dsn_and_fails_loudly():
    proc = MagicMock(returncode=1, stderr="could not connect")
    with patch.object(backup.settings, "BACKUP_PG_DUMP", "pg_dump"), \
         patch.object(backup.subprocess, "run", return_value=proc) as run:
        with pytest.raises(backup.BackupError, match="could not connect"):
            backup._run_pg_dump("postgresql://u:p@db:5432/midas", Path("/tmp/x.sql"))
    argv = run.call_args.args[0]
    assert argv[0] == "pg_dump"
    assert "postgresql://u:p@db:5432/midas" in argv


def test_pg_dump_binary_is_configurable():
    """The container has postgresql-client-16 on PATH; a dev machine may have
    only an older pg_dump, which refuses to dump a newer server."""
    proc = MagicMock(returncode=0, stderr="")
    with patch.object(backup.settings, "BACKUP_PG_DUMP", "/opt/pg16/bin/pg_dump"), \
         patch.object(backup.subprocess, "run", return_value=proc) as run:
        backup._run_pg_dump("dsn", Path("/tmp/x.sql"))
    assert run.call_args.args[0][0] == "/opt/pg16/bin/pg_dump"


def test_missing_pg_dump_names_the_setting_that_fixes_it():
    with patch.object(backup.settings, "BACKUP_PG_DUMP", "/nope/pg_dump"), \
         patch.object(backup.subprocess, "run", side_effect=FileNotFoundError):
        with pytest.raises(backup.BackupError, match="BACKUP_PG_DUMP"):
            backup._run_pg_dump("dsn", Path("/tmp/x.sql"))


# ── the client/server version match ───────────────────────────────────────

def _server(major):
    """psycopg.connect stub returning `major` from show server_version_num."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    cur.fetchone.return_value = (str(major * 10000 + 14),)
    return conn


def test_a_newer_pg_dump_than_the_server_is_refused():
    """The dangerous direction: pg_dump 18 runs fine against pg16 and writes
    `SET transaction_timeout = 0` (a pg17 parameter), so the restore dies on
    line 13 — months later, when someone finally needs the backup."""
    with patch("psycopg.connect", return_value=_server(16)), \
         patch.object(backup, "_binary_major", return_value=18):
        with pytest.raises(backup.BackupError, match="pg_dump is 18 but the server is 16"):
            _assert_versions_match("dsn")


def test_an_older_pg_dump_than_the_server_is_refused():
    with patch("psycopg.connect", return_value=_server(16)), \
         patch.object(backup, "_binary_major", return_value=14):
        with pytest.raises(backup.BackupError, match="pg_dump is 14"):
            _assert_versions_match("dsn")


def test_a_matching_pg_dump_passes():
    with patch("psycopg.connect", return_value=_server(16)), \
         patch.object(backup, "_binary_major", return_value=16):
        _assert_versions_match("dsn")      # does not raise


def test_binary_major_parses_the_version_string():
    proc = MagicMock(stdout="pg_dump (PostgreSQL) 16.14 (Homebrew)\n")
    with patch.object(backup.subprocess, "run", return_value=proc):
        assert backup._binary_major("pg_dump") == 16


def test_the_version_check_runs_before_the_dump(tmp_path):
    """Otherwise a mismatched client burns 90 seconds producing a file that is
    then published — the check has to gate the work, not follow it."""
    nas = MagicMock()
    with patch.object(backup, "_nas", return_value=nas), \
         patch("app.provision.assert_populated"), \
         patch.object(backup, "_assert_pg_dump_matches_server",
                      side_effect=backup.BackupError("mismatch")), \
         patch.object(backup, "_run_pg_dump") as dump:
        with pytest.raises(backup.BackupError, match="mismatch"):
            backup.snapshot_to_nas(dsn="x", work_dir=tmp_path)
    dump.assert_not_called()
    nas.copy_from_local.assert_not_called()
