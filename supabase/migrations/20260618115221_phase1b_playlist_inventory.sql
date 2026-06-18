-- Phase 1B (playlist inventory + health, recommend-only).
-- See docs/PHASE_1B_PLAN.md §3 for full justification per column.
--
-- All three additions land in one migration because they share the same
-- target tables and life-cycle (`channels`, `playlists`). Each column is
-- idempotent (IF NOT EXISTS) and nullable so existing rows are safe.
--
-- Column population schedule across 1B steps:
--   Step 1 (this PR): role / origin / item_count / last_synced_at — sync.
--   Step 1 also reserves: created_by_optimizer_at / strategy_version (NULL
--     for inherited playlists; written by Phase 2B's optimizer-created path).
--   Step 2: health_score / health_recommendation / health_computed_at /
--     health_rationale_json — written by app/playlist_health.py.
--   Step 4: channels.playlist_health_enabled — per-channel rollout flag.
--
-- Gap 5 (docs/PHASE_0_GAPS.md): `playlist_metrics.playlist_id` is left
-- deliberately FK-free in this migration (see PHASE_1B_PLAN.md §3.3).
-- Reason: metrics rows can arrive before sync inserts the playlist row
-- (Analytics polling and sync are independent), and the PO spec
-- intentionally omits the FK. Revisit once Phase 2B settles the inventory
-- write paths.

-- ── playlists table: spec-driven additions (PO §Control loop, requirement 1) ─
alter table playlists add column if not exists role                    text;
alter table playlists add column if not exists origin                  text default 'inherited';
alter table playlists add column if not exists item_count              int;
alter table playlists add column if not exists last_synced_at          timestamptz default now();
alter table playlists add column if not exists created_by_optimizer_at timestamptz;
alter table playlists add column if not exists strategy_version        text;

-- ── playlists table: health-score storage (PHASE_1B_PLAN §3.2, denormalized) ─
-- Latest-only by design; history of inputs lives in playlist_metrics already.
alter table playlists add column if not exists health_score            float;
alter table playlists add column if not exists health_recommendation   text;
  -- revive | remove | keep | insufficient_data
alter table playlists add column if not exists health_computed_at      timestamptz;
alter table playlists add column if not exists health_rationale_json   jsonb;

-- ── channels: per-channel rollout flag (PHASE_1B_PLAN §8) ────────────────────
-- Default false: 1B is off everywhere until explicitly enabled per channel,
-- matching the autopilot_enabled / sync_shorts pattern.
alter table channels add column if not exists playlist_health_enabled  boolean default false;

-- Backfill: existing inherited playlists get origin='inherited' explicitly
-- (no-op for new rows since they default to the same value).
update playlists set origin = 'inherited' where origin is null;

-- Origin is provenance, not application state — every row must declare which
-- side created it (sync vs. Phase 2B optimizer). Enforced after the backfill
-- so the column is fully populated before the constraint applies.
alter table playlists alter column origin set not null;
