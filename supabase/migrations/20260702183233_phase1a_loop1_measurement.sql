-- Phase 1A — CIL Loop 1 minimal slice (per-video measurement state machine).
--
-- CIL §1.1: measurement sub-lifecycle as SEPARATE columns so the existing
-- audits.status (pending|applied|failed|quarantined|...) and autopilot logic
-- stay untouched.
--
-- CIL §3.1 (pulled forward deliberately): every audit is stamped with the
-- strategy_version that produced it, starting NOW — outcomes accrued before
-- Loop 3 exists must still be attributable to a strategy, or the eventual
-- champion/challenger comparison has no history to stand on. The table is
-- created here; the full Loop 3 machinery (eval harness, promotion) is not.

create table if not exists audit_strategies (
    version          text primary key,          -- e.g. "2026.07-baseline-v1"
    -- The prompt machinery for the baseline strategy lives in code
    -- (audits.DEFAULT_PROMPT / per-channel audit_configs.generated_prompt),
    -- not in a frozen template — recorded as a code pointer, not a copy.
    -- Loop 3 challengers will store real frozen templates here.
    prompt_template  text not null,
    model            text not null,
    config           jsonb,
    status           text default 'challenger', -- champion | challenger | retired
    notes            text,
    created_at       timestamptz default now()
);

-- Seed the incumbent as champion. Model matches settings.AUDIT_MODEL default.
insert into audit_strategies (version, prompt_template, model, status, notes)
values (
    '2026.07-baseline-v1',
    'code:app/audits.py DEFAULT_PROMPT + audit_configs.generated_prompt (per-channel)',
    'anthropic/claude-haiku-4.5',
    'champion',
    'Incumbent strategy at Loop 1 launch; prompt lives in code/audit_configs, not frozen here.'
)
on conflict (version) do nothing;

alter table audits
    add column if not exists measurement_status text default 'not_applicable',
    -- not_applicable | awaiting_window | measuring | win | neutral | regression
    add column if not exists measurement_started_at timestamptz,
    add column if not exists measurement_result jsonb,
    add column if not exists outcome_decision text default 'none',
    -- none | kept | reverted | redo_queued
    add column if not exists redo_of_audit_id bigint references audits(id),
    add column if not exists strategy_version text references audit_strategies(version);

-- Partial: ~all rows are 'not_applicable'; the eval job's query only ever
-- looks for the two in-flight states, so index exactly those.
create index if not exists audits_measurement_inflight_idx
    on audits(measurement_status)
    where measurement_status in ('awaiting_window', 'measuring');

-- Per-channel rollout flag (CIL §1.9 MEASUREMENT_ENABLED — per-channel like
-- the thumbnail/playlist-health flags). Default false: one-channel-first.
alter table channels
    add column if not exists measurement_enabled boolean default false;
