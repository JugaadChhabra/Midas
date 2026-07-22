# NAS-Sourced Shorts Cutter — Design

**Date:** 2026-07-22
**Status:** Approved design (revised to real NAS structure), pending implementation plan
**Scope:** Replace the shorts cutter's YouTube/yt-dlp source with NAS SMB folders. Manual trigger per language. No YouTube upload — outputs go back to a second NAS directory.

---

## Goal

Add a NAS-sourced cutting path **alongside** the existing YouTube/yt-dlp one (which stays fully intact). When triggered for a language:

1. Read source rhyme videos from that language's folder on the NAS (over SMB).
2. Cut each uncut video into vertical Shorts (existing cutter pipeline, unchanged).
3. Write the generated Shorts **and** move the consumed source video into the destination NAS directory, into the matching language subfolder.
4. **No YouTube upload.** NAS in → NAS out.

---

## Real NAS structure (verified live)

Server `10.1.1.3`, share `DATA`. Two roots, both with the **same 11 language subfolders**:

```
Animations/SHORTS CUTTER/RHYMES/        <- NAS_SOURCE_ROOT_PATH
    BANGLA/  BHOJPURI/  ENGLISH/  GUJARATI/  HARYANVI/  HINDI/
    MALAYALAM/  MARATHI/  PUNJABI/  RAJASTHANI/  TAMIL/
        <rhyme>.mp4  (also some .mov)

Animations/SHORTS CUTTER/COMPLETED/     <- NAS_DESTINATION_ROOT_PATH
    (same 11 language subfolders; created on first write if missing)
```

- **Source of a language L:** `RHYMES/<L>/*.mp4` (loose files, no date/subfolders).
- **Output for L:** `COMPLETED/<L>/` receives both the generated short clips and the moved source video.
- Same folder name in both roots → language is unambiguous.
- Note: `COMPLETED/` is currently empty; the code creates `COMPLETED/<L>/` on demand.

---

## Decisions (from brainstorming)

| Decision | Choice |
| --- | --- |
| Source lookup | Enumerate every video file in one language folder |
| Trigger | **Manual, per language** (endpoint/CLI) for now while building/testing. **Autopilot is kept, not deleted** — it will drive the same enqueue at deploy time; inert until a channel is configured with a folder. |
| Upload | **None** for now. No YouTube upload; NAS in → NAS out. |
| yt-dlp | **Kept fully intact.** NAS is an *additive* second source. The runner branches: `source_nas_path` set → NAS flow; else → existing yt-dlp flow, untouched. **Nothing is deleted.** |
| NAS access | SMB over the network (`smbprotocol`) |
| Dedup | Move source to `COMPLETED/<L>/` after a successful cut (gone from `RHYMES`) |
| Move timing | After clips are successfully cut |
| Job execution | Reuse the existing `shorts_jobs` queue + dispatcher + runner (throttled, tracked, reaped) |
| Existing code | **Preserve everything.** No deletions. Legacy YouTube-URL endpoints, autopilot shorts action, `download.py`, `youtube_upload.py` all stay working. New code sits alongside. |

---

## Flow

```
POST /shorts/cut {language: "HINDI"}
  -> list RHYMES/HINDI/*.mp4
  -> for each file with no in-flight job and under retry cap:
         insert shorts_jobs row (language=HINDI, source_nas_path=HINDI/<file>, status=CREATED)
  -> return {language, enqueued: N}

dispatcher (existing) picks up CREATED jobs, runs run_shorts_job in a worker thread:
  1. copy RHYMES/HINDI/<file>  ->  local job_dir/src/
  2. cut_video(...)  (unchanged)
  3. on success:
       - write each clip  ->  COMPLETED/HINDI/<clip>.mp4
       - move source  RHYMES/HINDI/<file> -> COMPLETED/HINDI/<file>
       - status=DONE
     on failure: status=FAILED, source left in RHYMES (retry-capped)
```

---

## Components

### 1. NAS access layer

**`app/services/nas_service.py`** — adapt the provided `NASService`:
- Import from `app.config` (`from app.config import settings`).
- Read the repo's setting names (below). SMB mode.
- Methods:
  - `list_video_files(relative_dir)` — `smbclient.scandir` filtered to video extensions (`.mp4 .mov .mkv .webm .avi`), skip `.DS_Store`, sorted; returns filenames.
  - `copy_to_local(relative_path, local_dest)` — stream the SMB file to a local path (ffmpeg/Whisper/YOLO need a real file). Replaces `fetch_video`.
  - `copy_from_local(local_src, relative_path)` — `makedirs` dest dir on the NAS, stream-write a local clip up to it.
  - `move(src_relative, dst_relative)` — `makedirs` dest dir, then `smbclient.rename`.
- Paths are relative to the **share** (`//10.1.1.3/DATA`); source/dest roots are prepended by the caller (see helpers).

**`app/config.py`** — add to `Settings`:
- `NAS_MODE` (default `smb`)
- `NAS_SERVER`, `NAS_SHARE`, `NAS_USERNAME`, `NAS_PASSWORD`, `NAS_DOMAIN`, `NAS_PORT`
- `NAS_SOURCE_ROOT_PATH` = `Animations/SHORTS CUTTER/RHYMES`
- `NAS_DESTINATION_ROOT_PATH` = `Animations/SHORTS CUTTER/COMPLETED`

**`requirements.txt`** — add `smbprotocol` (installed in venv already).

### 2. Data model (migration)

`shorts_jobs` changes (single migration):
- Add **`language`** (text, nullable) — e.g. `"HINDI"`.
- Add **`source_nas_path`** (text, nullable) — path relative to the source root, e.g. `"HINDI/कन्या.mp4"`.
- Make **`channel_id`** nullable (manual NAS jobs have no channel; autopilot jobs still set it).
- `source_url` / `source_video_id` stay nullable (unused by NAS jobs).

`channels`:
- Add **`nas_folder`** (text, nullable) — the language folder this channel pulls from when autopilot runs (e.g. `"HINDI"`). Left NULL for all channels now → autopilot shorts is inert until deploy time.

`shorts_clips`:
- Add **`nas_path`** (text, nullable) — where the clip landed under `COMPLETED/<L>/`.

### 3. Shared enqueue helper

**`enqueue_language_jobs(language, *, channel_id=None, autopilot=False, limit=None)`** — the single core both the manual endpoint and autopilot call:
- Validate `language` is an existing folder under `RHYMES/`.
- List `RHYMES/<language>` video files.
- Skip files with an **in-flight** (non-terminal) `shorts_jobs` row for that `source_nas_path`, and files with **≥ `MAX_SHORTS_RETRY_ATTEMPTS` FAILED** jobs (poison guard).
- Insert a `CREATED` job per remaining file (`language`, `source_nas_path`, `channel_id`, `autopilot_generated`, cut/motion defaults). `limit` caps how many are enqueued per call (autopilot passes its daily/concurrency budget; manual passes `None` = all).
- Return the count enqueued.

### 4. Trigger endpoint

New in `app/shorts/routes.py`:
- **`GET /shorts/languages`** — list the 11 source folders with an uncut count (files in `RHYMES/<L>` minus in-flight jobs). Handy for the UI/CLI; optional but cheap.
- **`POST /shorts/cut`** body `{language: str}` → `enqueue_language_jobs(language)` → return `{language, enqueued: N}`.

(Optionally a tiny CLI `scripts/cut_language.py <LANG>` that calls the same helper, for headless runs.)

### 5. Runner (`run_shorts_job`) — branch, don't rewrite

Add a **NAS branch** at the top of the existing function; the legacy body is left untouched for `source_url` jobs.

```
if job.get("source_nas_path"):
    return _run_nas_shorts_job(job, job_dir)   # new path, no upload
# ... existing yt-dlp + upload flow unchanged below ...
```

New `_run_nas_shorts_job(job, job_dir)`:
1. `status=DOWNLOADING` → `nas_service.copy_to_local(SOURCE_ROOT + "/" + job["source_nas_path"], job_dir/"src"/<file>)`. `title = safe_name(filename stem)`.
2. `_cut_video(...)` — the same cutter call the legacy path uses.
3. On cut success:
   - `progress_label="saving to NAS"`.
   - For each clip: `copy_from_local(clip.path, DEST_ROOT + "/" + <L> + "/" + <clip filename>)`; insert a `shorts_clips` row with `nas_path` (and a static `upload_status="SAVED"`).
   - `move(SOURCE_ROOT + "/" + job["source_nas_path"], DEST_ROOT + "/" + <L> + "/" + <file>)`.
   - `status=DONE`. No YouTube upload.
4. On failure: `status=FAILED`, source left in `RHYMES` (retry-capped).

The legacy path keeps its `upload_short` / `upload_cap` / `yt_video_id` logic exactly as today.

### 6. Autopilot — untouched now, NAS-ready later

**No changes to autopilot in this build.** `_run_shorts_action`, `_next_uncut_video_for_channel`, the YouTube-URL job insert, and the `tick()` shorts branch all stay exactly as they are (still functional for the legacy YouTube flow).

Deploy-time switch to NAS autopilot is then a small, isolated change (not in scope now): have `_run_shorts_action` call the shared `enqueue_language_jobs(ch["nas_folder"], channel_id=ch["id"], autopilot=True, limit=…)` when `ch["nas_folder"]` is set. The `channels.nas_folder` column is added now so that future wiring needs no migration. Every channel's `nas_folder` is NULL, so nothing changes today.

**Channel→language mapping (deploy-time, trivial):** channel names already contain the language word. After channels are connected/saved to the DB, populate `nas_folder` by case-insensitively matching each channel name against the 11 folder names (BANGLA, BHOJPURI, ENGLISH, GUJARATI, HARYANVI, HINDI, MALAYALAM, MARATHI, PUNJABI, RAJASTHANI, TAMIL). A one-off backfill script, not a runtime procedure.

### 7. No removals

Nothing is deleted or moved. `download.py`, `youtube_upload.py`, the legacy `POST /shorts/jobs`, `POST /videos/{id}/short`, `POST /clips/{id}/upload` endpoints, `is_youtube_url`, and the autopilot shorts action all remain in place and keep working. The NAS flow is purely additive and selected per-job by the presence of `source_nas_path`.

Frontend (`channel.html`): **add** a per-language "Cut" trigger; leave existing buttons alone. (Optional / follow-up — backend + CLI can ship first.)

### 8. Testing

- **`NASService`** new methods in `local` mode against a temp dir simulating the share: `list_video_files` filter/order, `copy_to_local`, `copy_from_local`, `move` (creates dest dir + removes source).
- **Enqueue helper:** skips in-flight files, skips retry-capped files, enqueues the rest; rejects unknown language.
- **Runner** (mock `cut_video`): pushes clips to `COMPLETED/<L>/` + moves source on cut success; leaves source on cut failure; fetches into `src/`; never calls YouTube upload.

---

## Architecture choice

Reuse the existing `shorts_jobs` queue + dispatcher + runner — the manual endpoint only enqueues; proven job-state/concurrency/reaping infra runs them. Rejected: synchronous cutting in the request (folders have 100+ videos, minutes each) and a bespoke background walker (duplicates the dispatcher).

---

## Open items to confirm at implementation

- Keep `shorts_clips.upload_status` with a static `SAVED`, or drop it from the flow? (lean: `SAVED`)
- Frontend now or as a follow-up (backend + CLI first)?
- Default `cut_mode` / `camera_motion` for NAS jobs (lean: `highlights` / `calm`, as today).
