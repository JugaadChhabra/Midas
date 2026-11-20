-- Team tracker: member_targets, each team member's daily upload target.
--
-- One row per member per ISO weekday (1 = Monday … 7 = Sunday): how many
-- Shorts and how many long-form videos they should put live that day. The
-- current target only, no history: the uploads grid judges every day it shows
-- against these numbers (app/team_uploads.py), so changing a target recolours
-- past days too.
--
-- Written only by PUT /team/members/{id}/targets (app/team.py): a manager for
-- their own members, the admin for anyone. A member with no rows has no target.

create table if not exists member_targets (
    team_member_id  bigint       not null references team_members(id),
    weekday         smallint     not null check (weekday between 1 and 7),
    shorts          int          not null default 0 check (shorts >= 0),
    long_form       int          not null default 0 check (long_form >= 0),
    updated_by      bigint       references app_users(id),
    updated_at      timestamptz  not null default now(),
    primary key (team_member_id, weekday)
);

grant all on member_targets to service_role;
