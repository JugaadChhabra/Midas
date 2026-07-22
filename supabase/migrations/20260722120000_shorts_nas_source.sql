-- supabase/migrations/20260722120000_shorts_nas_source.sql
-- NAS-sourced shorts: jobs can originate from a NAS language folder instead
-- of a YouTube URL. Additive — the YouTube path is unchanged.
alter table shorts_jobs
    add column if not exists language        text,
    add column if not exists source_nas_path text;

-- NAS jobs have no channel; existing YouTube jobs still set it.
alter table shorts_jobs
    alter column channel_id drop not null;

alter table shorts_clips
    add column if not exists nas_path text;

-- Deploy-time autopilot mapping: which language folder a channel pulls from.
-- NULL for every channel today, so autopilot shorts stays inert until set.
alter table channels
    add column if not exists nas_folder text;
