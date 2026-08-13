-- Add quarantined_count and applied_by_day to dashboard_summary().
--
-- The Running board groups channels by what needs a person. It could show a
-- channel that had stopped, or whose data was stale, but not one that ran fine
-- last night and produced unusable rewrites — nothing in the payload said so,
-- so a channel quietly filling up with bad output looked identical to a healthy
-- one. This adds the count the "Needs attention" group is keyed on.
--
-- Same counting rule as pending_count, deliberately: PUBLIC videos, LATEST
-- audit per video. A video whose latest audit is quarantined is currently
-- unusable; an older quarantined audit that has since been re-run is not a
-- problem and must not keep the channel flagged forever.
--
-- applied_by_day is seven integers, oldest first, ending today (UTC days). The
-- board draws a heartbeat strip per channel and had no history to draw from, so
-- it rendered six zeros and a real value for today — six days of "nothing
-- happened" that were never measured. Deliberately NOT part of the scalar
-- _STAT_KEYS set the parity test walks: it is an RPC-only field, and when it is
-- absent the board draws no strip rather than inventing one.
--
-- Everything else is byte-for-byte the previous definition
-- (20260720120000_dashboard_summary_rpc.sql) — see that file's header for the
-- correctness rules this must keep matching in app/dashboard.py.
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
           count(*) filter (where not v.is_short)           as audited_regular,
           count(*) filter (where v.is_short)               as audited_shorts,
           count(*) filter (where l.status = 'pending')     as pending_count,
           count(*) filter (where l.status = 'quarantined') as quarantined_count,
           count(*) filter (where l.status = 'applied')     as applied_latest
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
  days as (
    select generate_series(
      (date_trunc('day', now() at time zone 'utc'))::date - 6,
      (date_trunc('day', now() at time zone 'utc'))::date,
      interval '1 day')::date as d
  ),
  byday as (
    select v.channel_id,
           (a.applied_at at time zone 'utc')::date as d,
           count(*) as n
    from audits a
    join videos v on v.id = a.video_id
    where a.status = 'applied'
      and a.applied_at >= (date_trunc('day', now() at time zone 'utc') - interval '6 days')
    group by 1, 2
  ),
  beat as (
    -- cross join channels x days so a channel with no applies still gets seven
    -- slots; without it the strip would be shorter for quiet channels and the
    -- bars would stop lining up across rows.
    select c.id as channel_id,
           jsonb_agg(coalesce(b.n, 0) order by d.d) as applied_by_day
    from channels c
    cross join days d
    left join byday b on b.channel_id = c.id and b.d = d.d
    group by c.id
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
        'channel_id',        c.id,
        'video_count',       coalesce(vc.video_count, 0),
        'regular_count',     coalesce(vc.regular_count, 0),
        'shorts_count',      coalesce(vc.shorts_count, 0),
        'audited_regular',   coalesce(ac.audited_regular, 0),
        'audited_shorts',    coalesce(ac.audited_shorts, 0),
        'pending_count',     coalesce(ac.pending_count, 0),
        'quarantined_count', coalesce(ac.quarantined_count, 0),
        'applied_latest',    coalesce(ac.applied_latest, 0),
        'applied_today',     coalesce(ap.applied_today, 0),
        'applied_7d',        coalesce(ap.applied_7d, 0),
        'applied_total',     coalesce(ap.applied_total, 0),
        'delta_views_7d',    coalesce(ap.delta_views_7d, 0),
        'applied_by_day',    coalesce(bt.applied_by_day, '[]'::jsonb)
      ))
      from channels c
      left join vcount  vc on vc.channel_id = c.id
      left join acount  ac on ac.channel_id = c.id
      left join apcount ap on ap.channel_id = c.id
      left join beat    bt on bt.channel_id = c.id
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
