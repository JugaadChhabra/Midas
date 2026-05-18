-- Human-in-the-loop queue for playlist allocation decisions.
-- Drop this table and set PLAYLIST_HITL=false to switch to full autopilot.

create table if not exists playlist_proposals (
    id              bigserial primary key,
    video_id        text not null references videos(id) on delete cascade,
    playlist_id     text not null references playlists(id) on delete cascade,
    video_title     text,
    playlist_title  text,
    action          text not null,   -- 'add' | 'remove'
    similarity      float,
    decision_source text not null,   -- 'embedding' | 'llm_confirmed'
    status          text not null default 'pending',  -- 'pending' | 'approved' | 'rejected'
    proposed_at     timestamptz default now(),
    decided_at      timestamptz
);

create index if not exists idx_playlist_proposals_channel
    on playlist_proposals(playlist_id);
create index if not exists idx_playlist_proposals_status
    on playlist_proposals(status);
