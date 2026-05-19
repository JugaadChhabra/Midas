create table if not exists prompt_versions (
    id                   bigserial primary key,
    channel_id           text not null references channels(id) on delete cascade,
    prompt_text          text not null,
    status               text not null default 'shadow',
    created_at           timestamptz default now(),
    promoted_at          timestamptz,
    retired_at           timestamptz,
    reflection_reasoning text,
    performance_snapshot jsonb,
    parent_version_id    bigint references prompt_versions(id)
);
create index if not exists idx_prompt_versions_channel on prompt_versions(channel_id);
create index if not exists idx_prompt_versions_status  on prompt_versions(channel_id, status);

create table if not exists threshold_history (
    id               bigserial primary key,
    channel_id       text not null references channels(id) on delete cascade,
    join_high        float not null,
    join_low         float not null,
    leave_threshold  float not null,
    created_at       timestamptz default now(),
    status           text not null default 'active',
    reason           text
);
create index if not exists idx_threshold_history_channel on threshold_history(channel_id, status);
