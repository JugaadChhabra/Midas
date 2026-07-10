-- Autopilot shorts (docs/superpowers/specs/2026-07-09-shorts-entrypoints-design.md, Phase B2).
-- Independent of the metadata-audit autopilot toggle. Daily cap = source videos
-- cut per day; upload cap = clips auto-uploaded per cut (rest held as PENDING).
alter table channels add column if not exists autopilot_shorts_enabled    boolean not null default false;
alter table channels add column if not exists autopilot_shorts_daily_cap   int not null default 1;
alter table channels add column if not exists autopilot_shorts_upload_cap  int not null default 2;
alter table channels add column if not exists shorts_cut_mode              text not null default 'highlights';
alter table channels add column if not exists shorts_camera_motion         text not null default 'calm';
