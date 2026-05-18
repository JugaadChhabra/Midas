-- Playlist management: embeddings, playlist sync, and assignment tracking.

create extension if not exists vector;

create table if not exists video_embeddings (
    id            bigserial primary key,
    video_id      text not null references videos(id) on delete cascade,
    chunk_index   text not null,  -- 'pooled' or '0','1','2',...
    embedding     vector(3072) not null,
    model_version text not null,
    created_at    timestamptz default now(),
    unique (video_id, chunk_index, model_version)
);
create index if not exists idx_video_embeddings_video on video_embeddings(video_id);

create table if not exists playlists (
    id          text primary key,  -- YouTube playlist id
    channel_id  text not null references channels(id) on delete cascade,
    title       text not null,
    description text default '',
    synced_at   timestamptz default now()
);
create index if not exists idx_playlists_channel on playlists(channel_id);

create table if not exists playlist_assignments (
    id               bigserial primary key,
    video_id         text not null references videos(id) on delete cascade,
    playlist_id      text not null references playlists(id) on delete cascade,
    playlist_item_id text,  -- YouTube playlistItem id, needed for deletion
    similarity_score float,
    action           text not null,  -- 'added' | 'removed'
    decision_source  text not null,  -- 'embedding' | 'llm_confirmed' | 'sync'
    model_version    text,
    decided_at       timestamptz default now()
);
create index if not exists idx_playlist_assignments_video   on playlist_assignments(video_id);
create index if not exists idx_playlist_assignments_playlist on playlist_assignments(playlist_id);
