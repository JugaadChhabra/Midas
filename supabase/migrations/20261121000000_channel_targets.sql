-- Team tracker: targets move from members to channels, and the Board's moves
-- (docs/superpowers/specs/2026-11-20-channel-targets-board-design.md).
--
-- channel_targets: each channel's daily upload target per ISO weekday
-- (1 = Monday … 7 = Sunday), Shorts and long-form apart. Whoever is credited
-- with the channel on a day (app/team_uploads.py _holder) carries that day's
-- target, so a reassigned channel takes its target with it. The current target
-- only, no history: changing it recolours past days on the grid. Written only by
-- PUT /channels/{id}/targets (app/team.py). A channel with no rows has no target.
--
-- member_targets (20261120000000) is dropped: a member's number can't be split
-- across their channels, and it held a day of data (owner, 2026-11-20).

create table if not exists channel_targets (
    channel_id   text         not null references channels(id) on delete cascade,
    weekday      smallint     not null check (weekday between 1 and 7),
    shorts       int          not null default 0 check (shorts >= 0),
    long_form    int          not null default 0 check (long_form >= 0),
    updated_by   bigint       references app_users(id),
    updated_at   timestamptz  not null default now(),
    primary key (channel_id, weekday)
);

grant all on channel_targets to service_role;

drop table if exists member_targets;

-- Move a channel on the Board, in one transaction (PostgREST runs one statement
-- per request; a function call is one transaction):
--   * to a member (p_team_member_id set): the channel's manager becomes the
--     member's manager, then assign_channel() closes the open row and opens the
--     member's from p_starts_on (the same member already open: unchanged);
--   * to a manager's tray (p_team_member_id null): the channel's manager becomes
--     p_manager_id (null = no manager) and its open assignment ends at
--     p_starts_on, or at the row's own start if that is later (an empty range,
--     crediting nothing).
-- The API checks who may move what first (app/team.py move_channel); this is
-- the backstop for the pairing of the two writes. Guarded by
-- tests/test_move_channel_sql.py.
create or replace function move_channel(
    p_channel_id      text,
    p_team_member_id  bigint,
    p_manager_id      bigint,
    p_starts_on       date,
    p_moved_by        bigint
)
returns jsonb
language plpgsql
as $$
declare
    v_manager  bigint;
    v_open     channel_assignments;
    v_row      channel_assignments;
begin
    if p_team_member_id is not null then
        select manager_id into v_manager from team_members where id = p_team_member_id;
        if not found then
            raise exception 'team member % not found', p_team_member_id using errcode = '22023';
        end if;
        update channels set manager_id = v_manager where id = p_channel_id;
        v_row := assign_channel(p_channel_id, p_team_member_id, p_starts_on, p_moved_by);
        return jsonb_build_object('manager_id', v_manager, 'team_member_id', p_team_member_id,
                                  'assignment_id', v_row.id);
    end if;

    update channels set manager_id = p_manager_id where id = p_channel_id;
    select * into v_open
      from channel_assignments
     where channel_id = p_channel_id and ends_on is null
       for update;
    if found then
        update channel_assignments
           set ends_on = greatest(p_starts_on, v_open.starts_on)
         where id = v_open.id;
    end if;
    return jsonb_build_object('manager_id', p_manager_id, 'team_member_id', null,
                              'assignment_id', null);
end;
$$;

revoke execute on function move_channel(text, bigint, bigint, date, bigint) from public;
grant  execute on function move_channel(text, bigint, bigint, date, bigint) to service_role;
