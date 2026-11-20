"""The channel_uploads migration keeps uploaded_at write-once (team tracker 06, #150).

The app never sends uploaded_at in an update (tests/test_sync_uploads.py); the
`before update` trigger is the backstop for any other writer. Nothing offline
runs this SQL, so this guard reads the migration and asserts the properties the
Team page relies on, in the style of tests/test_assign_channel_sql.py.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


def _code() -> str:
    defining = sorted(p for p in MIGRATIONS.glob("*.sql")
                      if re.search(r"create table if not exists channel_uploads\b", p.read_text()))
    assert defining, "no migration creates channel_uploads"
    sql = defining[-1].read_text()
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).lower()


def test_the_table_has_the_columns_the_sync_writes():
    code = _code()
    for column in ("video_id text primary key",
                   "channel_id text not null references channels(id) on delete cascade",
                   "is_short boolean", "duration_seconds int", "privacy_status text",
                   "scheduled_publish_at timestamptz", "thumbnail_url text",
                   "uploaded_at timestamptz not null",
                   "playlist_published_at timestamptz", "video_published_at timestamptz",
                   "first_seen_at timestamptz not null default now()",
                   "last_seen_at timestamptz not null default now()"):
        assert column in code, column


def test_the_grid_read_is_indexed():
    assert "on channel_uploads (channel_id, uploaded_at)" in _code()


def test_a_before_update_trigger_freezes_uploaded_at_and_first_seen_at():
    code = _code()
    assert "new.uploaded_at := old.uploaded_at" in code
    assert "new.first_seen_at := old.first_seen_at" in code
    assert re.search(r"create trigger \w+ before update on channel_uploads for each row", code)


def test_service_role_can_write_it():
    assert "grant all on channel_uploads to service_role" in _code()


def test_public_at_is_added():
    sql = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    assert re.search(r"alter table channel_uploads add column if not exists public_at timestamptz",
                     sql, re.I)
