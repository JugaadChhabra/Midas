-- Local shorts cutter (docs/superpowers/specs/2026-07-09-local-shorts-cutter-design.md).
-- Replaces WayinVideo: jobs now run in-process, so the row carries live progress.
-- New status vocabulary: CREATED → DOWNLOADING → ANALYSING → RENDERING →
-- UPLOADING → DONE / FAILED. Historical Wayin statuses (QUEUED, ONGOING,
-- SUCCEEDED) remain on old rows and are treated as terminal by the app.
-- wayinvideo_project_id stays as a dead column; shorts_clips.source_url is
-- null for new rows (clips are local files, local_path is always set).

alter table shorts_jobs add column if not exists progress int not null default 0;
alter table shorts_jobs add column if not exists progress_label text;
alter table shorts_jobs add column if not exists cut_mode text;
alter table shorts_jobs add column if not exists camera_motion text;
