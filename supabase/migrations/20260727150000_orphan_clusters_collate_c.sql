-- Fix: discover_orphan_clusters() drifted from the in-app greedy clustering.
-- The greedy algorithm is order-sensitive, and the two paths iterated orphans in
-- DIFFERENT orders: Python uses sorted() (Unicode codepoint order), but the RPC's
-- `order by video_id` used the database's default collation (locale-aware — sorts
-- case-insensitively and reorders '-'/'_'). For YouTube IDs those orders differ
-- wildly (e.g. uppercase-before-lowercase vs case-folded), so loose/ambiguous
-- videos cascaded into different clusters. `collate "C"` forces byte order, which
-- equals Python's codepoint sort for ASCII IDs. Only the ORDER BY changes.
create or replace function discover_orphan_clusters(
    p_channel_id      text,
    p_model_version   text,
    p_orphan_ids      text[],
    p_sim_threshold   double precision,
    p_min_cluster_size int
)
returns table(video_id text, cluster_id int)
language plpgsql
volatile
as $$
#variable_conflict use_column
declare
    v_ids       text[];
    v_id        text;
    n_clusters  int := 0;
    best_cluster int;
    best_score  double precision;
    cscore      double precision;
    c           int;
begin
    -- collate "C" => byte order, matching Python's sorted() on ASCII video IDs.
    select array_agg(e.video_id order by e.video_id collate "C")
      into v_ids
    from video_embeddings e
    join videos vv
      on vv.id = e.video_id
     and vv.channel_id = p_channel_id
    where e.chunk_index = 'pooled'
      and e.model_version = p_model_version
      and e.video_id = any(p_orphan_ids);

    if v_ids is null then
        return;
    end if;

    create temp table _orphan_asg(video_id text primary key, cluster_id int) on commit drop;

    foreach v_id in array v_ids loop
        best_cluster := null;
        best_score   := 0;

        for c in 1..n_clusters loop
            select avg(
                     case
                       when (cand.embedding <=> mem.embedding) <> (cand.embedding <=> mem.embedding)
                            then 0.0
                       else 1 - (cand.embedding <=> mem.embedding)
                     end
                   )
              into cscore
            from _orphan_asg a
            join video_embeddings mem
              on mem.video_id = a.video_id
             and mem.chunk_index = 'pooled'
             and mem.model_version = p_model_version
            cross join video_embeddings cand
            where a.cluster_id = c
              and cand.video_id = v_id
              and cand.chunk_index = 'pooled'
              and cand.model_version = p_model_version;

            if cscore is not null and cscore > best_score then
                best_score   := cscore;
                best_cluster := c;
            end if;
        end loop;

        if best_cluster is not null and best_score >= p_sim_threshold then
            insert into _orphan_asg values (v_id, best_cluster);
        else
            n_clusters := n_clusters + 1;
            insert into _orphan_asg values (v_id, n_clusters);
        end if;
    end loop;

    return query
        select a.video_id, a.cluster_id
        from _orphan_asg a
        where a.cluster_id in (
            select oa.cluster_id
            from _orphan_asg oa
            group by oa.cluster_id
            having count(*) >= p_min_cluster_size
        )
        order by a.cluster_id, a.video_id;
end;
$$;

revoke execute on function discover_orphan_clusters(text, text, text[], double precision, int) from public;
grant  execute on function discover_orphan_clusters(text, text, text[], double precision, int) to service_role;
