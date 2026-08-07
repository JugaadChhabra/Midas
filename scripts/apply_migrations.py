#!/usr/bin/env python3
"""Apply the SQL ledger to a self-hosted Postgres, in order, exactly once.

Supabase applied `supabase/migrations/*.sql` for us. Self-hosted, something has
to, and it has to be idempotent — the container restarts.

    python scripts/apply_migrations.py                 # apply what's pending
    python scripts/apply_migrations.py --dry-run       # list what would apply
    python scripts/apply_migrations.py --status        # what's applied so far

Order is filename order, which is timestamp order — the same order Supabase
applied them in. `supabase/bootstrap/*.sql` runs first: it provides the roles
and the storage.buckets shim the historical migrations assume (see that file).

Each file runs in its own transaction. A failure rolls that file back and
stops, so a half-applied migration can't be recorded as done.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:
    sys.exit("psycopg is required: pip install 'psycopg[binary]'")

REPO = Path(__file__).resolve().parents[1]
BOOTSTRAP_DIR = REPO / "supabase" / "bootstrap"
MIGRATIONS_DIR = REPO / "supabase" / "migrations"

LEDGER = """
create table if not exists schema_migrations (
    filename    text primary key,
    sha256      text not null,
    applied_at  timestamptz not null default now()
);
"""


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "  local:  postgresql://midas:<pw>@localhost:5432/midas\n"
            "  compose: it is set for you in docker-compose.yml"
        )
    return dsn


def _sql_files() -> list[Path]:
    """Bootstrap first, then migrations in timestamp order."""
    bootstrap = sorted(BOOTSTRAP_DIR.glob("*.sql")) if BOOTSTRAP_DIR.is_dir() else []
    return bootstrap + sorted(MIGRATIONS_DIR.glob("*.sql"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _applied(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("select filename, sha256 from schema_migrations")
        return dict(cur.fetchall())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list pending, apply nothing")
    ap.add_argument("--status", action="store_true", help="show the ledger and exit")
    args = ap.parse_args()

    files = _sql_files()
    if not files:
        print("No .sql files found — wrong working directory?")
        return 1

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        conn.execute(LEDGER)
        applied = _applied(conn)

        if args.status:
            for f in files:
                mark = "applied" if f.name in applied else "PENDING"
                drift = ""
                if f.name in applied and applied[f.name] != _digest(f):
                    drift = "  ** CONTENT CHANGED SINCE IT WAS APPLIED **"
                print(f"  [{mark:>7}] {f.name}{drift}")
            return 0

        # A file whose content changed after being applied is a real hazard: the
        # DB no longer matches the ledger and re-running is not safe in general.
        # Report it rather than silently re-applying or silently skipping.
        drifted = [
            f.name for f in files
            if f.name in applied and applied[f.name] != _digest(f)
        ]
        if drifted:
            print("Refusing to run — these files changed after being applied:")
            for name in drifted:
                print(f"  {name}")
            print("Migrations are an applied ledger. Add a new file instead.")
            return 1

        pending = [f for f in files if f.name not in applied]
        if not pending:
            print(f"Up to date — {len(applied)} migration(s) already applied.")
            return 0

        print(f"{len(pending)} pending:")
        for f in pending:
            print(f"  {f.name}")
        if args.dry_run:
            return 0

        for f in pending:
            sql = f.read_text()
            try:
                # Own transaction per file: a failure leaves nothing behind and
                # the ledger row is written only if the DDL committed.
                with psycopg.connect(_dsn()) as tx:
                    with tx.cursor() as cur:
                        cur.execute(sql)
                        cur.execute(
                            "insert into schema_migrations (filename, sha256) values (%s, %s)",
                            (f.name, _digest(f)),
                        )
                    tx.commit()
            except Exception as e:
                print(f"\nFAILED on {f.name}:\n  {e}")
                print("Nothing from this file was applied. Fix it and re-run.")
                return 1
            print(f"  applied {f.name}")

        print(f"\nDone — {len(pending)} applied.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
