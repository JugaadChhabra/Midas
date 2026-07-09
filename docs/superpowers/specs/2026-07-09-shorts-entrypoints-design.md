# Shorts Entry Points — Per-Video Button, Autopilot Action, and Docker Deployment

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan
**Builds on:** `2026-07-09-local-shorts-cutter-design.md` (the ported cutter, now E2E-validated on the Mac via the standalone `/shorts` page).

## Goal

Give the shorts cutter two production entry points that mirror Midas's existing audit
flow, and make it runnable in the deployed Docker instance:

1. **Per-video "Make shorts" button** on the per-channel dashboard (`channel.html`),
   mirroring the audit button UX.
2. **Autopilot shorts action** — the tick loop auto-cuts new long-form videos per channel.
3. **Docker deployment** of the cutter (ML stack + node + PO-token sidecar) so both of
   the above run on the user's dedicated work machine, not only the Mac.

## Settled decisions (from brainstorming)

- **Top-N upload for autopilot.** Each cut yields 4–8 clips; each YouTube `videos.insert`
  costs ~1600 quota units against a shared 10,000/day. Autopilot uploads only the top-N
  clips (default 2), holds the rest. The manual button uploads all clips (user-initiated).
- **Reject-when-busy (keep 409).** The cutter runs one CPU-bound job at a time. No queue:
  a second request (button or autopilot) is rejected/skipped while a job is active.
  Autopilot naturally serializes by skipping a tick when `has_active_job()`.
- **ML in Docker.** Reverses the port's original "local-only" call. The deployed image
  gains the ML stack + node; the PO-token provider runs as an HTTP sidecar.
- **Separate autopilot toggle.** Shorts autopilot is independent of the metadata-audit
  autopilot toggle; a channel can run either, both, or neither.

## Shared core: one job path

Both entry points create a `shorts_jobs` row with `source_video_id` set and start the
cutter thread, subject to the existing `has_active_job()` 409 guard, then `runner`
downloads → cuts → renders → uploads. The only new runner behavior is an **upload cap**:

- `cut_video()` (in `app/shorts/cutter/pipeline.py`) extends each returned clip record
  with the grader's `verdict` (`PASS`/`CHECK`, already computed in the pipeline). No new
  analysis — the grades list is already aligned to the clips; surface it per record.
- `runner.run_shorts_job` reads a new job column `upload_cap` (nullable int). If `None`,
  upload every clip (current behavior). If an int N, sort clips by (`verdict==PASS` first,
  then rank) and upload only the first N; insert the remaining clips as `shorts_clips`
  rows with `upload_status="PENDING"` (held, on disk in `shorts_cache/<job>/clips/`, not
  uploaded).
- New endpoint **`POST /shorts/clips/{clip_id}/upload`** uploads one held (`PENDING`)
  clip on demand via the existing `upload_short()`, flipping it to `UPLOADED`/`FAILED`.
  Used by the "Upload" button on held clips.

## Phase B1 — Per-video button (usable locally immediately)

### Backend
- **`POST /videos/{video_id}/short`** (parallels `POST /videos/{video_id}/audit` in
  `app/audits.py`). Looks up the video (404 if missing), builds
  `https://www.youtube.com/watch?v={video_id}`, rejects with 409 if `has_active_job()`,
  inserts a `shorts_jobs` row (`channel_id` from the video, `source_video_id=video_id`,
  `source_url`, `cut_mode`/`camera_motion` from request body or channel defaults,
  `upload_cap=None` → upload all, `status="CREATED"`), then `start_job_thread(job_id)`.
  Returns the created job row. (Unlike audit, this is async — cutting takes minutes — so
  it returns `CREATED` and the UI polls, rather than returning a finished result.)
- **Video-list enrichment** (`GET /channels/{id}/videos`, `app/sync.py`): add per-video
  `is_short` (already in the `videos` table, currently not returned), plus shorts fields
  from the latest `shorts_jobs` row for that `source_video_id`: `shorts_status`,
  `shorts_job_id`, `clips_count`, `clips_uploaded` (counts from `shorts_clips`).

### Frontend (`app/static/channel.html`)
- In each video row, for **long-form videos only** (`is_short === false`), render a
  "Make shorts" button next to the existing Audit button. (Shorts are not re-cut into
  shorts.)
- Clicking POSTs to `/videos/{id}/short`, then opens the row's inline detail cell (same
  pattern as `audit-{id}`) and polls `GET /shorts/jobs/{job_id}` showing the progress bar
  (reuse the `/shorts` page's `WORKING` statuses + progress rendering), then lists the
  clips with per-clip `upload_status`. Held (`PENDING`) clips get an "Upload" button
  hitting `POST /shorts/clips/{clip_id}/upload`.
- Add shorts states to the row's status-pill map (reuse `STATE_META` pattern): a shorts
  pill showing the latest `shorts_status` (or "no shorts" when none), clickable to expand
  the detail cell.

## Phase B2 — Autopilot shorts action

### Migration (`channels`)
- `autopilot_shorts_enabled boolean default false`
- `autopilot_shorts_daily_cap int default 1` (source videos cut per day)
- `autopilot_shorts_upload_cap int default 2` (clips uploaded per cut)
- `shorts_cut_mode text default 'highlights'`, `shorts_camera_motion text default 'calm'`

### `tick()` (`app/autopilot.py`)
After the existing audit action, add an independent shorts action:
- Gate: `channel.autopilot_shorts_enabled` AND `not has_active_job()` AND today's
  autopilot shorts count `< autopilot_shorts_daily_cap`.
- Selection: `_next_uncut_video_for_channel(channel_id)` — newest-first public **long-form**
  (`is_short=false`) video with **no existing terminal `shorts_jobs` row** for that
  `source_video_id` (dedup).
- Action: insert a `shorts_jobs` row (`source_video_id`, `autopilot_generated=true`,
  `upload_cap=channel.autopilot_shorts_upload_cap`, cut_mode/motion from channel defaults,
  `status="CREATED"`) and `start_job_thread`. One video per tick; the running job blocks
  further starts via the 409 guard until it finishes.
- Daily count: `shorts_jobs` created today for the channel with `autopilot_generated=true`.

### Autopilot UI (`app/static/channel.html` autopilot card)
Add below the existing autopilot controls: an "Auto-generate shorts for long-form videos"
checkbox, cut-mode + camera-motion selects, and "videos/day" + "upload top N" number
inputs. Saved through the existing `PATCH /auth/channels/{id}` by extending the
`ChannelSettings` model (`app/auth.py:117`) and the update handler.

## Phase A — Docker deployment of the cutter

### `Dockerfile`
- Install `requirements-ml.txt` in addition to `requirements.txt`.
- Add `node` (needed for PO-token generation). `ffmpeg` is already installed.
- The YOLO weights (`.pt`) auto-download at first run; no COPY needed.

### PO-token provider as an HTTP sidecar
- Add the `bgutil-ytdlp-pot-provider` HTTP server as a service in `docker-compose.yml`.
- `download.py::ytdlp_options()` gains a dual mode: if env `BGUTIL_POT_HTTP_BASE_URL` is
  set (Docker), configure the `youtubepot-bgutilhttp` provider with that base URL; else
  fall back to the local `generate_once.js` script path (the Mac). This is the one code
  change that makes downloads work in both environments.

### Deployed validation
- Build the image, deploy on the work machine, run one real cut end-to-end there
  (a `POST /videos/{id}/short` from the dashboard), confirm the same success criteria as
  the Mac E2E, and confirm autopilot shorts fires on the deployed scheduler.

## Data model summary

- `shorts_jobs`: add `autopilot_generated boolean default false`, `upload_cap int`
  (nullable). `source_video_id` already exists.
- `channels`: the five columns in Phase B2.
- No changes to `shorts_clips` (held clips reuse `upload_status="PENDING"`).

## Testing

- `POST /videos/{id}/short`: 200 + job created + thread started; 404 unknown video; 409
  when busy (mocked `has_active_job`/`start_job_thread`/supabase).
- Video-list enrichment: a video with/without shorts jobs returns correct
  `is_short`/`shorts_status`/`clips_count`/`clips_uploaded`.
- Runner top-N: with `upload_cap=2` and 5 clips (mixed PASS/CHECK), exactly the 2 PASS-first
  clips upload and 3 are left `PENDING`; with `upload_cap=None`, all upload.
- `POST /shorts/clips/{id}/upload`: uploads a `PENDING` clip → `UPLOADED`.
- Autopilot action: enqueues for an un-cut long-form video, skips when a job is active,
  skips when over daily cap, dedups already-cut videos (all mocked, offline).
- Migration applies; new columns queryable.
- `download.py`: `ytdlp_options()` uses HTTP provider when `BGUTIL_POT_HTTP_BASE_URL` set,
  script path otherwise.

## Build order

1. **Phase B1** (per-video button) — delivers the missing dashboard button, usable on the
   Mac immediately.
2. **Phase B2** (autopilot action + settings).
3. **Phase A** (Docker enablement) — makes B1/B2 run on the deployed work machine, then
   the deployed E2E.

Then push the branch and open one PR covering the whole shorts feature (the port + these
entry points).

## Out of scope (explicit follow-ups)

- AI-generated clip titles/descriptions via OpenRouter (still a follow-up from the port).
- A job queue (rejected in favor of reject-when-busy).
- Reconciling the parallel `worktree-llm-cost-opt` "cleaner shorts UI" branch — noted, but
  handled separately.
- GPU acceleration in Docker (CPU-only, matching the Mac's deterministic setup).
