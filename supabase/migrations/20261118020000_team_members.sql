-- Team tracker 07 (#148, spec #142) — team_members: each manager's roster.
--
-- Records only: a team member has no login and never sees their own numbers.
-- A member belongs to one manager (app_users, role `manager`); a manager sees
-- and edits only their own members, admin and exec every member
-- (app/team.py, app/access.py require_team_member).
--
-- Members are deactivated, never deleted, so the uploads credited to them
-- stay credited (channel_assignments, #149, will point here). Likewise no
-- `on delete` action on manager_id: app users are deactivated, not deleted
-- (scripts/manage_users.py).

create table if not exists team_members (
    id          bigserial    primary key,
    name        text         not null,
    manager_id  bigint       not null references app_users(id),
    is_active   boolean      not null default true,
    created_at  timestamptz  not null default now()
);

-- Backs "the members of this manager" (every manager's roster read).
create index if not exists team_members_manager_idx on team_members (manager_id);

grant all on team_members to service_role;
grant all on sequence team_members_id_seq to service_role;
