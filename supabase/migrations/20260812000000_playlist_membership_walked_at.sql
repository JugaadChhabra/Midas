-- Quota budgets for bulk collection — the resume cursor for the playlist walk.
--
-- sync_playlists now spends against a bounded per-run budget (see
-- PLAYLIST_SYNC_QUOTA_BUDGET) instead of walking every playlist's full
-- membership in one pass, which on 2026-08-03/04 consumed 8.5k-9.2k of the
-- 10k/day Data API quota by itself and starved videos.update (applying audits).
--
-- Two things need this column:
--
--   1. The resume cursor. When the budget runs out mid-pass the remaining
--      playlists are simply left unwalked; ordering the next run by
--      membership_walked_at ASC NULLS FIRST makes it pick up where it stopped
--      instead of re-walking the same head of the list every night.
--
--   2. The rotation walk. The incremental skip (item_count unchanged => don't
--      walk) is blind to an equal-count swap: one video added and one removed
--      leaves itemCount identical, so the membership drift is never observed.
--      A playlist not walked in PLAYLIST_FULL_WALK_DAYS is force-walked
--      regardless of count, which bounds that drift to the rotation period.
--
-- NULL means "never walked by a budget-aware sync" and sorts first, so the
-- backlog drains oldest-first on the nights after this ships.
alter table playlists add column if not exists membership_walked_at timestamptz;

-- The walk planner reads (channel_id, membership_walked_at) to order candidates.
create index if not exists playlists_channel_walked_idx
    on playlists (channel_id, membership_walked_at asc nulls first);
