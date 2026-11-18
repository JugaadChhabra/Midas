-- Team tracker 08 (#149, spec #142) — channel_assignments: which team member
-- holds which channel, on which IST days.
--
-- A row covers [starts_on, ends_on): IST dates, ends_on exclusive, NULL while
-- the assignment is current. Reassigning a channel closes its open row at the
-- new row's start and opens the new one, so an upload is credited to whoever
-- held the channel on its IST upload day, and history is never re-credited.
-- No back-dating before the open row's start in v1, so ranges never overlap
-- without an exclusion constraint.
--
-- Written only by app/team.py: POST /channels/{id}/assign through
-- assign_channel() below, and PATCH /team/members/{id} deactivating a member
-- (ends their open rows). No `on delete` on team_member_id: members are
-- deactivated, never deleted.

create table if not exists channel_assignments (
    id              bigserial    primary key,
    channel_id      text         not null references channels(id) on delete cascade,
    team_member_id  bigint       not null references team_members(id),
    starts_on       date         not null,   -- IST date
    ends_on         date,                    -- exclusive; null = current
    assigned_by     bigint       references app_users(id),
    created_at      timestamptz  not null default now(),
    -- ends_on = starts_on is an empty range: an assignment replaced on the day
    -- it started, which credits nothing.
    constraint channel_assignments_range check (ends_on is null or ends_on >= starts_on)
);

-- At most one open assignment per channel.
create unique index if not exists channel_assignments_one_open
    on channel_assignments (channel_id) where ends_on is null;

-- Backs "the open assignments of this member" (deactivation).
create index if not exists channel_assignments_member_idx
    on channel_assignments (team_member_id);

grant all on channel_assignments to service_role;
grant all on sequence channel_assignments_id_seq to service_role;

-- Close the channel's open assignment and open the new one, in one transaction
-- (PostgREST runs one statement per request; a function call is one
-- transaction). The open row is locked first, so two concurrent assigns
-- serialise; with no open row, the unique index refuses the second insert.
-- The same member already open is returned unchanged. A start before the open
-- row's start raises (the API refuses it first; this is the backstop).
-- Guarded by tests/test_assign_channel_sql.py.
create or replace function assign_channel(
    p_channel_id      text,
    p_team_member_id  bigint,
    p_starts_on       date,
    p_assigned_by     bigint
)
returns channel_assignments
language plpgsql
as $$
declare
    v_open  channel_assignments;
    v_new   channel_assignments;
begin
    select * into v_open
      from channel_assignments
     where channel_id = p_channel_id and ends_on is null
       for update;

    if found then
        if p_starts_on < v_open.starts_on then
            raise exception 'starts_on % is before the open assignment''s start %',
                p_starts_on, v_open.starts_on
                using errcode = '22023';
        end if;
        if v_open.team_member_id = p_team_member_id then
            return v_open;
        end if;
        update channel_assignments set ends_on = p_starts_on where id = v_open.id;
    end if;

    insert into channel_assignments (channel_id, team_member_id, starts_on, assigned_by)
    values (p_channel_id, p_team_member_id, p_starts_on, p_assigned_by)
    returning * into v_new;
    return v_new;
end;
$$;

revoke execute on function assign_channel(text, bigint, date, bigint) from public;
grant  execute on function assign_channel(text, bigint, date, bigint) to service_role;
