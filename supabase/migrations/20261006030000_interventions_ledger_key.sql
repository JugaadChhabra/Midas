-- Phase B · B3a (#33) — interventions.ledger_key, the human-edit ledger's
-- idempotency key.
--
-- The ledger (app/human_edits.py) records a link the SEO team added to a
-- description as one `human` backlinks intervention. A rerun of the same sync,
-- two syncs racing, or a sync whose videos upsert failed after the ledger wrote
-- would all see the same edit again. The key is deterministic in the edit
-- (source video, target video, the new description's hash), and the writer
-- inserts with ON CONFLICT (ledger_key) DO NOTHING, so the database refuses the
-- duplicate even under concurrent writers.
--
-- NULL for every row that isn't from the ledger (Midas interventions, from
-- Slice 1); NULLs are distinct, so they never conflict.

alter table interventions add column if not exists ledger_key text;

create unique index if not exists interventions_ledger_key_key
    on interventions (ledger_key);
