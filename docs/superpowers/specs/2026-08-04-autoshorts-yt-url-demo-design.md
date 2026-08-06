# AutoShorts — YouTube-URL demo page (design)

Date: 2026-08-04
Status: approved

## Goal

Revive the retired YouTube-URL shorts download flow and put a clean, standalone
web page in front of it so a YouTube link can be turned into shorts live during
a product demo. The tool is presented as **AutoShorts**.

Non-goal: changing how production shorts work. The NAS-sourced flow, autopilot,
and the Docker image are untouched.

## Constraints

- Runs on the local Mac (venv + local bgutil script provider). No Docker or
  sidecar work.
- Nothing is published to YouTube. Clips are cut, kept on disk, and shown in the
  page for preview and download.
- No database migration.

## Design

### 1. Un-retire the download path

`app/shorts/cutter/download.py::fetch_video` currently raises immediately; the
working yt-dlp implementation is retained below that raise. Remove the raise so
the existing implementation runs again. No new download logic is written.

Dependency pins are uncommented (`yt-dlp`, `bgutil-ytdlp-pot-provider`), and
`SHORTS_YT_DOWNLOAD_ENABLED=true` is set in `.env`. The `config.py` default stays
`false` so any Docker/prod deployment keeps the retired behaviour.

Local token minting uses the bgutil **script** provider
(`tools/bgutil-pot/server/build/generate_once.js`), which is already built on
this machine — `BGUTIL_POT_HTTP_BASE_URL` is unset, so `ytdlp_options()` selects
script mode automatically.

### 2. Cut without publishing

`run_shorts_job`'s URL branch already supports holding clips: with
`upload_cap = N`, clips beyond the first N are inserted as `PENDING` with a
`local_path` and never uploaded. `upload_cap = 0` therefore means "cut
everything, publish nothing" — every clip is written to disk and recorded, and
no YouTube upload call is made.

The only code change is the progress label, which currently reads
"uploading 0 of N clips" when the cap holds everything.

### 3. Serve clip files

New `GET /shorts/clips/{clip_id}/file` returns the clip's `local_path` as a
`FileResponse`. The resolved path must sit inside `SHORTS_CACHE_DIR`; anything
else is a 404. This single endpoint backs both inline `<video>` playback and the
download button.

### 4. Demo router

All demo-only server code lives in `app/shorts/autoshorts.py` so the feature is
one file plus one HTML page and can be removed cleanly after the demo.

- `POST /autoshorts/jobs {url}` — validates the URL with the existing
  `is_youtube_url`, inserts a `shorts_jobs` row with `upload_cap = 0`,
  `cut_mode = "highlights"`, `camera_motion = "calm"`,
  `autopilot_generated = false`. Returns `{job_id}`.
  `shorts_jobs.channel_id` is `NOT NULL` and a foreign key to `channels`, so the
  job borrows the first channel row. Nothing is ever published to that channel;
  this only satisfies the constraint and avoids a migration.
  Gated on `SHORTS_YT_DOWNLOAD_ENABLED`, same as the other URL entry points.
- `GET /autoshorts` — serves the page.

Progress polling reuses the existing `GET /shorts/jobs/{job_id}`, which already
returns the job row plus its clips.

Job execution needs no new machinery: the existing dispatcher picks up `CREATED`
rows and spawns `app.shorts.worker`.

### 5. The page

`app/static/autoshorts.html`, built on the shared `theme.css` tokens so it reads
as part of Midas and works in light and dark.

- Centered single column. **AutoShorts** wordmark at the top.
- One URL field and a "Make Shorts" button.
- A progress bar with the live stage label from the job row
  (downloading → analysing → rendering → done).
- A responsive grid of 9:16 clip cards, each an inline `<video>` plus a download
  link pointing at the clip-file endpoint.
- No navigation, no channel picker, no cut settings.

## Error handling

- Invalid or non-YouTube URL: 400 from the endpoint, shown inline under the field.
- Flag off: 503 with a plain message, so the page fails loudly rather than
  hanging on a job that will never run.
- Job failure: the poll sees `FAILED` and renders `error_message` in place of the
  progress bar. Download and PO-token failures already produce specific,
  actionable messages in `download.py`.
- Clip file missing on disk: 404 from the file endpoint; the card shows the
  video element's own error state.

## Verification

- `pytest tests/shorts` passes.
- A real YouTube URL downloads through the venv. Two known risks are checked
  empirically rather than assumed:
  - Deno is not installed on this machine and yt-dlp's EJS solver reportedly
    rejects node for the n-challenge. If the download fails on that, install
    Deno.
  - The venv has yt-dlp 2026.07.04, not the verified-good 2026.6.9 pin. Test
    with what is installed; downgrade only if it breaks.
- End to end: submit a URL on `/autoshorts`, watch progress advance, play a
  resulting clip in the page, and download it.
