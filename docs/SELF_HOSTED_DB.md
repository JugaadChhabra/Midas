# Self-hosted Postgres — setup, cutover, and restore

Midas ran on a hosted Supabase project and hit its monthly usage ceiling, which
paused production. The binding cost was **egress**: reading a channel's whole
video table on every dashboard load is correct but unaffordable over the wire.
The app runs on a single office machine with a NAS beside it, so the database
moves onto that machine and the wire disappears.

Recovery is a nightly `pg_dump` pushed to the NAS, replacing the previous one.
Worst case is losing the current day's work.

---

## What actually had to be replicated

Not "Supabase" — the app only ever used two pieces of it:

| Supabase service | Used? | Notes |
|---|---|---|
| **PostgREST** (data API) | **yes, everywhere** | All ~190 call sites use the fluent builder (`supabase().table(...).select(...)`), not SQL. This is why Postgres alone is not enough. |
| **Postgres + pgvector** | **yes** | `video_embeddings.embedding` is `vector(3072)`; four RPCs are plain SQL functions. |
| GoTrue (auth) | no | Google OAuth is handled in `app/auth.py`. |
| Realtime | no | Never subscribed. |
| Storage | effectively no | One call, `app/keyframes.py:140` — and nothing imports that module (`app/audits.py:19` says so). See the shim note below. |

So: **two containers**, `db` and `postgrest`. No app code changed; the client
only ever needed a base URL and a JWT.

---

## First-time setup

### 1. Secrets

```bash
export PGRST_JWT_SECRET="$(openssl rand -base64 48)"
python scripts/make_service_key.py
```

Put both printed lines in `.env`, plus a database password:

```
POSTGRES_PASSWORD=<something long>
PGRST_JWT_SECRET=<from above>
SUPABASE_SERVICE_KEY=<from above>
```

`SUPABASE_URL` is set for you in `docker-compose.yml` (`http://postgrest:3000`).
The secret and the key are a matched pair — rotating one invalidates the other.

### 2. Start the database

```bash
docker compose up -d db postgrest
```

### 3. Create the schema

```bash
DATABASE_URL="postgresql://midas:$POSTGRES_PASSWORD@localhost:5432/midas" \
  python scripts/apply_migrations.py
```

(Publish the `db` port first — it is commented out in `docker-compose.yml` — or
run this inside the `midas` container, where `DATABASE_URL` is already set.)

This applies `supabase/bootstrap/*.sql` and then all of `supabase/migrations/*.sql`
in timestamp order, recording each in a `schema_migrations` table so re-runs are
no-ops. `--status` shows what is applied; `--dry-run` shows what is pending.

**Why a bootstrap file exists.** The 33 migrations were written against Supabase
and assume things bare Postgres lacks:

- five of them `grant execute ... to service_role`, a role Supabase provides;
- `20260508082931_content_intelligence.sql` inserts into `storage.buckets`.

`supabase/bootstrap/000_local_compat.sql` creates the roles and a minimal
`storage.buckets` table so those migrations apply **unchanged**. Editing the
historical migrations would have been the other option and is worse — they are an
applied ledger, and rewriting them makes the hosted and local schemas diverge
silently.

### 4. Move the data across

Requires the Supabase project resumed (it is paused).

```bash
# from the hosted project — Settings -> Database -> Connection string
pg_dump --no-owner --no-privileges --data-only \
        "postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres" \
        --file supabase-data.sql

psql "postgresql://midas:$POSTGRES_PASSWORD@localhost:5432/midas" \
     -f supabase-data.sql
```

`--data-only` because step 3 already built the schema. Spot-check row counts on
`videos`, `audits` and `video_embeddings` before cutting over.

### 5. Start the app

```bash
docker compose up -d
```

---

## Nightly backup

`app/backup.py`, scheduled at `BACKUP_HOUR` (default 00:00 **server-local** —
the office's midnight, which is what bounds the accepted data loss).

It publishes in stages rather than dumping over the live file:

```
pg_dump -> local temp -> verify completion marker -> upload as .tmp -> move
```

A dump that dies partway through (disk full, container restart, NAS drop) would
otherwise overwrite the last good backup with a truncated one, and nothing would
say so until a restore was attempted. Any failure now leaves the previous
snapshot exactly where it was.

### Verified on the office NAS, 2026-08-11

`run_nightly_backup()` — the actual scheduler entry point, not a stand-in — run
on-network with `NAS_MODE=smb`: **366.1 MB published in 90s**, overwriting the
previous snapshot, and the file read back off the share is **sha256-identical**
to the local dump. Restoring it into a throwaway database with
`psql -v ON_ERROR_STOP=1` exits 0, with row counts identical on every table and
`vector(3072)`, `jsonb` and `text[]` intact.

Four things only failed once this ran against real infrastructure, all now fixed
(commit `1bd66a5`):

1. **`NASService.move` could never overwrite.** It used `smbclient.rename`,
   which passes `replace_if_exists=False`. The staged publish moves a `.tmp`
   *onto* yesterday's snapshot, so it succeeded once and would have failed with
   `NtStatus 0xc0000035` every night after. Now `replace()`, matching what the
   `local` adapter already did.
2. **64 KB SMB buffers.** ~5,800 round trips for the dump, and the share dropped
   partway through with `[Errno 49] Can't assign requested address`. `SMB_CHUNK`
   is 4 MB; the same file now moves in ~80s.
3. **`pg_dump` version skew.** It refuses to dump a newer server, and a dev
   machine's client is often older (here 14 vs 16). `BACKUP_PG_DUMP` makes the
   binary configurable. The image installs the unversioned `postgresql-client`
   — Debian trixie has no `-16` package at all, which is why the image had been
   failing to build — with a build-time gate that fails if it is ever < 16.
4. **nginx's 8 KB header buffers** were smaller than hosted Supabase's, so the
   500-id `in_()` batches (~10 KB URLs) came back 414/502.

**Residual risk worth a decision.** One snapshot is kept, so if the database is
already corrupt when tonight's dump runs, a healthy-looking dump replaces the
last good copy. `BACKUP_SLOTS=2` alternates between two files by day-of-year —
one extra file, and that failure mode goes away. Default is `1`, matching the
stated intent of no redundant snapshots.

Failures log at `exception` level with `NIGHTLY DB BACKUP FAILED`. That is the
line to alert on: a silent backup failure is how you find out months later that
there is no backup.

---

## Where the data actually lives

`./pgdata`, bind-mounted to `/var/lib/postgresql/data` (`docker-compose.yml`).
Two consequences worth being explicit about, because both are easy to assume
wrongly:

**It does not reset on restart.** Postgres's entrypoint runs `initdb` only when
that directory is *empty*, so every later start just opens the existing cluster.
Restarts, `docker compose down`, and reboots all preserve the data. Deleting
`./pgdata` is the only thing that wipes it — and that is also the only way to
change `POSTGRES_PASSWORD`, since it is read at `initdb` time and ignored after.

**It does not travel with the image.** `pgdata/` is gitignored, the image holds
app code only, nothing is mounted to `/docker-entrypoint-initdb.d`, and the app
does not apply migrations at startup. So on a machine that has never run this
before, `docker compose up` gives you a **completely empty database** and an app
that 404s on every table. Standing one up is the manual sequence below — there
is no automatic path from the NAS snapshot into a fresh cluster.

---

## Restore, or standing up a new machine

Same procedure either way: the snapshot is a full dump, so restoring it *is* the
migration.

```bash
# 1. Secrets. POSTGRES_PASSWORD, PGRST_JWT_SECRET, LOCAL_SERVICE_KEY and
#    DATABASE_URL must match the ones in .env on the machine you are replacing —
#    LOCAL_SERVICE_KEY is a JWT signed with PGRST_JWT_SECRET, so a fresh secret
#    means minting a fresh key (scripts/make_service_key.py).
docker compose up -d db          # creates an empty cluster on first run

# 2. Roles. The dump is --no-owner --no-privileges, so it needs no *original*
#    roles — but PostgREST still needs anon/authenticated/service_role to exist,
#    and they are not in the dump.
psql "$DATABASE_URL" -f supabase/bootstrap/000_local_compat.sql

# 3. Data. This creates the schema as well; do NOT run apply_migrations first.
#    fetch <NAS>/midas-db-backups/midas.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f midas.sql

# 4. Only if the dump predates a migration.
python scripts/apply_migrations.py

docker compose up -d             # postgrest, rest, midas
```

Restoring over a *live* database instead of an empty one: `docker compose stop
midas` first, so the app is not writing while the dump replays.

`ON_ERROR_STOP=1` matters — without it psql reports failures on stderr and still
exits 0, which is how a half-restored database gets mistaken for a good one.

---

## Things that did not change, deliberately

**The 1000-row cap stays at 1000.** `PGRST_DB_MAX_ROWS` could be raised now that
egress is free, and it is tempting: that cap is the single most-repeated bug in
this codebase. It stays because `app/rows.py` pages correctly either way, and
raising it locally would let unpaged code work here and silently truncate on any
hosted deployment — the exact failure mode that was just removed from five call
sites in `sync.py`.

**Reads still go through PostgREST.** `DATABASE_URL` exists only for `pg_dump`
and the migration runner. Nothing on the app's read path uses it, so there is no
second data-access idiom to keep in sync.
