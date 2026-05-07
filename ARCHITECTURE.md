# Midas — Architecture

A FastAPI service that audits a creator's YouTube videos with an LLM and (optionally) pushes the suggested metadata back to YouTube. Single-process Python app, Supabase for storage, OpenRouter for the LLM, APScheduler for the autopilot loop.

## Stack

- **Backend**: FastAPI (Python), single process
- **Storage**: Supabase (Postgres) via `supabase-py`, service-role key
- **LLM**: OpenRouter (default model `google/gemini-2.0-flash-001`, vision-capable)
- **YouTube**: Google API client, OAuth2 per-channel refresh tokens
- **Scheduler**: APScheduler `BackgroundScheduler`, in-process
- **Frontend**: 3 static HTML pages served from `app/static/` (no build step)

## Layout

```
app/
  main.py            FastAPI app, router wiring, scheduler lifespan, static routes
  config.py          Env-driven Settings (models, quota, DRY_RUN, OAuth)
  db.py              Supabase client singleton
  auth.py            Google OAuth flow, channel/refresh-token storage
  youtube_client.py  Thin wrappers around googleapiclient (videos.list/update, playlistItems)
  sync.py            Pull uploads → upsert videos table; refresh applied-video stats
  audits.py          Audit prompt, audit_video(), validate_audit(), apply_audit_internal()
  openrouter.py      chat_json() — JSON-mode LLM call with optional image_urls
  autopilot.py       Per-channel state machine, tick loop, quota/safety gates
  quota.py           Daily YouTube quota tracker (Postgres-backed counter)
  performance.py     Before/after stats endpoints for applied audits
  static/            index.html, channel.html, performance.html

supabase/migrations/  channels, videos, audits, audit_configs, autopilot_state, quota
```

## Data model (Supabase)

- **channels** — one row per connected YouTube channel; stores OAuth refresh token, `default_language`, sync timestamps
- **videos** — synced uploads (shorts and `private` filtered out); title/desc/tags/stats, stable thumbnail URL, `privacy_status`, `last_fetched_at`
- **audits** — one row per audit run; `status` ∈ `pending|applied|failed|quarantined`, suggested fields, before-state snapshot, baseline stats at apply
- **audit_configs** — per-channel raw insights + generated prompt
- **autopilot_state** — per-channel paused flag, reason, last tick
- **quota** — daily YouTube API unit counter

## Core flows

**Connect**: `/auth/login` → Google OAuth → callback stores channel + refresh token.

**Sync** (`POST /channels/{id}/sync`): paginate uploads playlist → batch `videos.list` (50/page) → drop shorts (≤180s) and `private` → upsert. Thumbnail stored as stable `i.ytimg.com/vi/{id}/hqdefault.jpg` (no expiring token).

**Audit** (`POST /videos/{id}/audit`): loads video + per-channel prompt → calls OpenRouter with metadata + thumbnail URL as vision input → on image-fetch failure, retries text-only → inserts `pending` audit row. Refuses non-public videos.

**Apply** (`POST /audits/{audit_id}/apply`): captures before-state and apply-time stats baseline → `videos.update` (snippet + `selfDeclaredMadeForKids: true`, optional `defaultLanguage`) → marks audit `applied`. `DRY_RUN=true` short-circuits the write.

**Autopilot** (`autopilot.tick` every `AUTOPILOT_TICK_SECONDS`, default 120s):
1. Skip paused channels
2. Quota gate (YT daily units + safety buffer)
3. Pick next unaudited video (skips `applied|pending|quarantined`, retries `failed`)
4. Audit → `validate_audit()` (title/desc length, tag shape & total chars)
5. Invalid → mark `quarantined`; valid + quota OK → apply
6. 3 consecutive failures → pause channel

**Performance** (`/channels/{id}/performance`): refreshes stats for applied videos (`videos.list` stats only, 1 unit / 50) and reports deltas vs. `*_at_apply` baselines.

## Safety / guardrails

- `DRY_RUN` env flag blocks all `videos.update` writes
- Only `public` videos are audited (audits.py); sync skips only `private`, so unlisted is synced but rejected at audit
- `validate_audit()` enforces YouTube limits (title ≤100, desc ≤5000, ≤30 tags, tag chars ≤500) before any apply
- Quota tracker with safety buffer; channel auto-pauses on repeated failures
- Unsafe-model gate (autopilot won't apply with a model on the blocklist)

## Capabilities today

- Multi-channel OAuth + per-channel sync of long-form uploads
- LLM audit with thumbnail vision input, per-channel custom prompts via natural-language elaboration
- Manual audit + apply, or hands-off autopilot loop
- Before/after performance tracking on applied audits
- Dry-run mode for safe testing

## Known gaps

- Unlisted videos sync but can't be audited (inconsistent gate)
- Thumbnail vision fetch can silently fall back to text-only on some providers
- Autopilot is in-process — single replica only; restart drops the schedule until next tick
- No auth on the FastAPI endpoints themselves (session cookie only protects OAuth flow)
