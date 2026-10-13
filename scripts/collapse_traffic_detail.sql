-- One-off: apply the B1 retention rule (owner, 2026-10-13; docs/PHASE_B_FINDINGS.md) to
-- video_traffic_source_daily rows ingested before app/traffic_poll.py learned it.
--
-- Same rule as traffic_poll.keeps_detail: keep source_detail for
--   * type 7 (suggested) when the referring video is in `videos` (any channel);
--   * type 14 (playlists) for `PL…` playlists and for Mixes seeded from one of our videos (`RD<videoId>`);
--   * every other type;
-- and fold the rest into the (video, date, type) row with source_detail = '', summing the metrics, so
-- per-type totals don't change. Idempotent: a second run finds nothing to fold.
--
-- One data-day per transaction, so an interruption leaves whole days done and a rerun finishes the rest.
-- Ends with VACUUM FULL, which locks the table: run it away from traffic_poll (12:00 IST).
--
-- Office machine (scripts/ ships in the image, which has psql 16):
--   docker compose exec -T midas sh -c 'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/collapse_traffic_detail.sql'

\echo 'before: rows and views per source type'
select source_type, count(1) nrows, sum(views) views from video_traffic_source_daily group by 1 order by 1;
select pg_size_pretty(pg_total_relation_size('video_traffic_source_daily')) size_before;

do $$
declare
    d date;
    folded bigint;
begin
    for d in select distinct date from video_traffic_source_daily order by 1 loop
        with gone as (
            delete from video_traffic_source_daily t
            where t.date = d
              and t.source_detail <> ''
              and (
                   (t.source_type = 7
                    and not exists (select 1 from videos v where v.id = t.source_detail))
                or (t.source_type = 14
                    and t.source_detail not like 'PL%'
                    and not (t.source_detail like 'RD%'
                             and exists (select 1 from videos v where v.id = substr(t.source_detail, 3))))
              )
            returning t.video_id, t.channel_id, t.date, t.source_type,
                      t.views, t.engaged_views, t.watch_time_minutes, t.report_id
        ), sums as (
            select video_id, channel_id, date, source_type,
                   sum(views)::bigint views, sum(engaged_views)::bigint engaged_views,
                   sum(watch_time_minutes) watch_time_minutes, max(report_id) report_id
            from gone
            group by 1, 2, 3, 4
        )
        insert into video_traffic_source_daily
            (video_id, channel_id, date, source_type, source_detail,
             views, engaged_views, watch_time_minutes, report_id)
        select video_id, channel_id, date, source_type, '',
               views, engaged_views, watch_time_minutes, report_id
        from sums
        on conflict (video_id, date, source_type, source_detail) do update
            set views              = video_traffic_source_daily.views + excluded.views,
                engaged_views      = video_traffic_source_daily.engaged_views + excluded.engaged_views,
                watch_time_minutes = video_traffic_source_daily.watch_time_minutes + excluded.watch_time_minutes;
        get diagnostics folded = row_count;
        raise notice 'collapse %: % blank-detail rows written', d, folded;
        commit;
    end loop;
end $$;

\echo 'after: rows and views per source type (views must equal the before figures)'
select source_type, count(1) nrows, sum(views) views from video_traffic_source_daily group by 1 order by 1;

vacuum full video_traffic_source_daily;
analyze video_traffic_source_daily;
select pg_size_pretty(pg_total_relation_size('video_traffic_source_daily')) size_after;
