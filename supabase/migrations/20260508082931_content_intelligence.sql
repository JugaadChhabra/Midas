-- Content-aware audit: transcript flags, keyframe storage, and per-keyframe rows.
-- Block A of the content-intelligence upgrade. Thumbnail-generation tables come later.

alter table audits
    add column if not exists transcript_available boolean default false,
    add column if not exists transcript_lang text,
    add column if not exists keyframes_extracted int default 0;

create table if not exists video_keyframes (
    id bigserial primary key,
    video_id text not null references videos(id) on delete cascade,
    timestamp_seconds float not null,
    storage_path text not null,
    created_at timestamptz default now()
);
create index if not exists idx_video_keyframes_video on video_keyframes(video_id);

-- Private bucket for raw extracted keyframes. Vision models read via signed URLs.
insert into storage.buckets (id, name, public)
values ('keyframes', 'keyframes', false)
on conflict (id) do nothing;
