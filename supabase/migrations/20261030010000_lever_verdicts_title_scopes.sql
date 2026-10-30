-- Slice 3 · S3.5 (#120, spec Part 6 S3.5, F7): lever_verdicts gains the title
-- lever's two scopes, one per path against the shared holdout
-- (app/lever_verdicts.py title_verdicts). arm_scope has no check constraint, so
-- nothing changes in the column itself; this records the vocabulary
-- (app/status_vocab.py LeverVerdictScope, checked by tests/test_status_vocab.py)
-- on the column, since 20261023010000's comment is applied and can't change.
-- The app doesn't need this applied.
comment on column lever_verdicts.arm_scope is 'treated_vs_holdout|human|pipeline_vs_holdout|agent_vs_holdout';
