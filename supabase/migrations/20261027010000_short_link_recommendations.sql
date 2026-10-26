-- Slice 2 · S2.4 (#90) — short_link_recommendations, the long videos each
-- Short should link to.
--
-- Spec Part 5 S2.4 (Part 2 §2.3, P4, E9, E10). Recommend-only, permanently: the
-- YouTube API can't read or write a Short's related-video link (A2), so the
-- team sets it in Studio and Midas writes nothing to YouTube. Written by the
-- weekly `short_link_refresh` job (app/short_links.py refresh): per Short with
-- Shorts-feed views and no rows yet, its targets as `pending` rows, rank 1…
-- SHORT_LINK_TARGETS, each with the next-watch question asked in shadow and its
-- decision_log row's id on `decision_log_id` (decision_log.intervention_id stays
-- NULL: no intervention exists for a recommendation). A Short that has rows is
-- never re-recommended, so a person's tick or dismissal stands.
--
-- `similarity` is the raw cosine on B6 vectors (reembed.MODEL_VERSION);
-- `impressions` the target's warm impressions and `feed_views` the Short's
-- type-24 views, both as of the refresh. `decided_at`, `seen_at` and
-- `intervention_id` are written by S2.5 (the team's tick) and S2.6 (the link
-- seen in the traffic). The vocabulary lives in app/status_vocab.py
-- (ShortLinkStatus).

create table if not exists short_link_recommendations (
    id                bigserial         primary key,
    channel_id        text              references channels(id),
    short_id          text              not null references videos(id) on delete cascade,
    target_video_id   text              not null references videos(id) on delete cascade,
    rank              smallint          not null,
    similarity        double precision  not null,
    impressions       bigint,
    feed_views        bigint,
    decision_log_id   bigint            references decision_log(id) on delete set null,
    status            text              not null default 'pending',   -- pending|set|not_chosen|dismissed
    decided_at        timestamptz,
    seen_at           timestamptz,
    intervention_id   bigint            references interventions(id) on delete set null,
    created_at        timestamptz       default now(),
    unique (short_id, target_video_id)
);
