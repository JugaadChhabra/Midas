# Shorts Per-Video Button (Phase B1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-video "Make shorts" button to the channel dashboard that cuts a long-form video into shorts through the existing local cutter, mirroring the audit-flow UX, with a top-N upload cap and on-demand upload of held clips.

**Architecture:** One video-scoped endpoint (`POST /videos/{id}/short`) creates a `shorts_jobs` row (subject to the existing single-job 409 guard) and starts the cutter thread. The runner gains an `upload_cap`: it uploads the top-N clips (PASS-graded first) and holds the rest as `PENDING`, which a new `POST /shorts/clips/{id}/upload` endpoint can upload later. The video list is enriched with per-video shorts status, and `channel.html` renders a button + inline detail cell that polls the job and lists clips.

**Tech Stack:** FastAPI, Supabase (postgrest), the ported cutter (`app/shorts/cutter/`), vanilla JS in `app/static/channel.html`.

**Spec:** `docs/superpowers/specs/2026-07-09-shorts-entrypoints-design.md` (this plan implements Phase B1 only; Phase B2 autopilot and Phase A Docker are separate plans).

## Global Constraints

- Repo: `~/Documents/Github/Midas`, branch `feat/local-shorts-cutter`. Python: `venv/bin/python`, tests `venv/bin/pytest` (note `venv`, not `.venv`).
- The cutter package `app/shorts/cutter/` stays framework-free (no fastapi/app.db/app.config imports). Only `pipeline.py`'s return shape changes in this plan.
- Manual button uploads ALL clips (`upload_cap=None`). The top-N cap exists for autopilot (Phase B2) but is implemented and tested here.
- Reject-when-busy: `POST /videos/{id}/short` returns 409 when `has_active_job()` — no queue.
- Full suite (`venv/bin/pytest tests/ -q`) must stay green before every commit (currently 143 pass).
- Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Migration — `upload_cap` and `autopilot_generated` on `shorts_jobs`

**Files:**
- Create: `supabase/migrations/20260709150000_shorts_entrypoints.sql`

**Interfaces:**
- Produces: `shorts_jobs.upload_cap int` (nullable) and `shorts_jobs.autopilot_generated boolean default false`, used by Tasks 3-4 (upload_cap) and Phase B2 (autopilot_generated — added now to avoid a second migration).

- [ ] **Step 1: Write the migration**

```sql
-- Shorts entry points (docs/superpowers/specs/2026-07-09-shorts-entrypoints-design.md).
-- upload_cap: max clips to auto-upload for a job (null = upload all). The manual
-- per-video button sets null; autopilot (Phase B2) sets a small integer.
-- autopilot_generated: marks jobs created by the autopilot shorts action (Phase B2),
-- added here so the autopilot phase needs no further migration.
alter table shorts_jobs add column if not exists upload_cap int;
alter table shorts_jobs add column if not exists autopilot_generated boolean not null default false;
```

- [ ] **Step 2: Push and verify**

```bash
cd ~/Documents/Github/Midas && supabase db push
```
Verify: `venv/bin/python -c "from app.db import supabase; print(supabase().table('shorts_jobs').select('id,upload_cap,autopilot_generated').limit(1).execute().data)"` → runs without error.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260709150000_shorts_entrypoints.sql
git commit -m "feat: shorts_jobs upload_cap + autopilot_generated columns"
```

---

### Task 2: `cut_video` returns the grader verdict per clip

**Files:**
- Modify: `app/shorts/cutter/pipeline.py` (the clip-render loop, ~lines 143-152)
- Test: `tests/shorts/cutter/test_pipeline_api.py` (existing `test_cut_video_returns_clip_records`)

**Interfaces:**
- Consumes: `grades` (list from `grade_clips`, each element has a `"verdict"` key of `"PASS"`/`"CHECK"`), aligned by index to `stanzas`/clips.
- Produces: each dict in `cut_video()`'s returned `clips` list gains `"verdict": str`. Task 3's runner reads `clip["verdict"]`.

- [ ] **Step 1: Update the existing test to assert the verdict**

In `tests/shorts/cutter/test_pipeline_api.py`, the test already monkeypatches `grade_clips` to return `[{"verdict": "PASS", "reasons": []}, {"verdict": "PASS", "reasons": []}]`. Add an assertion after the existing clip-record assertions:

```python
    assert result["clips"][0]["verdict"] == "PASS"
    assert result["clips"][1]["verdict"] == "PASS"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
venv/bin/pytest tests/shorts/cutter/test_pipeline_api.py -q
```
Expected: FAIL with `KeyError: 'verdict'` (the record has no verdict yet).

- [ ] **Step 3: Add verdict to the clip record**

In `app/shorts/cutter/pipeline.py`, change the `clip_records.append({...})` block in the render loop to include the verdict from the aligned `grades` entry:

```python
        clip_records = []
        for index, stanza in enumerate(stanzas, start=1):
            _tick("rendering clips", 80 + int(15 * (index - 1) / max(len(stanzas), 1)))
            clip_name = f"{safe_name(preferred_name)}_stanza_{index:02}_{int(stanza.start):04d}s.mp4"
            clip_path = clips_dir / clip_name
            export_clip(master, clip_path, stanza.start, stanza.end)
            grade = grades[index - 1] if index - 1 < len(grades) else {}
            clip_records.append({
                "path": str(clip_path), "rank": index,
                "start_s": float(stanza.start), "end_s": float(stanza.end),
                "verdict": grade.get("verdict", "CHECK"),
            })
```
(The `grades` list is computed just above this loop by `grade_clips(...)` and is index-aligned to `stanzas`. The `if index-1 < len(grades)` guard keeps it safe if lengths ever diverge, defaulting to the conservative `"CHECK"`.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
venv/bin/pytest tests/shorts/cutter/test_pipeline_api.py -q && venv/bin/pytest tests/ -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/cutter/pipeline.py tests/shorts/cutter/test_pipeline_api.py
git commit -m "feat: cut_video includes grader verdict per clip record"
```

---

### Task 3: Runner honors `upload_cap` (top-N upload, hold the rest)

**Files:**
- Modify: `app/shorts/runner.py` (`run_shorts_job`, the clip loop)
- Test: `tests/shorts/test_runner.py`

**Interfaces:**
- Consumes: `job["upload_cap"]` (int or None); clip records with `"verdict"` from Task 2.
- Produces: with `upload_cap=N`, exactly N clips (PASS-first, then by rank) are uploaded and the rest are inserted as `shorts_clips` rows with `upload_status="PENDING"`; with `upload_cap=None`, all clips upload (unchanged behavior).

- [ ] **Step 1: Write the failing test**

Add to `tests/shorts/test_runner.py` (follows the existing `_fake_sb`/recorder house style already in that file):

```python
def test_run_shorts_job_upload_cap_uploads_top_n(tmp_path):
    recorder = []
    job = {"id": 5, "channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ",
           "cut_mode": "highlights", "camera_motion": "calm", "upload_cap": 2, "status": "CREATED"}
    clips = [
        {"path": str(tmp_path / "c1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0, "verdict": "CHECK"},
        {"path": str(tmp_path / "c2.mp4"), "rank": 2, "start_s": 10.0, "end_s": 20.0, "verdict": "PASS"},
        {"path": str(tmp_path / "c3.mp4"), "rank": 3, "start_s": 20.0, "end_s": 30.0, "verdict": "PASS"},
        {"path": str(tmp_path / "c4.mp4"), "rank": 4, "start_s": 30.0, "end_s": 40.0, "verdict": "CHECK"},
    ]
    for c in clips:
        Path(c["path"]).write_bytes(b"clip")
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(job, recorder)), \
         patch("app.shorts.runner._fetch_video", return_value=(tmp_path / "src.mkv", "My_Video")), \
         patch("app.shorts.runner._cut_video", return_value={"clips": clips, "message": "ok", "language": "en", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short", return_value="yt_abc") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(5)

    # Only 2 clips uploaded (the two PASS clips, ranks 2 and 3), 4 clip rows inserted total.
    assert up.call_count == 2
    inserted = [f for t, op, f in recorder if t == "shorts_clips" and op == "insert"]
    assert len(inserted) == 4
    pending = [f for f in inserted if f["upload_status"] == "PENDING"]
    uploading = [f for f in inserted if f["upload_status"] == "UPLOADING"]
    assert len(pending) == 2 and len(uploading) == 2
    # The uploaded clips are the PASS ones (ranks 2 and 3).
    assert {f["rank"] for f in uploading} == {2, 3}


def test_run_shorts_job_no_cap_uploads_all(tmp_path):
    recorder = []
    job = {"id": 6, "channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ",
           "cut_mode": "highlights", "camera_motion": "calm", "upload_cap": None, "status": "CREATED"}
    clips = [
        {"path": str(tmp_path / "d1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0, "verdict": "CHECK"},
        {"path": str(tmp_path / "d2.mp4"), "rank": 2, "start_s": 10.0, "end_s": 20.0, "verdict": "PASS"},
    ]
    for c in clips:
        Path(c["path"]).write_bytes(b"clip")
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(job, recorder)), \
         patch("app.shorts.runner._fetch_video", return_value=(tmp_path / "src.mkv", "My_Video")), \
         patch("app.shorts.runner._cut_video", return_value={"clips": clips, "message": "ok", "language": "en", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short", return_value="yt_abc") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(6)

    assert up.call_count == 2  # all clips uploaded
```
Note: confirm the existing `_fake_sb` in this file records `("shorts_clips", "insert", fields)` tuples and returns a row with an `id`; the existing `test_run_shorts_job_happy_path` already relies on that, so reuse it as-is.

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/shorts/test_runner.py -q
```
Expected: FAIL (the current runner uploads every clip, ignoring `upload_cap`).

- [ ] **Step 3: Rewrite the clip loop in `run_shorts_job`**

Replace the clip-upload block (from `clips = result["clips"]` through the end of the `for clip in clips:` loop) with cap-aware logic:

```python
        clips = result["clips"]
        cap = job.get("upload_cap")
        # PASS-graded clips first, then by rank. With a cap, upload only the first N; hold the rest.
        ordered = sorted(clips, key=lambda c: (0 if c.get("verdict") == "PASS" else 1, c["rank"]))
        hold_ranks = set() if cap is None else {c["rank"] for c in ordered[cap:]}

        n_upload = len(clips) - len(hold_ranks)
        _set_job(job_id, status="UPLOADING", progress=95,
                 progress_label=f"uploading {n_upload} of {len(clips)} clips to YouTube")
        all_ok = True
        for clip in ordered:
            clip_title = f"{title.replace('_', ' ')} — Part {clip['rank']}"[:100]
            held = clip["rank"] in hold_ranks
            row = sb.table("shorts_clips").insert({
                "job_id": job_id, "rank": clip["rank"], "title": clip_title,
                "description": "", "hashtags": ["shorts"],
                "start_s": clip["start_s"], "end_s": clip["end_s"],
                "local_path": clip["path"],
                "upload_status": "PENDING" if held else "UPLOADING",
            }).execute().data[0]
            if held:
                continue
            try:
                video_id = upload_short(job["channel_id"], clip["path"],
                                        clip_title, "", ["shorts"])
                sb.table("shorts_clips").update(
                    {"upload_status": "UPLOADED", "yt_video_id": video_id}
                ).eq("id", row["id"]).execute()
            except Exception as exc:
                all_ok = False
                log.exception("Job %s: upload failed for clip rank=%s", job_id, clip["rank"])
                sb.table("shorts_clips").update(
                    {"upload_status": "FAILED",
                     "upload_error": f"{type(exc).__name__}: {exc}"[:1000]}
                ).eq("id", row["id"]).execute()

        held_note = f" ({len(hold_ranks)} held for review)" if hold_ranks else ""
        _set_job(job_id, status="DONE" if all_ok else "FAILED", progress=100,
                 progress_label="done",
                 error_message=None if all_ok else "One or more clips failed to upload")
        _notify_macos("Midas Shorts",
                      f"Job {job_id}: {len(clips)} clips cut, "
                      f"{n_upload} uploaded{held_note}"
                      + ("" if all_ok else " — some uploads FAILED"))
```
(Held clips are `PENDING` with a `local_path` still on disk in `shorts_cache/<job>/clips/`; Task 4's per-clip endpoint uploads them later. `all_ok` reflects only attempted uploads, so a job that holds clips still finishes `DONE`.)

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/shorts/test_runner.py -q && venv/bin/pytest tests/ -q
```
Expected: PASS (the new cap tests plus the pre-existing runner tests).

- [ ] **Step 5: Commit**

```bash
git add app/shorts/runner.py tests/shorts/test_runner.py
git commit -m "feat: runner honors upload_cap — top-N upload, hold the rest as PENDING"
```

---

### Task 4: Endpoints — `POST /videos/{id}/short` and `POST /shorts/clips/{id}/upload`

**Files:**
- Modify: `app/shorts/routes.py` (add a no-prefix `video_router` + the per-clip upload endpoint on the existing `router`)
- Modify: `app/main.py` (include `video_router`)
- Test: `tests/shorts/test_video_short_routes.py`

**Interfaces:**
- Consumes: `has_active_job`, `start_job_thread` (from `app.shorts.runner`); `upload_short` (from `app.shorts.youtube_upload`).
- Produces: `POST /videos/{video_id}/short` → `{"job_id": int}` (404 unknown video, 409 busy); `POST /shorts/clips/{clip_id}/upload` → `{"clip_id": int, "yt_video_id": str}` (404 unknown clip, 409 if not PENDING).

- [ ] **Step 1: Write the failing tests** — `tests/shorts/test_video_short_routes.py`:

```python
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _sb_video(found=True, channel="UC123"):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        {"id": "vid123", "channel_id": channel} if found else None)
    tbl.insert.return_value.execute.return_value.data = [{"id": 42}]
    return sb


def test_make_short_creates_job():
    with patch("app.shorts.routes.supabase", return_value=_sb_video()), \
         patch("app.shorts.routes.has_active_job", return_value=False), \
         patch("app.shorts.routes.start_job_thread") as start:
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 200 and r.json() == {"job_id": 42}
    start.assert_called_once_with(42)


def test_make_short_unknown_video_404():
    with patch("app.shorts.routes.supabase", return_value=_sb_video(found=False)):
        r = _client().post("/videos/nope/short")
    assert r.status_code == 404


def test_make_short_conflicts_when_busy():
    with patch("app.shorts.routes.supabase", return_value=_sb_video()), \
         patch("app.shorts.routes.has_active_job", return_value=True):
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409


def _sb_clip(status="PENDING"):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        {"id": 7, "job_id": 5, "local_path": "/tmp/c.mp4", "title": "t",
         "upload_status": status} if status else None)
    # the job lookup for channel_id
    return sb


def test_upload_clip_uploads_pending():
    sb = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "shorts_clips":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": 7, "job_id": 5, "local_path": "/tmp/c.mp4", "title": "t", "upload_status": "PENDING"}
        if name == "shorts_jobs":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": 5, "channel_id": "UC123"}
        t.update.return_value.eq.return_value.execute.return_value.data = [{}]
        return t
    sb.table.side_effect = table
    with patch("app.shorts.routes.supabase", return_value=sb), \
         patch("app.shorts.routes.upload_short", return_value="yt_xyz") as up:
        r = _client().post("/shorts/clips/7/upload")
    assert r.status_code == 200 and r.json()["yt_video_id"] == "yt_xyz"
    up.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/shorts/test_video_short_routes.py -q
```
Expected: FAIL (routes/import not present).

- [ ] **Step 3: Add the endpoints to `app/shorts/routes.py`**

At the top, extend the imports:

```python
from app.shorts.youtube_upload import upload_short
```

Then add a second router (no `/shorts` prefix) and the two endpoints (append to the file):

```python
# Video-scoped shorts endpoint. No /shorts prefix so it sits next to /videos/{id}/audit.
video_router = APIRouter(tags=["shorts"])


class MakeShort(BaseModel):
    cut_mode: str = "highlights"        # highlights | coverage
    camera_motion: str = "calm"         # locked | calm | follow


@video_router.post("/videos/{video_id}/short")
def make_short(video_id: str, body: MakeShort | None = None):
    body = body or MakeShort()
    sb = supabase()
    video = sb.table("videos").select("id,channel_id").eq("id", video_id).single().execute().data
    if not video:
        raise HTTPException(404, f"Video {video_id} not found")
    if has_active_job():
        raise HTTPException(409, "A shorts job is already running; wait for it to finish")
    inserted = sb.table("shorts_jobs").insert({
        "channel_id":         video["channel_id"],
        "source_video_id":    video_id,
        "source_url":         f"https://www.youtube.com/watch?v={video_id}",
        "cut_mode":           body.cut_mode,
        "camera_motion":      body.camera_motion,
        "upload_cap":         None,       # manual button uploads all clips
        "autopilot_generated": False,
        "status":             "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]
    start_job_thread(job_id)
    log.info("Shorts job %d created for video %s", job_id, video_id)
    return {"job_id": job_id}


@router.post("/clips/{clip_id}/upload")
def upload_clip(clip_id: int):
    sb = supabase()
    clip = sb.table("shorts_clips").select("*").eq("id", clip_id).single().execute().data
    if not clip:
        raise HTTPException(404, "Clip not found")
    if clip["upload_status"] not in ("PENDING", "FAILED"):
        raise HTTPException(409, f"Clip is {clip['upload_status']}, not uploadable")
    job = sb.table("shorts_jobs").select("channel_id").eq("id", clip["job_id"]).single().execute().data
    if not job:
        raise HTTPException(404, "Parent job not found")
    sb.table("shorts_clips").update({"upload_status": "UPLOADING"}).eq("id", clip_id).execute()
    try:
        video_id = upload_short(job["channel_id"], clip["local_path"],
                                clip.get("title") or "Short", "", ["shorts"])
    except Exception as exc:
        sb.table("shorts_clips").update(
            {"upload_status": "FAILED", "upload_error": f"{type(exc).__name__}: {exc}"[:1000]}
        ).eq("id", clip_id).execute()
        raise HTTPException(502, f"Upload failed: {exc}")
    sb.table("shorts_clips").update(
        {"upload_status": "UPLOADED", "yt_video_id": video_id}
    ).eq("id", clip_id).execute()
    return {"clip_id": clip_id, "yt_video_id": video_id}
```
(`upload_clip` lives on the existing `/shorts`-prefixed `router`, so its path is `/shorts/clips/{id}/upload`. `make_short` lives on `video_router` with no prefix → `/videos/{id}/short`.)

- [ ] **Step 4: Include `video_router` in `app/main.py`**

Find the shorts router include (`app.include_router(shorts_router)`) and add the video router next to it. First read `app/main.py` to get the exact import line for the shorts router, then mirror it:

```python
from app.shorts.routes import router as shorts_router, video_router as shorts_video_router
```
and after `app.include_router(shorts_router)`:
```python
app.include_router(shorts_video_router)
```

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/shorts/test_video_short_routes.py -q && venv/bin/pytest tests/ -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/shorts/routes.py app/main.py tests/shorts/test_video_short_routes.py
git commit -m "feat: POST /videos/{id}/short and POST /shorts/clips/{id}/upload endpoints"
```

---

### Task 5: Video-list enrichment — `is_short` + shorts fields

**Files:**
- Modify: `app/sync.py` (`list_videos`)
- Test: `tests/test_list_videos_shorts.py`

**Interfaces:**
- Produces: each video in `GET /channels/{id}/videos` gains `is_short` (bool), `shorts_status` (str|None — latest `shorts_jobs.status` for that `source_video_id`), `shorts_job_id` (int|None), `clips_count` (int), `clips_uploaded` (int).

- [ ] **Step 1: Write the failing test** — `tests/test_list_videos_shorts.py`:

```python
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def test_list_videos_includes_shorts_fields():
    videos = [{"id": "v1", "channel_id": "UC1", "title": "Long one", "is_short": False,
               "published_at": "2026-07-01T00:00:00Z", "view_count": 100},
              {"id": "v2", "channel_id": "UC1", "title": "A short", "is_short": True,
               "published_at": "2026-07-02T00:00:00Z", "view_count": 5}]
    jobs = [{"id": 9, "source_video_id": "v1", "status": "DONE", "created_at": "2026-07-03T00:00:00Z"}]
    clips = [{"job_id": 9, "upload_status": "UPLOADED"}, {"job_id": 9, "upload_status": "PENDING"}]

    sb = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "videos":
            t.select.return_value.eq.return_value.order.return_value.execute.return_value.data = videos
        if name == "audits":
            t.select.return_value.in_.return_value.order.return_value.execute.return_value.data = []
        if name == "shorts_jobs":
            t.select.return_value.in_.return_value.order.return_value.execute.return_value.data = jobs
        if name == "shorts_clips":
            t.select.return_value.in_.return_value.execute.return_value.data = clips
        return t
    sb.table.side_effect = table

    with patch("app.sync.supabase", return_value=sb):
        r = _client().get("/channels/UC1/videos")
    data = r.json()
    v1 = next(v for v in data if v["id"] == "v1")
    v2 = next(v for v in data if v["id"] == "v2")
    assert v1["is_short"] is False and v2["is_short"] is True
    assert v1["shorts_status"] == "DONE" and v1["shorts_job_id"] == 9
    assert v1["clips_count"] == 2 and v1["clips_uploaded"] == 1
    assert v2["shorts_status"] is None and v2["clips_count"] == 0
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/test_list_videos_shorts.py -q
```
Expected: FAIL (fields absent; `is_short` not selected; shorts tables not queried).

- [ ] **Step 3: Add `is_short` to the select and enrich with shorts data**

In `app/sync.py::list_videos`, add `is_short` to the `.select(...)` column string:

```python
        .select("id,title,description,tags,view_count,like_count,comment_count,"
                "published_at,thumbnail_url,privacy_status,last_fetched_at,is_short")
```

Then, after the existing audit-enrichment loop (right before `return videos`), add shorts enrichment:

```python
    # Shorts enrichment: latest shorts_jobs row per source_video_id + clip counts.
    jobs = (
        supabase().table("shorts_jobs")
        .select("id,source_video_id,status,created_at")
        .in_("source_video_id", video_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    latest_job: dict[str, dict] = {}
    for j in jobs:
        svid = j.get("source_video_id")
        if svid and svid not in latest_job:
            latest_job[svid] = j
    job_ids = [j["id"] for j in latest_job.values()]
    clip_rows = []
    if job_ids:
        clip_rows = (
            supabase().table("shorts_clips")
            .select("job_id,upload_status")
            .in_("job_id", job_ids)
            .execute()
        ).data or []
    clips_by_job: dict[int, list] = {}
    for c in clip_rows:
        clips_by_job.setdefault(c["job_id"], []).append(c)
    for v in videos:
        j = latest_job.get(v["id"])
        v["shorts_status"] = j["status"] if j else None
        v["shorts_job_id"] = j["id"] if j else None
        job_clips = clips_by_job.get(j["id"], []) if j else []
        v["clips_count"] = len(job_clips)
        v["clips_uploaded"] = sum(1 for c in job_clips if c["upload_status"] == "UPLOADED")
```
(`video_ids` is already defined earlier in the function for the audit query — reuse it.)

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/test_list_videos_shorts.py -q && venv/bin/pytest tests/ -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/sync.py tests/test_list_videos_shorts.py
git commit -m "feat: enrich /channels/{id}/videos with is_short + shorts status/clip counts"
```

---

### Task 6: `channel.html` — "Make shorts" button, status pill, detail cell, per-clip upload

**Files:**
- Modify: `app/static/channel.html`

**Interfaces:**
- Consumes: `POST /videos/{id}/short`, `GET /shorts/jobs/{job_id}`, `POST /shorts/clips/{id}/upload`; the per-video fields `is_short`, `shorts_status`, `shorts_job_id`, `clips_count`, `clips_uploaded`.

- [ ] **Step 1: Read the current file** to confirm the exact anchors (the video-row template around the `row-${v.id}` / `audit-${v.id}` rows, the `STATE_META` object, `statusPill`, `escapeHtml`, `toast`, `$`). Do not guess line numbers — match the live text.

- [ ] **Step 2: Add shorts states to `STATE_META`**

Extend the `STATE_META` object (used by `statusPill`) with the shorts job statuses so the shorts pill renders with colors:

```javascript
  // shorts job statuses
  CREATED:     { bg:'#28a', label:'Queued' },
  DOWNLOADING: { bg:'#28a', label:'Downloading' },
  ANALYSING:   { bg:'#28a', label:'Analysing' },
  RENDERING:   { bg:'#28a', label:'Rendering' },
  UPLOADING:   { bg:'#28a', label:'Uploading' },
  DONE:        { bg:'#2a7', label:'Shorts done' },
```
(`FAILED` already exists in `STATE_META` and is reused.)

- [ ] **Step 3: Add a `shortsButton(v)` helper** near `auditButton(v)`:

```javascript
function shortsButton(v) {
  if (v.is_short) return '';                 // don't cut shorts into shorts
  const label = v.shorts_job_id ? 'Re-cut shorts' : 'Make shorts';
  return `<button onclick="makeShort('${v.id}')">${label}</button>`;
}
```

- [ ] **Step 4: Render the button + a shorts pill in the video row.** In the row template, add the shorts pill next to the audit pill cell and the button next to the audit button. Concretely, in the `<td>${auditButton(v)}</td>` area, change it to include both buttons:

```javascript
      <td>${auditButton(v)} ${shortsButton(v)}</td>
```
And add a shorts-status pill cell after the audit pill cell (a video with `shorts_job_id` links to expand the shorts detail):

```javascript
      <td>${v.shorts_job_id
            ? `<a href="#" onclick="viewShort('${v.id}', ${v.shorts_job_id}); return false;" style="text-decoration:none;color:inherit" title="View shorts">${statusPill(v.shorts_status)}${v.clips_count ? ` <span class="muted">(${v.clips_uploaded}/${v.clips_count})</span>` : ''}</a>`
            : (v.is_short ? '<span class="muted">—</span>' : statusPill(null))}</td>
```
Because this adds one `<td>`, bump the detail row's `colspan` from `11` to `12` (the `<tr id="audit-${v.id}"><td colspan="11">` line) and add a second detail row for shorts:

```javascript
    <tr id="shorts-${v.id}"><td colspan="12" style="border:none; padding:0"></td></tr>
```
(Also update the `<thead>` to add a "Shorts" column header so the column count matches — read the header row and add one `<th>Shorts</th>` next to the audit status header.)

- [ ] **Step 5: Add the `makeShort`, `viewShort`, `pollShort`, and `uploadClip` handlers** (mirror the `audit()` pattern):

```javascript
async function makeShort(videoId) {
  const cell = $('shorts-' + videoId).firstChild;
  cell.innerHTML = '<div class="audit muted">Starting shorts job…</div>';
  try {
    const r = await fetch(`/videos/${videoId}/short`, { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    const { job_id } = await r.json();
    pollShort(videoId, job_id);
  } catch (e) {
    cell.innerHTML = `<div class="audit" style="border-color:#c33;color:#c33">Could not start: ${escapeHtml(String(e))}</div>`;
    toast('Make shorts failed: ' + escapeHtml(String(e)), 'err');
  }
}

function viewShort(videoId, jobId) { pollShort(videoId, jobId); }

async function pollShort(videoId, jobId) {
  const cell = $('shorts-' + videoId).firstChild;
  const WORKING = ['CREATED','DOWNLOADING','ANALYSING','RENDERING','UPLOADING'];
  try {
    const r = await fetch(`/shorts/jobs/${jobId}`);
    if (!r.ok) throw new Error(await r.text());
    const { job, clips } = await r.json();
    cell.innerHTML = renderShort(job, clips);
    if (WORKING.includes(job.status)) setTimeout(() => pollShort(videoId, jobId), 2000);
  } catch (e) {
    cell.innerHTML = `<div class="audit" style="border-color:#c33;color:#c33">${escapeHtml(String(e))}</div>`;
  }
}

function renderShort(job, clips) {
  const WORKING = ['CREATED','DOWNLOADING','ANALYSING','RENDERING','UPLOADING'];
  const bar = WORKING.includes(job.status)
    ? `<div class="prog"><div class="prog-bar" style="width:${Math.max(0,Math.min(100,job.progress||0))}%"></div></div><small>${escapeHtml(job.progress_label||job.status)} ${job.progress||0}%</small>`
    : statusPill(job.status);
  const rows = (clips||[]).map(c => `<li>
      <b>#${c.rank}</b> ${escapeHtml((c.start_s|0)+'s–'+(c.end_s|0)+'s')} · ${statusPill(c.upload_status)}
      ${c.upload_status === 'UPLOADED' && c.yt_video_id ? ` · <a href="https://youtube.com/watch?v=${c.yt_video_id}" target="_blank">view</a>` : ''}
      ${(c.upload_status === 'PENDING' || c.upload_status === 'FAILED') ? ` <button onclick="uploadClip(${c.id}, this)">Upload</button>` : ''}
    </li>`).join('');
  return `<div class="audit">${bar}${rows ? `<ul>${rows}</ul>` : ''}</div>`;
}

async function uploadClip(clipId, btn) {
  btn.disabled = true; btn.textContent = 'Uploading…';
  try {
    const r = await fetch(`/shorts/clips/${clipId}/upload`, { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    toast('Clip uploaded as private.', 'ok');
    btn.textContent = 'Uploaded'; 
  } catch (e) {
    btn.disabled = false; btn.textContent = 'Upload';
    toast('Upload failed: ' + escapeHtml(String(e)), 'err');
  }
}
```
Note: `renderShort` reuses the `.prog`/`.prog-bar` CSS from `shorts.html`. Add those two CSS rules to `channel.html`'s `<style>` block if not present (read the block first; match the page's palette):
```css
.prog { width: 160px; height: 6px; background: #8882; border-radius: 3px; overflow: hidden; margin-bottom: 3px; }
.prog-bar { height: 100%; background: #6af; transition: width .5s; }
```

- [ ] **Step 6: Manual serve-check**

```bash
cd ~/Documents/Github/Midas
venv/bin/uvicorn app.main:app --port 8127 >/tmp/b1.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "%{http_code}\n" localhost:8127/channel   # expect 200
curl -s localhost:8127/channel | grep -c "makeShort\|shortsButton\|prog-bar"   # expect >=3
kill %1 2>/dev/null
venv/bin/pytest tests/ -q   # confirm suite still green
```
Then, if the app has a running channel, open `http://localhost:8127/channel?channel_id=UC...` in a browser and confirm: long-form rows show a "Make shorts" button, shorts rows do not, no console errors. (A real cut is exercised in Step 8.)

- [ ] **Step 7: Commit**

```bash
git add app/static/channel.html
git commit -m "feat: per-video Make-shorts button with progress + per-clip upload on channel dashboard"
```

- [ ] **Step 8: Real end-to-end check (manual, on the Mac)**

Start the server, open the channel dashboard for a connected channel, click "Make shorts" on a **long-form** video, and confirm: the detail cell shows the progress bar walking DOWNLOADING→…→DONE, clips list with per-clip UPLOADED status (all clips, since the manual button uploads all), a second click on a `PENDING`/`FAILED` clip's Upload button uploads it, and a second "Make shorts" while a job runs shows a 409 error toast. This mirrors the base `/shorts` E2E that already passed, now through the dashboard button.
