-- Bootstrap part 2 of 2: the storage.buckets shim, plus the grants that have to
-- be re-applied once tables actually exist.
--
-- Runs AFTER a restore (see 000_roles.sql for why the split), and after the
-- migrations otherwise. Safe to re-run.

-- ── storage.buckets shim ──
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

-- Re-apply the object grants now that the tables exist. The equivalents in
-- 000_roles.sql run against an empty schema — `all tables in schema public`
-- grants nothing when there are none. ALTER DEFAULT PRIVILEGES covers what the
-- restore creates afterwards, but only for objects the same role creates, so
-- this is the belt to that's braces.
grant usage on schema public to anon, authenticated, service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant all on all functions in schema public to service_role;
