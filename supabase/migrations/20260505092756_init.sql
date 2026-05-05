-- Midas initial schema

create table if not exists channels (
    id              text primary key,
    name            text,
    handle          text,
    refresh_token   text not null,
    access_token    text,
    token_expiry    timestamptz,
    last_synced_at  timestamptz,
    created_at      timestamptz default now()
);

create table if not exists videos (
    id               text primary key,
    channel_id       text references channels(id) on delete cascade,
    title            text,
    description      text,
    tags             text[],
    thumbnail_url    text,
    category_id      text,
    view_count       bigint,
    like_count       bigint,
    comment_count    bigint,
    published_at     timestamptz,
    last_fetched_at  timestamptz default now()
);

create table if not exists audit_configs (
    channel_id        text primary key references channels(id) on delete cascade,
    raw_insights      text,
    generated_prompt  text,
    updated_at        timestamptz default now()
);

create table if not exists audits (
    id                     bigserial primary key,
    video_id               text references videos(id) on delete cascade,
    status                 text default 'pending',
    suggested_title        text,
    suggested_description  text,
    suggested_tags         text[],
    thumbnail_feedback     text,
    issues_found           jsonb,
    ai_reasoning           text,
    applied_at             timestamptz,
    created_at             timestamptz default now()
);

create index if not exists videos_channel_idx on videos(channel_id);
create index if not exists audits_video_idx on audits(video_id);
create index if not exists audits_status_idx on audits(status);
