-- Slice 3 · S3.4 (#119, spec Part 6 S3.4, Part 2 §3.1, §7): the title agent's
-- run, stored on every agent-path title row whatever its end (a title, a
-- decline, a failure): the model, the turns, how it ended, its submitted
-- titles, and each message, tool call and tool result, each cut to 2,000
-- characters (app/agent/loop.py). NULL on every other row.
-- Written by app/agent_tick.py through interventions.record, which sends the
-- column only when there is a trajectory, so nothing else needs this applied.
alter table interventions add column if not exists trajectory jsonb;
