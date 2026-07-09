# Local Shorts Cutter — Replace WayinVideo with the RhymeShortsCutter Pipeline

**Date:** 2026-07-09
**Status:** Approved (design), pending implementation plan
**Source codebase:** `~/Downloads/RhymeShortsCutter_Mac` (to be archived after the port)

## Goal

Replace the third-party WayinVideo clipping API in Midas's shorts feature with the
local RhymeShortsCutter pipeline: vocal-safe cut detection, stanza/highlight
selection, smart-follow vertical cropping, and native-quality yt-dlp downloads.
The cutter runs in-process on this Mac; rendered clips auto-upload to YouTube as
private shorts via the existing `upload_short()`.

## Decisions (settled during brainstorming)

- **Full transplant** (not a pip package, not a sidecar service). One repo: Midas.
- **Local-only runtime.** ML deps install into Midas's venv. The Docker image does
  NOT gain the ML stack.
- **Auto-upload as private** — keep Wayin's post-render behavior; no human review
  gate between render and upload.
- The RhymeShortsCutter repo cleanup happens *as* the port: its 970-line `main.py`
  dissolves into focused modules while moving. No separate cleanup of the old repo.

## 1. Package layout

```
app/shorts/
  routes.py          # rewired: drives local cutter instead of Wayin
  runner.py          # NEW: background-thread job orchestration (replaces poller.py)
  youtube_upload.py  # unchanged
  cutter/            # NEW: the pipeline, framework-free
    __init__.py      # public entry: cut_video(source, mode, ...) -> clip metadata + paths
    download.py      # ytdlp_options + fetch_with_ytdlp   (from cutter main.py)
    transcribe.py    # Whisper loading, transcription, SRT (from cutter main.py)
    render.py        # ffmpeg render/export/crop commands  (from cutter main.py)
    pipeline.py      # process_video orchestration         (from cutter main.py)
    framing.py       # moved as-is
    vocals.py        # moved as-is
    structure.py     # moved as-is
    cutplan.py       # moved as-is
    selection.py     # moved as-is
    grading.py       # moved as-is
```

**Deleted:** `app/shorts/wayin_client.py`, `app/shorts/poller.py`, and the Wayin
normalization/streaming-upload parts of the old `app/shorts/pipeline.py` (its
`upload_short()` call-out survives inside `runner.py`).

**Hard boundary:** nothing in `app/shorts/cutter/` imports FastAPI or Supabase.
The package takes a file path + options and returns clip paths + metadata, and
reports progress via a plain callback. This keeps pipeline tests framework-free
and leaves the door open to running the cutter as a separate worker later.

## 2. Job flow

`POST /shorts/jobs` accepts `channel_id`, `source_url`, and new optional fields
`cut_mode` (`highlights` | `stanzas`, default `highlights`) and `camera_motion`.
It inserts the `shorts_jobs` row (as today) and starts a Python `threading.Thread`
(the cutter's current approach; APScheduler keeps its cron duties but its pool is
not used for minutes-long CPU jobs).

The thread runs, updating `shorts_jobs.status/progress/progress_label` at each
stage:

1. **DOWNLOADING** — yt-dlp at native upload quality (`bv*+ba/b`, mkv merge,
   mweb client + bgutil PO-token script; ported verbatim from the cutter).
2. **ANALYSING** — transcription (multilingual Whisper), vocal-safe cut points,
   stanza/highlight selection, smart-crop analysis.
3. **RENDERING** — vertical master + per-clip exports into
   `SHORTS_CACHE_DIR/<job_id>/`.
4. **UPLOADING** — one `shorts_clips` row per rendered clip (`local_path` set,
   `source_url` null), then `upload_short()` per clip as private, updating
   `upload_status` per clip as today.
5. **DONE** (or **FAILED** with `error_message`). A macOS notification fires on
   completion (three lines, ported from the cutter).

Clip titles/descriptions: video title + stanza/clip index for v1. AI-generated
metadata via the existing OpenRouter client is an explicit follow-up, out of
scope here.

The UI polls job status from Supabase exactly as it polls Wayin statuses today —
no websocket work.

**Concurrency:** one cutter job at a time. If a job is already CREATED/DOWNLOADING/
ANALYSING/RENDERING/UPLOADING, `POST /shorts/jobs` returns 409. The Mac cannot
run two Whisper+YOLO jobs concurrently anyway; a queue is a follow-up if ever
needed.

**Crash recovery:** jobs are thread-local; if the server restarts mid-job the row
stays stuck in a working status. On startup, any job in a working status is
marked FAILED with "server restarted mid-job" (replaces the Wayin poller's
4-hour age ceiling).

## 3. Schema migration (additive only)

New migration:

- `shorts_jobs` gains `progress int not null default 0`,
  `progress_label text`, `cut_mode text`.
- Status vocabulary becomes
  `CREATED → DOWNLOADING → ANALYSING → RENDERING → UPLOADING → DONE / FAILED`.
  Historical rows keep their old Wayin statuses (`QUEUED`, `ONGOING`,
  `SUCCEEDED`); no data rewrite. Any status checks in code treat unknown
  statuses as terminal.
- `shorts_clips.source_url` becomes null for new rows (clips are local;
  `local_path` always set). `shorts_jobs.wayinvideo_project_id` remains as a
  dead column — not worth a destructive migration.

## 4. UI (`static/shorts.html`)

Keeps its job-list + create-job shape, gains:

- cut-mode toggle (highlights vs. full stanzas),
- camera-motion setting,
- progress bar + stage label driven by the new `progress`/`progress_label`
  fields.

The cutter's drag-and-drop file upload is dropped for v1 (Midas's flow is
URL-driven and channel-scoped). `WAYINVIDEO_*` env vars and any related UI
copy are removed.

## 5. Dependencies, tests, old repo

- `requirements.txt` gains the ML stack pinned to the versions currently working
  in the cutter's venv (torch, faster-whisper, ultralytics, opencv-python,
  numpy, yt-dlp already present). Note: torchaudio is known-broken in the
  cutter's venv and is NOT required — do not add it.
- YOLO `.pt` weights stay gitignored; ultralytics auto-downloads on first run.
- ffmpeg and node (for the bgutil PO-token script) are runtime prerequisites on
  the Mac; `tools/bgutil-pot/` moves into Midas (gitignored build output, same
  as today) and its script path is resolved relative to the repo root.
- Dockerfile explicitly does not install ML extras; the shorts feature degrades
  with a clear error if imports fail in a container.
- The cutter's 14 test files move to Midas `tests/`. Pipeline tests port
  unchanged (framework-free boundary). The cutter's wiring tests are rewritten
  against the new routes/runner with Supabase mocked. Existing Wayin tests are
  deleted with the modules they test.
- **Definition of done:** tests green AND one real end-to-end run — a real
  YouTube URL cut and uploaded as private shorts to the connected channel.
- After that, `RhymeShortsCutter_Mac` gets a final README commit pointing to
  Midas and the GitHub repo is archived.

## Out of scope (explicit follow-ups)

- AI-generated clip titles/descriptions/hashtags via OpenRouter.
- Human review gate before upload.
- File-upload input (non-YouTube sources).
- Job queue / multi-job concurrency.
- Running the cutter as a separate worker container.
