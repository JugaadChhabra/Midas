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

**Residual risk worth a decision.** One snapshot is kept, so if the database is
already corrupt when tonight's dump runs, a healthy-looking dump replaces the
last good copy. `BACKUP_SLOTS=2` alternates between two files by day-of-year —
one extra file, and that failure mode goes away. Default is `1`, matching the
stated intent of no redundant snapshots.

Failures log at `exception` level with `NIGHTLY DB BACKUP FAILED`. That is the
line to alert on: a silent backup failure is how you find out months later that
there is no backup.

---

## Restore

```bash
# fetch <NAS>/midas-db-backups/midas.sql
docker compose stop midas
psql "$DATABASE_URL" -f midas.sql
docker compose start midas
```

The dump is `--no-owner --no-privileges`, so it restores into a fresh database
without the original roles. Run `python scripts/apply_migrations.py` afterwards
only if the dump predates a migration.

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
