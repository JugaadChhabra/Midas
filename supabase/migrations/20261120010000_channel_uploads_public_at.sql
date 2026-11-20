-- When a sync saw an unlisted upload turn public (owner, 2026-11-20). YouTube's
-- snippet.publishedAt stays at the time a video went up unlisted, and YouTube
-- keeps no record of the switch to public, so the team's "went live" day is only
-- knowable by watching for it: app/sync.py stamps this the first time a sync or
-- the upload re-check finds a row that was stored unlisted now public. NULL for
-- everything else, including videos already public before this column existed.
-- The uploads grid places a video on this day when it is set
-- (app/team_uploads.py live_at).
alter table channel_uploads add column if not exists public_at timestamptz;
