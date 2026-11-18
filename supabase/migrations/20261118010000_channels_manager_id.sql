-- Team tracker 03 (#145, spec #142) — channels.manager_id: which manager sees a
-- channel.
--
-- app/access.py is the one place that reads it: admin and exec see every
-- channel, a manager sees the channels whose manager_id is them. NULL (every
-- channel until the admin maps it) = visible to admin and exec only, so a newly
-- connected channel isn't shown to the wrong team. Set only by the admin's
-- PATCH /channels/{id}/manager, which accepts an active `manager` user or NULL.
--
-- No `on delete` action: app users are deactivated, not deleted
-- (scripts/manage_users.py), so a mapped user is never removed under a channel.

alter table channels add column if not exists manager_id bigint references app_users(id);

-- Backs "the channels of this manager" (every manager request reads it).
create index if not exists channels_manager_idx on channels (manager_id);
