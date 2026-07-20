-- Server-side aggregation for the /dashboard endpoint.
--
-- /dashboard previously egressed the entire videos + audits + shorts_clips
-- tables into the app server on every cache miss (~2 MB) and counted in Python.
-- This function computes the same per-channel aggregates + shorts totals inside
-- Postgres and returns a few KB of JSON instead — the ~100x egress cut that
-- app/dashboard.py consumes behind the DASHBOARD_USE_RPC flag.
--
-- Correctness must match the Python path exactly (see app/dashboard.py):
--   * "public" = privacy_status IS NULL OR = 'public' (legacy null = public)
--   * video/audited/pending counts  -> PUBLIC videos only
--   * applied_today/7d/total + delta -> ALL videos (orphan-video audits excluded
--     by the inner join, matching Python's `if not ch: continue`)
--   * audited/pending use the LATEST audit per video; applied_* count RAW applied
--     rows; applied_latest = public videos whose LATEST audit is 'applied'
--   * time anchors in UTC: today = UTC-midnight-today, 7d = rolling now()-7d
--
-- STABLE + read-only; callable only by service_role (the app), not anon.
create or replace function dashboard_summary()
returns jsonb
language sql
stable
as $$
  with pub as (
    select id, channel_id, is_short, coalesce(view_count, 0) as view_count
    from videos
    where privacy_status is null or privacy_status = 'public'
  ),
  latest as (
    select distinct on (video_id) video_id, status
    from audits
    order by video_id, created_at desc
  ),
  vcount as (
    select channel_id,
           count(*)                              as video_count,
           count(*) filter (where not is_short)  as regular_count,
           count(*) filter (where is_short)      as shorts_count
    from pub
    group by channel_id
  ),
  acount as (
    select v.channel_id,
           count(*) filter (where not v.is_short)       as audited_regular,
           count(*) filter (where v.is_short)           as audited_shorts,
           count(*) filter (where l.status = 'pending') as pending_count,
           count(*) filter (where l.status = 'applied') as applied_latest
    from latest l
    join pub v on v.id = l.video_id
    group by v.channel_id
  ),
  applied as (
    select v.channel_id, a.applied_at, a.view_count_at_apply,
           coalesce(v.view_count, 0) as cur_views
    from audits a
    join videos v on v.id = a.video_id
    where a.status = 'applied'
  ),
  apcount as (
    select channel_id,
      count(*) filter (
        where applied_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'
      ) as applied_today,
      count(*) filter (where applied_at >= now() - interval '7 days') as applied_7d,
      count(*) as applied_total,
      coalesce(sum(cur_views - coalesce(view_count_at_apply, 0))
               filter (where applied_at >= now() - interval '7 days'), 0) as delta_views_7d
    from applied
    group by channel_id
  )
  select jsonb_build_object(
    'channels', coalesce((
      select jsonb_agg(jsonb_build_object(
        'channel_id',      c.id,
        'video_count',     coalesce(vc.video_count, 0),
        'regular_count',   coalesce(vc.regular_count, 0),
        'shorts_count',    coalesce(vc.shorts_count, 0),
        'audited_regular', coalesce(ac.audited_regular, 0),
        'audited_shorts',  coalesce(ac.audited_shorts, 0),
        'pending_count',   coalesce(ac.pending_count, 0),
        'applied_latest',  coalesce(ac.applied_latest, 0),
        'applied_today',   coalesce(ap.applied_today, 0),
        'applied_7d',      coalesce(ap.applied_7d, 0),
        'applied_total',   coalesce(ap.applied_total, 0),
        'delta_views_7d',  coalesce(ap.delta_views_7d, 0)
      ))
      from channels c
      left join vcount  vc on vc.channel_id = c.id
      left join acount  ac on ac.channel_id = c.id
      left join apcount ap on ap.channel_id = c.id
    ), '[]'::jsonb),
    'shorts', (
      select jsonb_build_object(
        'cut_total',      count(*),
        'uploaded_total', count(*) filter (where upload_status = 'UPLOADED')
      )
      from shorts_clips
    )
  );
$$;

revoke execute on function dashboard_summary() from public;
grant execute on function dashboard_summary() to service_role;
