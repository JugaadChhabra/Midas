-- Phase B · B5 (#36) — decision_log, the shadow record of every decide() call.
--
-- Spec Part 2 §7 / Part 3 B5. One row per decision (app/decide.py): the rules
-- answer, the backend's answer and probabilities (the `llm` backend until Jev
-- access exists; NULL when the backend failed), whose answer was used, and the
-- question-set version the answers belong to. While decide() runs in shadow,
-- `used` is always 'rules'. The vocabulary of `used` lives in
-- app/status_vocab.py (DecisionUsed).
--
-- `intervention_id` links a decision to the intervention it led to, once
-- Slice 1 writes them. `on delete set null`: an intervention goes when its
-- video is deleted (interventions.video_id cascades), and the decision stays.
-- Nothing calls decide() in Phase B.

create table if not exists decision_log (
    id                    bigserial   primary key,
    decided_at            timestamptz not null default now(),
    question_set_version  text        not null,
    subject               text        not null,   -- video / pair / candidate
    rules_answer          text        not null,
    jev_answer            text,
    jev_probs             jsonb,
    used                  text        not null,   -- rules|jev
    intervention_id       bigint      references interventions(id) on delete set null
);
