#!/usr/bin/env python3
"""Load the NDJSON export from scripts/export_supabase.py into local Postgres.

    docker compose up -d db postgrest
    DATABASE_URL=postgresql://midas:<pw>@localhost:5432/midas \
      python scripts/apply_migrations.py      # schema first
    DATABASE_URL=... python scripts/import_to_local.py

Idempotent per table: each is truncated before loading, so a re-run replaces
rather than duplicates. Use --tables to redo one.

Four things this has to get right, all of which are silent if wrong:

  * **Insert order.** Tables are loaded parents-first so foreign keys resolve.
  * **jsonb.** PostgREST returned these as parsed objects; psycopg needs them
    re-serialised or it stores a Python repr. Which columns those are is read
    from information_schema, not hand-listed — the hand-written list was wrong
    in both directions on the first attempt.
  * **vector.** Comes back as the string '[0.1,...]', which is exactly the
    literal pgvector accepts — pass it through untouched, do not parse it.
  * **Sequences.** Rows carry explicit `id`s, so a bigserial's sequence stays
    at 1 and the app's very next insert collides. Every sequence is advanced
    past the loaded maximum at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    sys.exit("psycopg is required: pip install 'psycopg[binary]'")

EXPORT = Path(__file__).resolve().parents[1] / "migration_export"
BATCH = 500

#: Parents before children — foreign keys must resolve as we go.
#: channels <- videos <- audits; channels <- playlists <- playlist_assignments.

LOAD_ORDER = [
    "channels",
    "audit_configs",
    "audit_strategies",
    "prompt_versions",
    "videos",
    "audits",
    "playlists",
    "playlist_assignments",
    "playlist_proposals",
    "playlist_metrics",
    "video_embeddings",
    "video_keyframes",
    "video_metrics",
    "video_reach_daily",
    "video_traffic_source_playlist",
    "reporting_reports_ingested",
    "quota_log",
    "threshold_history",
    "shorts_jobs",
    "shorts_clips",
]

def column_types(conn) -> dict[tuple[str, str], str]:
    """{(table, column): data_type} for the public schema, from the database.

    Asked rather than hand-listed on purpose. A first draft of this script
    carried a literal set of jsonb columns and it was wrong in BOTH directions
    — four columns that do not exist, two real ones missed. The database
    already knows; a stale constant is just a way to be confidently wrong.
    """
    with conn.cursor() as cur:
        cur.execute("""
            select table_name, column_name, data_type
            from information_schema.columns
            where table_schema = 'public'
        """)
        return {(t, c): d for t, c, d in cur.fetchall()}


def _adapt(table: str, row: dict, types: dict) -> dict:
    """Convert one exported row into values psycopg can bind."""
    out = {}
    for col, val in row.items():
        dtype = types.get((table, col))
        if val is None:
            out[col] = None
        elif dtype in ("json", "jsonb"):
            # PostgREST parsed these into Python objects; psycopg needs them
            # re-serialised or it stores a Python repr.
            out[col] = Jsonb(val)
        elif isinstance(val, dict):
            # A dict in a non-json column would be a schema surprise — fail
            # loudly rather than silently storing str(dict).
            raise TypeError(
                f"{table}.{col} holds an object but its type is {dtype!r}; "
                "the export and the schema disagree"
            )
        else:
            # Arrays (text[]) bind natively from a list; the pgvector literal
            # '[0.1,...]' is already exactly what pgvector accepts, so strings
            # pass through untouched.
            out[col] = val
    return out


def _rows(table: str):
    path = EXPORT / f"{table}.ndjson"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_table(conn, table: str, types: dict) -> int:
    first = next(_rows(table), None)
    if first is None:
        print(f"  {table:<32} empty — nothing to load")
        return 0
    cols = list(first.keys())
    placeholders = ", ".join(f"%({c})s" for c in cols)
    collist = ", ".join(f'"{c}"' for c in cols)
    sql = f'insert into "{table}" ({collist}) values ({placeholders})'

    n = 0
    with conn.cursor() as cur:
        cur.execute(f'truncate table "{table}" cascade')
        batch = []
        for row in _rows(table):
            batch.append(_adapt(table, row, types))
            if len(batch) >= BATCH:
                cur.executemany(sql, batch)
                n += len(batch)
                batch.clear()
                print(f"    {table}: {n}", end="\r", flush=True)
        if batch:
            cur.executemany(sql, batch)
            n += len(batch)
    print(f"  {table:<32} {n:>9} rows loaded")
    return n


def fix_sequences(conn) -> None:
    """Advance every sequence past the ids we inserted explicitly.

    Without this the first app insert into any bigserial table fails on a
    duplicate key — the sequence is still sitting at 1.
    """
    with conn.cursor() as cur:
        cur.execute("""
            select c.relname as table_name,
                   a.attname as column_name,
                   pg_get_serial_sequence(quote_ident(c.relname), a.attname) as seq
            from pg_class c
            join pg_attribute a on a.attrelid = c.oid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public'
              and c.relkind = 'r'
              and a.attnum > 0
              and pg_get_serial_sequence(quote_ident(c.relname), a.attname) is not null
        """)
        for table, column, seq in cur.fetchall():
            cur.execute(
                f'select setval(%s, coalesce((select max("{column}") from "{table}"), 0) + 1, false)',
                (seq,),
            )
            print(f"  sequence {seq} advanced past max({table}.{column})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", help="comma-separated subset (order still enforced)")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL is not set")
    if not EXPORT.is_dir():
        sys.exit(f"{EXPORT} not found — run scripts/export_supabase.py first")

    wanted = set(t.strip() for t in args.tables.split(",")) if args.tables else None
    tables = [t for t in LOAD_ORDER if wanted is None or t in wanted]

    total = 0
    with psycopg.connect(dsn) as conn:
        # One transaction for the whole load: a failure halfway through leaves
        # the database as it was rather than half-migrated.
        types = column_types(conn)
        if not types:
            sys.exit("No public tables found — run scripts/apply_migrations.py first")
        for t in tables:
            total += load_table(conn, t, types)
        fix_sequences(conn)
        conn.commit()

    print(f"\n  {total} rows loaded. Verify row counts against migration_export/ before cutting over.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
