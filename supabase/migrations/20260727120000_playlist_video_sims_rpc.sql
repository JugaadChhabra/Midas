-- Server-side playlist assignment scoring (pgvector) — Tier 3′ RPC 1.
--
-- join_pass (per-video) and reconcile_channel (DAILY) previously pulled the
-- pooled `embedding` column — a vector(3072), ~39 KB/row — into the app to
-- compute a playlist centroid (mean of member embeddings) and cosine-score
-- every candidate video against it. On the daily reconcile that egressed every
-- embedded video's raw vector per channel; the biggest recurring Supabase
-- egress source. This function does the identical math in Postgres and returns
-- only floats.
--
-- Correctness must match app/playlists.py exactly:
--   * membership = latest playlist_assignments action per (playlist,video),
--     kept only when it is 'added' (mirrors _current_members).
--   * centroid   = avg() of pooled member embeddings for the given model_version
--     (members without an embedding are dropped, exactly like _centroid).
--   * sim        = 1 - (candidate <=> centroid); pgvector <=> is cosine DISTANCE,
--     so this is cosine similarity. A zero-vector yields NaN from <=>; we map
--     that to 0.0 to match _cosine_sim's mag==0 guard.
--   * candidates = channel videos that have a pooled embedding (unembedded
--     videos simply produce no row, matching Python's `if emb is None: continue`).
--
-- p_video_id: NULL scores all channel videos (reconcile); a value scores one
-- video (join_pass) and returns one row per playlist-with-centroid.
--
-- STABLE + read-only; callable only by service_role (the app), not anon.
create or replace function playlist_video_sims(
    p_channel_id    text,
    p_model_version text,
    p_video_id      text default null
)
returns table(playlist_id text, video_id text, sim double precision)
language sql
stable
as $$
  with member_latest as (
    select distinct on (pa.playlist_id, pa.video_id)
           pa.playlist_id, pa.video_id, pa.action
    from playlist_assignments pa
    join playlists pl
      on pl.id = pa.playlist_id
     and pl.channel_id = p_channel_id
    order by pa.playlist_id, pa.video_id, pa.decided_at desc
  ),
  centroids as (
    select m.playlist_id, avg(e.embedding) as centroid
    from member_latest m
    join video_embeddings e
      on e.video_id = m.video_id
     and e.chunk_index = 'pooled'
     and e.model_version = p_model_version
    where m.action = 'added'
    group by m.playlist_id
  ),
  cand as (
    select e.video_id, e.embedding
    from video_embeddings e
    join videos v
      on v.id = e.video_id
     and v.channel_id = p_channel_id
    where e.chunk_index = 'pooled'
      and e.model_version = p_model_version
      and (p_video_id is null or e.video_id = p_video_id)
  )
  select c.playlist_id,
         cand.video_id,
         case
           -- x <> x is true only for NaN (zero-vector distance); match _cosine_sim -> 0.0
           when (cand.embedding <=> c.centroid) <> (cand.embedding <=> c.centroid) then 0.0
           else 1 - (cand.embedding <=> c.centroid)
         end::double precision as sim
  from centroids c
  cross join cand;
$$;

revoke execute on function playlist_video_sims(text, text, text) from public;
grant execute on function playlist_video_sims(text, text, text) to service_role;
