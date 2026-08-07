-- Bootstrap for a SELF-HOSTED Postgres. Runs ONCE, before any migration.
--
-- The migrations in ../migrations were written against Supabase, which
-- pre-provisions things bare Postgres does not. Rather than edit 33 historical
-- migrations (they are an applied ledger — rewriting them makes the two
-- environments diverge silently), this shim provides what they assume.
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

-- ── 2. storage.buckets shim ───────────────────────────────────────────────
-- 20260508082931_content_intelligence.sql registers a private 'keyframes'
-- bucket. Supabase Storage is NOT part of this deployment: app/keyframes.py is
-- the only module that ever used it and nothing imports that module (see the
-- note at app/audits.py:19). This table exists purely so that historical
-- migration applies unchanged. If Storage is ever genuinely needed, it needs a
-- real service, not this.
create schema if not exists storage;

create table if not exists storage.buckets (
    id      text primary key,
    name    text not null,
    public  boolean not null default false
);

grant usage on schema storage to service_role;
grant all on all tables in schema storage to service_role;
