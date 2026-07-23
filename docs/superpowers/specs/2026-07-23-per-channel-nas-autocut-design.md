# Per-Channel NAS Auto-Cut — Design

**Date:** 2026-07-23
**Status:** Approved design, pending implementation plan
**Scope:** Automate the NAS pick → cut → save flow per channel, controlled from each channel's Autopilot tab. Reuses the existing autopilot scheduler + shorts dispatcher.

---

## Goal

Let each channel automatically cut every video in its mapped NAS language folder into Shorts (saving to `COMPLETED/<LANG>/`), toggled on/off from that channel's UI, plus an on-demand "Cut now" button. No YouTube upload.

---

## Why this is small

The automation infrastructure already exists (`app/main.py`):
- **APScheduler** runs `autopilot_tick` every `AUTOPILOT_TICK_SECONDS` (120s) — picks one channel round-robin (`autopilot_last_tick_at`).
- **`dispatch_tick`** every `SHORTS_DISPATCH_INTERVAL_SECONDS` (5s) launches `CREATED` jobs up to `SHORTS_MAX_CONCURRENT_JOBS`.

So automation = re-point the autopilot's shorts action at `enqueue_language_jobs()` and let the dispatcher (already NAS-aware via the runner branch) drain the queue. `channels.nas_folder` and `channels.autopilot_shorts_enabled` columns already exist — **no migration needed**.

---

## Decisions (from brainstorming)

| Decision | Choice |
| --- | --- |
| Folder → channel mapping | **Both**: auto-derive from channel name (one-off backfill), plus a dropdown per channel to correct/override |
| Trigger | **Auto toggle + "Cut now" button** |
| Throttle | **Drain continuously** — enqueue all uncut each tick (dedup-guarded); the dispatcher's concurrency cap is the only limit |
| Upload | None (NAS in → NAS out) |
| Existing code | Preserve. The YouTube fetch/cut/upload code and the legacy `_next_uncut_video_for_channel` / `_shorts_made_today` helpers stay; only the autopilot's *automatic enqueue* switches to NAS |

---

## Components

### 1. Backend — autopilot re-point (`app/autopilot.py`)

Replace the body of `_run_shorts_action(ch)` with the NAS enqueue:

```python
def _run_shorts_action(ch: dict) -> None:
    """Enqueue NAS cuts for this channel's language folder. No-op unless the
    channel has a nas_folder set. The dispatcher (throttled by the concurrency
    cap) drains the queue; in-flight dedup keeps re-ticks idempotent."""
    folder = ch.get("nas_folder")
    if not folder:
        return
    if active_job_count() >= settings.SHORTS_MAX_CONCURRENT_JOBS:
        return  # queue already full; next tick tops it up
    try:
        n = enqueue_language_jobs(
            folder, channel_id=ch["id"], autopilot=True,
            cut_mode=ch.get("shorts_cut_mode") or "highlights",
            camera_motion=ch.get("shorts_camera_motion") or "calm",
        )
    except ValueError:
        log.warning("Autopilot shorts: channel %s has unknown nas_folder %r", ch["id"], folder)
        return
    if n:
        log.info("Autopilot shorts: enqueued %d NAS job(s) for %s (folder %s)", n, ch["id"], folder)
```

- `tick()` already gates on `autopilot_shorts_enabled` before calling this and already `select("*")` (so `nas_folder` is present). No change to `tick()`.
- `enqueue_language_jobs` with no `limit` enqueues every uncut file; already-`CREATED`/in-flight files are skipped (dedup), so re-ticks add only genuinely new files.
- Import `enqueue_language_jobs` from `app.shorts.nas_source` (guard the import to avoid pulling heavy deps at module load — mirror the lazy pattern already used for the cutter).
- **Left intact, now unused by this action:** `_next_uncut_video_for_channel`, `_shorts_made_today`. Not deleted.

### 2. Backend — expose `nas_folder` on the channel API (`app/auth.py`)

- `list_channels` select (line ~109): add `nas_folder`.
- `ChannelSettings`: add `nas_folder: str | None = None`.
- `update_channel`: accept it, validating against the live folder list:

```python
    if body.nas_folder is not None:
        folder = body.nas_folder.strip().upper()
        if folder and folder not in list_source_languages():
            raise HTTPException(400, f"Unknown NAS folder: {folder}")
        patch["nas_folder"] = folder or None
```

(Import `list_source_languages` from `app.shorts.nas_source`.)

### 3. Backend — "Cut now" reuses the existing endpoint

No new endpoint. The UI's "Cut now" calls the existing `POST /shorts/cut {language}` with the channel's `nas_folder`. (Enqueues immediately; dispatcher picks up within 5s.)

### 4. Backend — one-off auto-derive backfill (`scripts/backfill_nas_folder.py`)

Match each channel's name to a folder and set `nas_folder` where unset:

```python
# For every channel with nas_folder NULL, uppercase-match a folder name that
# appears as a word in the channel name; set it if exactly one matches.
from app.db import supabase
from app.shorts.nas_source import list_source_languages

def main() -> int:
    folders = list_source_languages()
    chans = supabase().table("channels").select("id,name,nas_folder").execute().data or []
    for c in chans:
        if c.get("nas_folder"):
            continue
        name = (c.get("name") or "").upper()
        hits = [f for f in folders if f in name]
        if len(hits) == 1:
            supabase().table("channels").update({"nas_folder": hits[0]}).eq("id", c["id"]).execute()
            print(f"{c['name']} -> {hits[0]}")
        else:
            print(f"{c['name']} -> (no unique match: {hits or 'none'})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Idempotent (skips channels already set); run manually, review the "no unique match" lines and fix those via the dropdown.

### 5. UI — "Shorts (NAS)" card in the channel Autopilot tab (`app/static/channel.html`)

A small card under Autopilot settings:

```
Shorts (NAS)
Language folder:  [ HINDI ▾ ]      144 uncut · 2 cutting
[✓] Auto-cut this folder
[ Cut now ]                        <status/toast area>
```

- **Folder dropdown** — options from `GET /shorts/languages` (label = folder, plus its uncut count); current value = channel's `nas_folder`. On change → `PATCH /auth/channels/{id} {nas_folder}`.
- **Auto-cut toggle** — bound to `autopilot_shorts_enabled`; on change → `PATCH {autopilot_shorts_enabled}`.
- **Cut now** button → `POST /shorts/cut {language: <nas_folder>}`; toast the enqueued count. Disabled if no folder set.
- **Status line** — `uncut` from `GET /shorts/languages` (the row for this folder) + `cutting` = count of this channel's non-terminal `shorts_jobs` (`GET /shorts/jobs?channel_id=`). Refreshed on tab load and after "Cut now".
- Populate on channel load from the `/auth/channels` data (which now includes `nas_folder`).

No job-list table returns (we deleted it); this card is status + controls only. A richer job view is a later, separate build.

---

## Flow (end to end)

```
User sets folder (dropdown) + flips Auto-cut on  ->  PATCH channel
   autopilot_tick (120s) picks the channel, sees autopilot_shorts_enabled
     -> _run_shorts_action -> enqueue_language_jobs(nas_folder) -> N CREATED jobs
   dispatch_tick (5s) launches up to SHORTS_MAX_CONCURRENT_JOBS
     -> runner NAS branch: copy -> cut -> write clips + move source to COMPLETED/<LANG>/
   next ticks top up the queue until the folder is drained
"Cut now" -> POST /shorts/cut{folder} -> same enqueue, immediately
```

---

## Testing

- `_run_shorts_action`: no-op when `nas_folder` is None; calls `enqueue_language_jobs` with the folder + channel_id when set; no-op when the queue is already at the cap; swallows unknown-folder `ValueError`.
- `update_channel`: accepts a valid `nas_folder`, uppercases it, rejects an unknown one (400), clears it on empty string.
- Backfill: sets folder on a uniquely-matching channel, skips already-set, leaves ambiguous unset.
- UI: manual check — dropdown lists folders, toggle + Cut now issue the right requests (browser or a light fetch-mock test).

---

## Open items to confirm at implementation

- Should the Autopilot tab still show the metadata-autopilot section header layout unchanged, with this card added below it? (assumed yes)
- "Cut now" while Auto-cut is already draining is harmless (dedup), but should the button be hidden when Auto-cut is on? (assumed: keep it — useful to kick immediately instead of waiting up to 120s)
