-- Shorts automation prototype (docs/superpowers/plans/2026-06-17-shorts-prototype.md).
-- Job rows track a single "clip this YouTube video" request submitted to the
-- WayinVideo API. Clip rows track individual generated shorts and their
-- per-upload state on YouTube.

create table if not exists shorts_jobs (
    id                      bigserial primary key,
    channel_id              text        not null references channels(id),
    source_video_id         text,
    source_url              text        not null,
    wayinvideo_project_id   text,
    -- WayinVideo lifecycle: CREATED → QUEUED → ONGOING → SUCCEEDED / FAILED.
    -- We add UPLOADING and DONE for the post-WayinVideo phase.
    status                  text        not null default 'CREATED',
    error_message           text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);
create index if not exists shorts_jobs_channel_idx on shorts_jobs(channel_id);
create index if not exists shorts_jobs_status_idx  on shorts_jobs(status);

create table if not exists shorts_clips (
    id              bigserial primary key,
    job_id          bigint      not null references shorts_jobs(id) on delete cascade,
    rank            int         not null,
    title           text,
    description     text,
    hashtags        text[],
    start_s         float,
    end_s           float,
    -- WayinVideo-hosted mp4 URL returned when export is enabled.
    source_url      text,
    yt_video_id     text,
    -- PENDING → UPLOADING → UPLOADED / FAILED.
    upload_status   text        not null default 'PENDING',
    upload_error    text,
    -- Set only when streaming upload failed and we cached the file on disk.
    local_path      text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (job_id, rank)
);
create index if not exists shorts_clips_job_idx on shorts_clips(job_id);
