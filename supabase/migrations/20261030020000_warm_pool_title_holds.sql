-- Slice 3 · S3.5 (#120, spec Part 6 S3.5, Part 2 §2.1): a video is in the title
-- experiment once. Replaces warm_pool() from 20261023000000 (same signature, so
-- `create or replace`, no overload) with one more once-per-experiment clause:
-- any Midas `title` holdout row, or treated row that isn't a `cancelled` row
-- that never reached YouTube (`applied_at` NULL), keeps its video out at any
-- age. So a title put back by the auto-revert (`cancelled`, `applied_at` set),
-- a judged title or holdout, and an agent decline (`declined`, later `judged`
-- or `insufficient_data`; F14, measured over its own 14-day post window) never
-- re-enter the pool. A treated title row cancelled before its write
-- (checks_failed, turn_cap, writer_exception, a refused apply) holds its video
-- only for the cooldown, as a backlinks row that never reached YouTube.
-- app/warm.py _holds is the in-app twin; tests/test_warm_pool_parity.py runs both.
-- STABLE + read-only; callable only by service_role (the app).
create or replace function warm_pool(
    p_channel_id               text,
    p_min_impressions          bigint,
    p_window_days              int,
    p_measurement_window_days  int,
    p_cooldown_days            int
)
returns table(id text, impressions bigint)
language sql
stable
as $$
  with covered as (
    select distinct r.data_date
    from reporting_reports_ingested r
    where r.channel_id = p_channel_id
      and r.report_type = 'channel_reach_basic_a1'
  ),
  certified as (
    select count(1) = p_measurement_window_days as ok
    from covered c
    where c.data_date > (select max(data_date) from covered) - p_measurement_window_days
  ),
  window_days as (
    select c.data_date
    from covered c
    order by c.data_date desc
    limit p_window_days
  ),
  reach as (
    select d.video_id, sum(d.impressions)::bigint as impressions
    from video_reach_daily d
    where d.channel_id = p_channel_id
      and d.date in (select data_date from window_days)
    group by d.video_id
  )
  select v.id, rc.impressions
  from reach rc
  join videos v on v.id = rc.video_id
  where (select ok from certified)
    and v.channel_id = p_channel_id
    and (v.privacy_status is null or v.privacy_status = 'public')
    and v.is_episode is not true
    and rc.impressions >= p_min_impressions
    and not exists (
      select 1 from interventions i
      where i.video_id = v.id
        and i.origin = 'midas'
        and (
          i.status in ('planned', 'applied', 'measuring', 'holdout')
          or i.created_at > now() - make_interval(days => p_cooldown_days)
          or (i.lever = 'backlinks'
              and (i.arm = 'holdout' or (i.arm = 'treated' and i.applied_at is not null)))
          or (i.lever = 'title'
              and (i.arm = 'holdout'
                   or (i.arm = 'treated'
                       and (i.applied_at is not null or i.status <> 'cancelled'))))
        )
    )
  order by rc.impressions desc, v.id;
$$;

revoke execute on function warm_pool(text, bigint, int, int, int) from public;
grant  execute on function warm_pool(text, bigint, int, int, int) to service_role;
