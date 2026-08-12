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

`supabase/bootstrap/*.sql` creates the roles and a minimal `storage.buckets`
table so those migrations apply **unchanged**. It is two files, not one, because
`app/provision.py` needs the roles *before* a restore and the rest *after* —
see "Restoring by hand" below. Editing the
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

### Snapshot again after any DB change — don't wait for the nightly

The nightly run bounds *steady-state* data loss to one day. It does nothing about
the window between changing the database and the next 00:00: during it, the only
snapshot on the NAS describes a database that no longer exists. Restore from it
after a schema migration and you get the pre-migration schema back, which the
running code no longer matches — a restore that "succeeds" and then fails at the
first query is worse than an obvious one.

So: **after a migration, a backfill, or any bulk mutation, publish a snapshot.**

```bash
# on-network (NAS_MODE=smb), AFTER verifying the change landed
PYTHONPATH=. venv/bin/python -c \
  "from app.backup import snapshot_to_nas; print(snapshot_to_nas())"
```

`snapshot_to_nas()` is the same function the scheduler calls, minus
`run_nightly_backup`'s never-raise wrapper — so a failure surfaces as a
traceback instead of a log line, which is what you want when running it by hand.
Both guards still apply: it refuses to publish from an empty database
(`assert_populated`) and refuses to dump with a `pg_dump` whose major version
does not equal the server's.

Order it correctly: **verify, then snapshot.** Publishing replaces a slot, so
snapshotting an unverified change trades a known-good copy for an unknown one.

Slot arithmetic bounds what an extra run can cost you. `BACKUP_SLOTS=2` and
`_slot_name` picks `day_of_year % 2`, so an ad-hoc snapshot lands in *today's*
slot — the one that night's run will overwrite anyway. It can never consume
yesterday's. The corollary is that extra runs buy no extra history: slots rotate
by date, not by invocation.

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
3. **`pg_dump` version skew, in both directions.** The client major must EQUAL
   the server's — see the section below, which is where that is written down.
4. **nginx's 8 KB header buffers** were smaller than hosted Supabase's, so the
   500-id `in_()` batches (~10 KB URLs) came back 414/502.

**Two slots, since 2026-08-11.** `BACKUP_SLOTS=2` alternates between
`midas.0.sql` and `midas.1.sql` by day-of-year. With one slot, a database that is
already corrupt at midnight produces a healthy-looking dump that replaces the
last good copy — and now that a new machine restores itself on first boot, the
next deploy would restore that corruption. One extra file on the NAS removes the
whole failure mode.

There is no fixed filename to restore any more, so `app/provision.py` picks the
most recently modified snapshot in the directory rather than a name computed
from the current setting. That is also what makes raising the setting safe: for
one night the only backup that exists is still the old single-slot `midas.sql`,
and it is still found. The staged `.tmp` is excluded — it is a half-uploaded
file by definition, and it is the newest thing in the directory while it is
being written.

Failures log at `exception` level with `NIGHTLY DB BACKUP FAILED`. That is the
line to alert on: a silent backup failure is how you find out months later that
there is no backup.

---

## Where the data actually lives, and how a new machine gets it

`./pgdata`, bind-mounted to `/var/lib/postgresql/data`.

**It does not reset on restart.** Postgres runs `initdb` only when that
directory is *empty*, so every later start reopens the existing cluster.
Restarts, `docker compose down`, and reboots all preserve the data. Deleting
`./pgdata` is the only thing that wipes it — and also the only way to change
`POSTGRES_PASSWORD`, which is read at `initdb` time and ignored afterwards.

**A machine that has never run Midas provisions itself.** `pgdata/` is
gitignored and the image carries app code only, so a new machine starts with an
empty cluster. On startup `app/provision.py` notices, pulls last night's
snapshot off the NAS, and restores it — before a single scheduled job is
registered. Deploying is `docker compose up` plus a `.env`, which is the point:
the tool should be runnable by someone who never has to learn what psql is.

Only machines you have put a `.env` on can do this, and only on the office
network. That is the intended blast radius.

### It fails closed

If the database is empty and the NAS is unreachable, **the app does not start**.
Starting anyway is much worse than not starting: it would serve an empty
catalogue as if it were real, and at 00:00 the backup would dump that empty
database over the last good snapshot — turning a missing mount into permanent
data loss. `snapshot_to_nas()` refuses from the other side too, so both ends of
that loop are closed.

`RESTORE_ON_EMPTY=false` opts out.

### Client and server major versions must be EQUAL

Not "client at least as new", which is the easy half-memory:

* **older client than the server** — `pg_dump` refuses to run. Loud, harmless.
* **newer client than the server** — `pg_dump` runs fine and writes a dump the
  server cannot replay. pg_dump 18 against this pg16 emits
  `SET transaction_timeout = 0`, a parameter added in pg17, and the restore dies
  on line 13 with `unrecognized configuration parameter`.

The second one is the dangerous one: nothing fails until the day someone needs
the backup. The image installs `postgresql-client-16` from apt.postgresql.org
(Debian trixie carries only 17) with a build-time assertion, and
`_assert_pg_dump_matches_server()` re-checks against the live server before
every dump, so a server upgrade cannot silently orphan a pinned client.

On this Mac: `BACKUP_PG_DUMP` and `RESTORE_PSQL` point at
`/opt/homebrew/opt/postgresql@16/bin/` — the default `pg_dump` is 14 (refuses)
and libpq's is 18 (writes an unreplayable dump).

### Verified 2026-08-11

A brand-new empty database, provisioned from the real NAS snapshot:
**366.1 MB restored in 206s**, every row count identical, `vector(3072)` intact,
`service_role` able to read, all four RPCs present.

---

## Restoring by hand

The automatic path above covers a new machine. To force a restore over a
database that already has data — recovering from corruption, say — the app will
not do it for you, since it only acts on an empty database:

```bash
docker compose stop midas
psql "$DATABASE_URL" -f supabase/bootstrap/000_roles.sql     # roles are not in the dump
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f midas.sql
psql "$DATABASE_URL" -f supabase/bootstrap/010_storage_shim.sql
docker compose start midas
```

The bootstrap is split around the restore on purpose: a plain `pg_dump` carries
schemas but **not** roles (they are cluster-level), so `anon`/`service_role` must
exist before its GRANTs run — while pre-creating the storage shim collides with
the dump's own `CREATE SCHEMA storage` and stops the restore dead.

`ON_ERROR_STOP=1` is not optional. Without it psql reports failures on stderr
and still exits 0, which is how a half-restored database gets mistaken for a
good one.

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
