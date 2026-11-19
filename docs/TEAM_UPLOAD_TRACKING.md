# Team Upload Tracking — what to build on Midas

> **Status:** built (team tracker #143–#152, 2026-11-18). `STATE.md` is now the source of
> truth for what exists: tables in §2 (`app_users`, `app_sessions`, `channels.manager_id`,
> `team_members`, `channel_assignments`, `channel_uploads`), routes, the gate and access
> rules in §5, modules and the Team page in §5's module table. This document stays as the
> design record (written 2026-11-06 from a discussion held in the retired Argus repo); where
> its design-level detail differs from the code, `STATE.md` wins. Live at the office since
> 2026-11-19 (#153: migrations, the four users, every channel's manager). Changed since the
> design (owner, 2026-11-19): a channel's uploads from before its **first** assignment are
> credited to that first assignee (a later reassignment still never re-credits history), and
> the grid has a By channel view (#163, #164); videos count on their go-live day, not their
> upload day (§2 "Upload day").

## 1. Goal

Give the YouTube team leads logins to Midas so each one can run Midas on **their own
channels only**, map their team members to those channels, and see **what was uploaded
per day per person**. Upload views/analytics are out of scope; YouTube Studio covers that.

## 2. Decisions (locked)

| Topic | Decision |
|---|---|
| Who logs in | Jugaad (admin), Akshay (exec), Justin (manager), Ishwari (manager). Nobody else. |
| Team members | Pranav, Prakash, Meet, Heramb (under Justin); Rachel (under Ishwari). **Roster records, no logins**, never see their own numbers. |
| Shaheed | Dropped entirely. Thumbnail work is untrackable; not worth building for. |
| Channel visibility | Justin sees only his ~12 channels, Ishwari only her 3–4, Akshay sees all. |
| Midas operation | Justin/Ishwari pick and run Midas features (autopilot, audits, playlists, shorts…) on their channels. |
| Channel ↔ member | One channel → exactly one member at a time. Assignments are **dated** so reassignment never re-credits history. |
| Who assigns | A manager assigns **their own** members to **their own** channels. |
| Upload day | ~~A video counts on the IST day it was uploaded~~. **Changed 2026-11-19 (owner):** a video counts on the **IST day it goes live** (a scheduled video on its go-live day; a private, unscheduled one not at all), since the team schedules weekend videos ahead. |
| Freshness | Existing routine sync cadence (`SYNC_STALE_AFTER = 6h`, `app/sync.py`) is fine. No extra polling. |
| YouTube client / quota | **No new client.** Data comes from calls `sync_channel` already makes. Marginal quota ≈ 0. |
| Channel connection | Jugaad connects channels (OAuth on `localhost` on the office machine). Midas only runs channels owned by these two managers. |
| Akshay's exec view | Later. Not in this build. |

## 3. Step 0 — run the timestamp probe first

`scripts/probes/probe_upload_timestamps.py` (written, **not yet run or committed**) answers
the three facts the upload-day design rests on. Run it against a channel with a scheduled
video, once while scheduled and once after it goes live:

```bash
PYTHONPATH=. venv/bin/python scripts/probes/probe_upload_timestamps.py <channel_id> \
  --video-id <scheduled_video_id> --save before.json
# …after it goes public:
PYTHONPATH=. venv/bin/python scripts/probes/probe_upload_timestamps.py <channel_id> --compare before.json
```

Questions it must answer:

1. **Is a scheduled (private) video in the uploads playlist under the owner token?**
   Expected yes — `sync.py:224` already sees `privacyStatus == "private"` items and skips them.
2. **Which timestamp is the upload time and stays fixed when the video goes live?**
   Candidates: `playlistItem.snippet.publishedAt` (added-to-playlist, expected winner),
   `video.snippet.publishedAt` (documented to become the go-live time — expected to move).
   Confirm the winner against the upload time shown in YouTube Studio.
3. **Does the uploads playlist reorder when a scheduled video goes live?** Incremental sync
   stops at the first known id (`sync_channel`, "Newest-first ordering"). If a new upload
   can sit *below* a known one, it is missed until the next full sync (`FULL_SYNC_INTERVAL
   = 3 days`). Acceptable, but know it.

If (1) is "no", stop and redesign §5 before building anything else.

**Answers (2026-11-18, recorded on #143; the live probe moved to #153 as a rollout check):**
(1) yes — `sync_channel` already receives private items from the uploads playlist; (2) `uploaded_at`
= `playlistItem.snippet.publishedAt`, with both raw timestamps stored (`playlist_published_at`,
`video_published_at`) so it can be recomputed; (3) unknown, cost at most a ≤3-day lag until the next
full sync. Upload capture is built (#150): see STATE.md §2 `channel_uploads`.

## 4. Auth & access control

Midas has **no auth today** and publishes `8000:8000` to the LAN (`docker-compose.yml`), while
holding write-scoped tokens and running an autopilot. Auth closes that hole as a side effect.

### 4.1 Model

```sql
create table app_users (
    id             bigserial primary key,
    email          text not null unique,
    name           text not null,
    password_hash  text not null,
    role           text not null check (role in ('admin','exec','manager')),
    is_active      boolean not null default true,
    created_at     timestamptz not null default now()
);

create table app_sessions (
    token_hash   text primary key,           -- sha256 of the cookie value; raw token never stored
    user_id      bigint not null references app_users(id) on delete cascade,
    expires_at   timestamptz not null,
    created_at   timestamptz not null default now()
);

alter table channels add column if not exists manager_id bigint references app_users(id);
```

Roles:

| Role | Channels visible | Can do |
|---|---|---|
| `admin` | all | everything, incl. OAuth connect (`/auth/login`, `/auth/callback`), users, channel → manager mapping, `/quota`, `/health/*` detail |
| `exec` | all | everything a manager can, on all channels; no user/OAuth admin |
| `manager` | `channels.manager_id = me` | run Midas features + manage team/assignments on own channels |

### 4.2 Mechanics

- **Session cookie**, not JWT: the frontend is static HTML on the same origin, so an
  `httpOnly`, `SameSite=Lax` cookie works with zero JS changes to existing `fetch` calls.
  30-day expiry, server-side row so logout/deactivate is immediate.
- **Password hashing**: add `argon2-cffi` (or `bcrypt`) to `requirements.txt`. Pin exactly,
  per the file's existing convention.
- **No signup / invites.** Users are created with a script:
  `scripts/manage_users.py create --email … --name … --role manager` (prompts for password;
  also `reset-password`, `deactivate`). Built in #144: see STATE.md.
- **Login page**: `app/static/login.html` + `POST /session/login`, `POST /session/logout`,
  `GET /session/me` (sidebar uses it for name + role-based nav).
- **Global gate**: one middleware/dependency that 401s every route except an explicit
  allowlist: `/login`, `/session/login`, `/static/*` (login assets only need theme.css),
  `/health` (Docker healthcheck). HTML routes (`/`, `/channel`, …) redirect to `/login`
  instead of 401.
- **CSRF**: `SameSite=Lax` blocks cross-site POSTs from other origins; add an `Origin`
  header check on non-GET requests for belt-and-braces. LAN-only, so no more than that.

### 4.3 Channel scoping — the bulk of the work

64 routes today (`grep -rhoE '@(router|app)\.(get|post|put|patch|delete)' app`). Three kinds:

1. **Path has `{channel_id}`** (~33 routes: `/channels/{channel_id}/…` across `sync.py`,
   `audits.py`, `playlists_router.py`, `autopilot.py`, `reflection.py`, `performance.py`,
   `short_links.py`, `lever_verdicts.py`, `playlist_test.py`, `auth.py` PATCH…).
   → one dependency `require_channel(channel_id, user)` that 404s (not 403 — don't leak
   existence) if the channel isn't visible.
2. **Path has another object id** — `/videos/{video_id}`, `/audits/{audit_id}/…`,
   `/interventions/{intervention_id}/revert`, `/short-links/{recommendation_id}/…`,
   `/shorts/jobs/{job_id}`, `/clips/{clip_id}/…`, `/audits/{audit_id}/measurement`.
   → resolve object → `channel_id`, then the same check. One small resolver per object type.
3. **Global / list routes** — `/channels`, `/dashboard`, `/shorts/jobs`, `/shorts/languages`,
   `/autoshorts`, `/health/channels`, `/quota`, `/quota-cost-preview`, `/measurement/evaluate`,
   `/jobs`, `/health/jobs`.
   → filter by `visible_channel_ids(user)`, or restrict to admin. `/dashboard` is cached
   (`invalidate_dashboard_cache`) and backed by the `dashboard_summary()` RPC — the cache
   must become per-visibility-set (or compute unfiltered and filter on read).

Write it as: `app/access.py` with `current_user`, `visible_channel_ids(user)`,
`require_channel(...)`, and the per-object resolvers. Every route imports from there. The
access module, `channels.manager_id` and the channel-id routes are built in #145, the object
resolvers and object-id routes in #146: see STATE.md §5.

**Guard test (required):** `tests/test_route_access.py` walks `app.routes` and fails if any
route lacks an access dependency and isn't in the public allowlist. Then, for each kind
above, a parametrised test: manager A requesting manager B's channel/object gets 404, and
list endpoints never return B's rows. New routes added later then fail CI until scoped.

**Not affected:** the APScheduler jobs (`_register_jobs` in `app/main.py`) — autopilot,
sync, backups run across all channels as today. Auth limits the HTTP surface only.

## 5. Upload ingestion

### 5.1 Why a separate table, not `videos`

Sync deliberately keeps things *out of* `videos`:
- private videos are skipped (`sync.py:224`) — and scheduled = private until live;
- channels with `sync_shorts = false` skip Shorts entirely (`if not sync_shorts and is_short: continue`).

Both would undercount uploads. Putting private/Shorts rows into `videos` instead would mean
re-auditing all ~58 `table("videos")` readers plus the SQL RPCs (`dashboard_summary`, the
autopilot picker) to make sure none of them now act on private or opted-out Shorts. A
separate table avoids touching autopilot semantics at all:

```sql
create table channel_uploads (
    video_id              text primary key,
    channel_id            text not null references channels(id) on delete cascade,
    title                 text,
    is_short              boolean,
    duration_seconds      int,
    privacy_status        text,          -- latest seen: private / unlisted / public
    scheduled_publish_at  timestamptz,   -- video.status.publishAt, null once live
    uploaded_at           timestamptz not null,  -- set once, never changes (see trigger)
    first_seen_at         timestamptz not null default now(),
    last_seen_at          timestamptz not null default now()
);
create index channel_uploads_channel_uploaded on channel_uploads (channel_id, uploaded_at);

-- uploaded_at is write-once regardless of which code path upserts.
create function channel_uploads_freeze_uploaded_at() returns trigger language plpgsql as $$
begin
    new.uploaded_at   := old.uploaded_at;
    new.first_seen_at := old.first_seen_at;
    return new;
end $$;
create trigger channel_uploads_freeze before update on channel_uploads
    for each row execute function channel_uploads_freeze_uploaded_at();
```

### 5.2 Sync changes (`app/sync.py`, zero extra quota)

1. `yt_playlist_items_page` (`app/youtube_client.py`): request
   `part="snippet,contentDetails"` instead of `contentDetails` — same 1u cost — and carry
   `snippet.publishedAt` per video id through `sync_channel` (assuming the probe confirms it
   as the upload time; otherwise use whichever field §3 picks, falling back to
   `first_seen_at`).
2. In the per-item loop, **before** the private-skip and the `sync_shorts` skip, append a
   `channel_uploads` row (`is_short`, duration, privacy, `status.publishAt`, uploaded_at).
   `videos.list` already requests `snippet,statistics,contentDetails,status`, so every field
   is in hand.
3. Upsert `channel_uploads` in batches alongside the `videos` upsert. Wrap it like
   `_record_human_edits`: a failure logs and never fails the sync.
4. Private/scheduled and opted-out-Shorts videos never enter `videos`, so they are not
   "known" and the incremental walk re-fetches them each sync until they go public. That
   keeps their privacy/scheduled fields current for free-ish (1u per 50). No change needed.

### 5.3 Backfill

One full sync per channel (`sync_channel(id, full=True)`) populates history at
~1 + 2·ceil(N/50) units per channel. Spread across a few days with the existing quota gates,
or just let `FULL_SYNC_INTERVAL` (3 days) do it naturally after deploy. Videos deleted from
YouTube before the backfill won't appear — fine.

## 6. Team roster & assignments

```sql
create table team_members (
    id          bigserial primary key,
    name        text not null,
    manager_id  bigint not null references app_users(id),
    is_active   boolean not null default true,
    created_at  timestamptz not null default now()
);

create table channel_assignments (
    id              bigserial primary key,
    channel_id      text not null references channels(id) on delete cascade,
    team_member_id  bigint not null references team_members(id),
    starts_on       date not null,          -- IST date
    ends_on         date,                   -- null = current; exclusive end
    assigned_by     bigint references app_users(id),
    created_at      timestamptz not null default now()
);
-- At most one open assignment per channel.
create unique index channel_assignments_one_open on channel_assignments (channel_id) where ends_on is null;
```

Rules (enforced in the API, covered by tests):
- Assign = close the current open row (`ends_on = today`) and insert a new one, in one
  transaction (an RPC is simplest given PostgREST).
- A manager may only assign members whose `manager_id` = self to channels whose
  `manager_id` = self. Admin/exec may assign anything.
- Deactivating a member ends their open assignments.
- No overlapping ranges per channel (guaranteed by close-then-open; add a `btree_gist`
  exclusion constraint only if back-dated edits are ever allowed — they aren't in v1).

Endpoints (all scoped via `app/access.py`):
`GET/POST/PATCH /team/members`, `GET /team/assignments`, `POST /channels/{channel_id}/assign`
(body: `team_member_id`, optional `starts_on` defaulting to today IST),
admin-only `PATCH /channels/{channel_id}/manager`.

## 7. Daily output view

SQL RPC `team_daily_uploads(p_from date, p_to date, p_channel_ids text[])` (like
`dashboard_summary()`: `stable`, `grant execute … to service_role`). Pass the caller's
visible channel ids from Python, so the RPC itself stays scope-agnostic:

```sql
select tm.id as member_id, tm.name,
       (u.uploaded_at at time zone 'Asia/Kolkata')::date as day,
       count(*)                               as uploads,
       count(*) filter (where u.is_short)     as shorts,
       count(*) filter (where not u.is_short) as long_form
from channel_uploads u
left join channel_assignments a
       on a.channel_id = u.channel_id
      and (u.uploaded_at at time zone 'Asia/Kolkata')::date >= a.starts_on
      and (a.ends_on is null or (u.uploaded_at at time zone 'Asia/Kolkata')::date < a.ends_on)
left join team_members tm on tm.id = a.team_member_id
where u.channel_id = any(p_channel_ids)
  and (u.uploaded_at at time zone 'Asia/Kolkata')::date between p_from and p_to
group by 1, 2, 3;
```

`left join` so uploads on unassigned channels show as **"Unassigned"** rather than vanishing.
`is_short` can be null for not-yet-probed videos — show those as "unknown" or count with
long-form; decide when building.

Endpoints: `GET /team/uploads?from=&to=` (grid) and
`GET /team/uploads/videos?member_id=&day=` (drill-down list).

Page `app/static/team.html`, linked from `sidebar.js`:
- **Uploads grid**: rows = members (+ Unassigned), columns = days (default last 7, IST),
  cell = `total (S / L)`. Exec sees a manager filter (Justin / Ishwari / all).
- **Drill-down**: click a cell → thumbnails, title, channel, upload time IST, status pill
  (scheduled → shows go-live time / public / private / unlisted).
- **Freshness note**: show each channel's `last_synced_at` ("data up to 4h old"), since lag
  up to 6h is expected.
- **Roster & assignments tab**: members list (add/deactivate), channel → member dropdown per
  channel with assignment history.

Note: `app/quota.py` uses `America/Los_Angeles` for the **quota day**. Upload days are IST.
Different concepts; don't reuse `_quota_date`.

## 8. Frontend touches on existing pages

- `index.html` / `channel.html` / `autoshorts.html`: handle 401 → redirect to `/login`
  (one wrapper in `swr.js`/`components.js` if fetches go through it).
- `sidebar.js`: user pill + logout; channel switcher lists only visible channels (it already
  reads `/channels`, which becomes scoped); add "Team" nav item.
- Admin-only controls (connect channel, channel → manager) hidden for non-admins — but the
  server check is what counts.

## 9. Migrations & ops

- New file(s) under `supabase/migrations/` (timestamped, like the rest), applied with
  `scripts/apply_migrations.py`.
- **After applying on the office machine: verify, then refresh the NAS snapshot** —
  `CLAUDE.md` rule, `snapshot_to_nas()`.
- Bootstrap users with `scripts/manage_users.py create` and set `channels.manager_id` for every
  channel (admin UI or a one-off SQL) before handing logins out — a channel with
  `manager_id = null` is visible only to admin/exec.
- Update `STATE.md` in the same commits (new tables, routes, RPCs, pages, the auth gate).
- Docker healthcheck hits `/health` — keep it public.

## 10. Suggested build order

1. Run the probe (§3). Adjust §5 if needed.
2. Auth: tables, `manage_users.py`, session endpoints, login page, global gate. Ship this
   alone first — it also closes the open-LAN-port issue.
3. `app/access.py` + scope all 64 routes + `tests/test_route_access.py`. Biggest step.
4. `channel_uploads` table + sync changes + backfill.
5. Roster, assignments, `channels.manager_id`.
6. `team_daily_uploads` RPC + `team.html`.
7. `STATE.md`, migrate on the office machine, NAS snapshot, create the four users.

## 11. Open items (defaults chosen, change if wrong)

- **Akshay = `exec` with full operate rights** on all channels (not read-only). Default: yes.
- **Channel → manager mapping is admin-only** (Jugaad, at connect time). Default: yes.
- **Null `is_short`** in counts — default: count as long-form, show "?" in drill-down.
- **Unlisted uploads** count as uploads. Default: yes.
- **Deleted-after-upload videos** stay counted (row isn't removed). Default: yes — it was uploaded that day.
