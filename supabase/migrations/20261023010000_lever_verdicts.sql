-- Slice 1 · S1.6b (#68) — lever_verdicts, the weekly verdict per channel and lever.
--
-- Spec Part 4 S1.6 (P1, D6, D8). Written by the weekly `lever_measurement` job
-- (app/lever_verdicts.py) after S1.6a's pair measurement. Per channel, lever and
-- week (week_start = the Monday, UTC, of the week the rows were judged in):
--
--   * `treated_vs_holdout`: the treated arm's mean delta minus the holdout arm's,
--     over the `midas` rows judged that week (`lift`), and over every row judged
--     so far (`cumulative_lift`). No row for a week without a judged row in each
--     arm. `windows_judged` counts the channel's verdict weeks so far, this one
--     included; `stop_rule_triggered` is the P1 stop rule, read by triage
--     (app/agent_tick.py backlinks_stopped). Blocks already applied stay (D8).
--   * `human`: the SEO team's backlinks judged that week, on their own (§1.4):
--     n_treated and treated_mean_delta only; no lift, no verdict, never stopped.
--
-- `delta` is in attributable views per week (lever_measurement._result), so
-- lift and BACKLINK_MIN_LIFT share D6's unit. The vocabularies live in
-- app/status_vocab.py (LeverVerdictScope, LeverVerdict). Rows of past weeks are
-- not rewritten; a rerun in the same week replaces that week's row.

create table if not exists lever_verdicts (
    id                   bigserial        primary key,
    channel_id           text             not null references channels(id),
    lever                text             not null,   -- backlinks
    arm_scope            text             not null,   -- treated_vs_holdout|human
    week_start           date             not null,
    n_treated            int              not null,
    n_holdout            int              not null,
    treated_mean_delta   double precision,
    holdout_mean_delta   double precision,
    lift                 double precision,
    cumulative_lift      double precision,
    windows_judged       int              not null,
    verdict              text,                        -- helped|no_change|worse
    stop_rule_triggered  boolean          not null default false,
    computed_at          timestamptz      not null default now(),
    unique (channel_id, lever, arm_scope, week_start)
);
