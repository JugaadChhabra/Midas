-- Apply-time snapshot columns on audits
alter table audits add column if not exists title_before           text;
alter table audits add column if not exists description_before     text;
alter table audits add column if not exists tags_before            text[];
alter table audits add column if not exists view_count_at_apply    bigint;
alter table audits add column if not exists like_count_at_apply    bigint;
alter table audits add column if not exists comment_count_at_apply bigint;

-- Autopilot per-channel state
alter table channels add column if not exists autopilot_enabled       boolean default false;
alter table channels add column if not exists autopilot_paused_reason text;
alter table channels add column if not exists autopilot_last_tick_at  timestamptz;
alter table channels add column if not exists autopilot_daily_cap     int default 10;

-- Quota log
create table if not exists quota_log (
    id           bigserial primary key,
    occurred_at  timestamptz default now(),
    channel_id   text,
    operation    text,
    units        int not null,
    success      boolean default true
);
create index if not exists quota_log_day_idx on quota_log ((occurred_at::date));
