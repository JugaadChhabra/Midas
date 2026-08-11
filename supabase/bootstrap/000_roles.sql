-- Bootstrap part 1 of 2: ROLES ONLY. Runs before anything else, and before a
-- restore.
--
-- Split out from the storage shim deliberately. app/provision.py restores a
-- pg_dump into an empty database on first boot, and a plain pg_dump contains
-- SCHEMAS but not ROLES — roles are cluster-level. So the dump's own
-- `CREATE SCHEMA storage` collides with a pre-created one ("schema storage
-- already exists", and the restore stops), while its GRANT statements need the
-- roles to already exist. Roles before, everything else after.
--
-- Safe to re-run.

-- ── 1. Roles ──────────────────────────────────────────────────────────────
-- Five migrations `grant execute ... to service_role`. PostgREST also needs an
-- anonymous role to switch from. `authenticated` is unused by this app but is
-- created so a copied-in Supabase migration cannot fail on it later.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
end
$$;

-- The app connects as service_role via PostgREST's role switching, so the
-- connection role must be allowed to become it.
do $$
declare
  connection_role text := current_user;
begin
  execute format('grant anon, authenticated, service_role to %I', connection_role);
end
$$;

grant usage on schema public to anon, authenticated, service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant all on all functions in schema public to service_role;

-- Anything a later migration creates, too.
alter default privileges in schema public
  grant all on tables    to service_role;
alter default privileges in schema public
  grant all on sequences to service_role;
alter default privileges in schema public
  grant all on functions to service_role;
