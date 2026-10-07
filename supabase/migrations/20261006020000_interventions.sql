-- Phase B · B2 (#32) — the interventions record, and channels.agent_enabled.
--
-- Spec Part 2 §7 / Part 3 B2. One row per change to a video, by Midas or by the
-- SEO team (B3), including the changes Midas deliberately didn't make: the
-- holdout arm (§1.3) and declined triages (§2.2). `audits` stays intact; a title
-- intervention references its audit.
--
-- Vocabularies live in app/status_vocab.py (InterventionLever, InterventionOrigin,
-- InterventionArm, InterventionStatus). Nothing writes this table in Phase B
-- except B3's human ledger; Midas interventions start in Slice 1.

create table if not exists interventions (
    id                  bigserial   primary key,
    video_id            text        not null references videos(id) on delete cascade,
    channel_id          text        not null references channels(id),
    lever               text        not null,   -- backlinks|playlist|short_link|title
    origin              text        not null,   -- midas|human
    arm                 text        not null,   -- treated|holdout|n/a
    status              text        not null,
    payload             jsonb,
    before_state        jsonb,
    -- Title lever only.
    audit_id            bigint      references audits(id),
    strategy_version    text        references audit_strategies(version),
    -- Rules choice, Jev choice and probabilities.
    triage_json         jsonb,
    applied_at          timestamptz,
    -- Human interventions: when sync saw the edit, not when it was made.
    detected_at         timestamptz,
    measurement_status  text,
    measurement_result  jsonb,
    created_at          timestamptz default now()
);

-- Spec Part 2 §1.6: at most one active Midas intervention per video, of any
-- lever. app/interventions.record checks this first; the index makes it hold
-- under concurrent writers too. The status list mirrors
-- status_vocab.ACTIVE_INTERVENTION_STATUSES (tests/test_status_vocab.py).
-- Human interventions are outside it: they never block a Midas change.
create unique index if not exists interventions_one_active_midas_per_video
    on interventions (video_id)
    where origin = 'midas' and status in ('planned', 'applied', 'measuring', 'holdout');

-- Backs the on-delete-cascade from videos, and per-video reads of any origin.
create index if not exists interventions_video_idx on interventions (video_id);

grant all on interventions to service_role;
grant all on sequence interventions_id_seq to service_role;

-- Slice 1's tick routing reads it (spec Part 2 §6.1). Nothing sets it true in Phase B.
alter table channels add column if not exists agent_enabled boolean not null default false;
