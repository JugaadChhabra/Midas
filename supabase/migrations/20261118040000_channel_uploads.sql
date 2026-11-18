-- Team tracker 06 (#150, spec #142) — channel_uploads: every video uploaded to a
-- channel, with the time it was uploaded.
--
-- Written only by the video sync (app/sync.py `_record_uploads`), from the calls
-- `sync_channel` already makes: no new YouTube client, no extra quota. Unlike
-- `videos`, it holds private and scheduled uploads and Shorts on channels with
-- `sync_shorts = false`, so the levers and the autopilot (which read `videos`)
-- never see those. No FK to `videos` for that reason; a video deleted from
-- YouTube keeps its row, so its upload day keeps its credit.
--
-- uploaded_at = the uploads-playlist item's snippet.publishedAt (#143's
-- decision), else first_seen_at. Both raw timestamps are kept
-- (playlist_published_at, video_published_at) so uploaded_at can be recomputed
-- from stored data if #153's probe picks the other field.
--
-- Write-once: the app inserts new rows with ignore-duplicates and updates only
-- the mutable fields of existing ones, never uploaded_at. The trigger below is
-- the backstop for any other writer.

create table if not exists channel_uploads (
    video_id               text         primary key,
    channel_id             text         not null references channels(id) on delete cascade,
    title                  text,
    is_short               boolean,                 -- null = not yet classified
    duration_seconds       int,
    privacy_status         text,                    -- latest seen: private|unlisted|public
    scheduled_publish_at   timestamptz,             -- video status.publishAt; null once live
    thumbnail_url          text,
    uploaded_at            timestamptz  not null,   -- write-once (trigger below)
    playlist_published_at  timestamptz,             -- playlistItem snippet.publishedAt
    video_published_at     timestamptz,             -- video snippet.publishedAt, latest seen
    first_seen_at          timestamptz  not null default now(),
    last_seen_at           timestamptz  not null default now()
);

-- Backs "this channel's uploads in a date window" (the Team page's grid).
create index if not exists channel_uploads_channel_uploaded
    on channel_uploads (channel_id, uploaded_at);

-- uploaded_at and first_seen_at are write-once, whichever code path updates.
create or replace function channel_uploads_freeze_uploaded_at()
returns trigger
language plpgsql
as $$
begin
    new.uploaded_at   := old.uploaded_at;
    new.first_seen_at := old.first_seen_at;
    return new;
end;
$$;

drop trigger if exists channel_uploads_freeze on channel_uploads;
create trigger channel_uploads_freeze
    before update on channel_uploads
    for each row execute function channel_uploads_freeze_uploaded_at();

grant all on channel_uploads to service_role;
