-- Team tracker 02 (#144, spec #142) — logins: app_users and app_sessions.
--
-- Midas had no authentication and published port 8000 to the office LAN while
-- holding write-scoped YouTube tokens. These two tables back the login page and
-- the global gate (app/session.py). Users are created by
-- scripts/manage_users.py; there is no signup.
--
-- app_users.password_hash is an argon2id hash (argon2-cffi). `role` is checked
-- here and mirrored by app/status_vocab.py UserRole (tests/test_status_vocab.py).
-- `email` is stored lower-cased by the app.
--
-- app_sessions keys a session by the sha256 (hex) of its cookie token: the raw
-- token is never stored, so a read of this table can't sign anyone in. A session
-- is valid while expires_at is in the future AND its user is active; the app
-- checks both on every request, and deletes an expired row when it reads one
-- (no scheduled job). Deleting a user removes their sessions (cascade).

create table if not exists app_users (
    id             bigserial    primary key,
    email          text         not null unique,
    name           text         not null,
    password_hash  text         not null,
    role           text         not null check (role in ('admin', 'exec', 'manager')),
    is_active      boolean      not null default true,
    created_at     timestamptz  not null default now()
);

create table if not exists app_sessions (
    token_hash   text         primary key,
    user_id      bigint       not null references app_users(id) on delete cascade,
    expires_at   timestamptz  not null,
    created_at   timestamptz  not null default now()
);

-- Backs the cascade, and "every session of this user" (deactivate).
create index if not exists app_sessions_user_idx on app_sessions (user_id);

grant all on app_users to service_role;
grant all on sequence app_users_id_seq to service_role;
grant all on app_sessions to service_role;
