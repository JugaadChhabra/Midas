-- Track YouTube privacy state so we can skip unlisted/private at audit time
-- without re-fetching from the API.
alter table videos add column if not exists privacy_status text;

-- Backlog markers for the two optimization flows we haven't built yet.
-- When those flows ship, we'll batch-update videos where these are NULL but
-- a corresponding applied audit already exists.
alter table videos add column if not exists thumbnail_optimized_at timestamptz;
alter table videos add column if not exists playlists_optimized_at  timestamptz;

create index if not exists videos_privacy_idx on videos(privacy_status);
