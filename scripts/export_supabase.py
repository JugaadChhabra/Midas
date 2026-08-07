#!/usr/bin/env python3
"""Export every table from the hosted Supabase project to local NDJSON.

Used once, to move off the hosted project onto self-hosted Postgres. Reads
through PostgREST with the service key — a direct pg_dump would need the
database password (a separate secret) and a pg_dump matching the server's major
version.

    python scripts/export_supabase.py              # export everything
    python scripts/export_supabase.py --tables videos,audits
    python scripts/export_supabase.py --skip quota_log

**Keyset pagination, not OFFSET.** PostgREST caps responses at 1000 rows, and
paging with OFFSET over a table that is being written to silently skips and
duplicates rows at page boundaries. Every table here has a single-column primary
key, so each page asks for `pk > last_seen` — exact regardless of concurrent
writes, and it does not slow down as the offset grows.

**Resumable.** Each table writes one NDJSON file; a re-run reads the last line,
takes its key, and continues. A dropped connection costs one page, not the run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "migration_export"
PAGE = 1000

#: Primary keys, from the PostgREST OpenAPI doc. video_reach_daily's `id` is a
#: bigserial primary key that PostgREST does not annotate as one.
PKS = {
    "audit_configs": "channel_id",
    "audit_strategies": "version",
    "audits": "id",
    "channels": "id",
    "playlist_assignments": "id",
    "playlist_metrics": "id",
    "playlist_proposals": "id",
    "playlists": "id",
    "prompt_versions": "id",
    "quota_log": "id",
    "reporting_reports_ingested": "report_id",
    "shorts_clips": "id",
    "shorts_jobs": "id",
    "threshold_history": "id",
    "video_embeddings": "id",
    "video_keyframes": "id",
    "video_metrics": "id",
    "video_reach_daily": "id",
    "video_traffic_source_playlist": "id",
    "videos": "id",
}


def _headers() -> dict:
    key = settings.SUPABASE_SERVICE_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}",
            "Accept": "application/json"}


def _resume_key(path: Path):
    """Last primary-key value already written, or None."""
    if not path.exists() or path.stat().st_size == 0:
        return None, 0
    last, n = None, 0
    with path.open("rb") as f:
        for line in f:
            if line.strip():
                n += 1
                last = line
    return (json.loads(last), n) if last else (None, 0)


def export_table(client: httpx.Client, base: str, table: str) -> dict:
    pk = PKS[table]
    path = OUT / f"{table}.ndjson"
    OUT.mkdir(parents=True, exist_ok=True)

    last_row, written = _resume_key(path)
    cursor = last_row[pk] if last_row else None
    if cursor is not None:
        print(f"  {table}: resuming after {pk}={cursor} ({written} rows already)")

    t0 = time.time()
    with path.open("a", encoding="utf-8") as out:
        while True:
            params = {"select": "*", "order": f"{pk}.asc", "limit": str(PAGE)}
            if cursor is not None:
                # Keyset: exact under concurrent writes, and constant-time.
                params[pk] = f"gt.{cursor}"
            r = client.get(f"{base}/rest/v1/{table}", params=params, timeout=180)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                out.write("\n")
            written += len(rows)
            cursor = rows[-1][pk]
            out.flush()
            print(f"    {table}: {written} rows", end="\r", flush=True)
            if len(rows) < PAGE:
                break

    size = path.stat().st_size if path.exists() else 0
    print(f"  {table:<32} {written:>9} rows  {size/1_048_576:>8.1f} MB  "
          f"{time.time()-t0:>6.1f}s")
    return {"table": table, "rows": written, "bytes": size}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", help="comma-separated subset")
    ap.add_argument("--skip", default="", help="comma-separated tables to skip")
    args = ap.parse_args()

    base = settings.SUPABASE_URL.rstrip("/")
    if not base or not settings.SUPABASE_SERVICE_KEY:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY must be set")

    wanted = [t.strip() for t in args.tables.split(",")] if args.tables else list(PKS)
    skip = {t.strip() for t in args.skip.split(",") if t.strip()}
    wanted = [t for t in wanted if t not in skip]

    print(f"Exporting {len(wanted)} table(s) from {base} -> {OUT}\n")
    summary = []
    with httpx.Client(headers=_headers(), http2=False) as client:
        for t in wanted:
            summary.append(export_table(client, base, t))

    rows = sum(s["rows"] for s in summary)
    mb = sum(s["bytes"] for s in summary) / 1_048_576
    print(f"\n  {'TOTAL':<32} {rows:>9} rows  {mb:>8.1f} MB")
    (OUT / "_manifest.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
