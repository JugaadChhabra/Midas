# Shorts Automation Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a YouTube video URL (chosen by the user from a synced channel), generate sequential shorts via the WayinVideo API and upload each one back to that YouTube channel as a private video.

**Architecture:** New `app/shorts/` module. Job submission writes a `shorts_jobs` row and schedules an APScheduler one-off poll loop (the existing scheduler in `app/main.py`). On WayinVideo `SUCCEEDED`, the pipeline iterates ranked clips: stream WayinVideo's mp4 URL straight into a YouTube resumable upload; if that upload fails, download the mp4 to local cache and retry from disk. Each clip row tracks its own upload status and YT video id. Dashboard page lets the user paste/pick a video and watch job + per-clip status.

**Tech Stack:** FastAPI, Supabase (Postgres), APScheduler (already present), httpx, google-api-python-client (already present, resumable upload via `MediaIoBaseUpload` with `chunksize` and `resumable=True`).

## Global Constraints

- Python file paths under `app/shorts/` — follow existing module style (snake_case files, one router per module).
- Privacy of uploaded shorts: hardcoded `privacyStatus="private"` for the prototype. No flag, no config knob.
- Single WayinVideo API version: header `x-wayinvideo-api-version: v2` on every request.
- Base URL configurable but defaults to `https://wayinvideo-api.wayin.ai/api/v2`.
- No webhooks in this prototype — poll only.
- Reuse existing `youtube_for_channel(channel_id)` from `app/youtube_client.py` for credentials; no new OAuth scope (existing `https://www.googleapis.com/auth/youtube` covers `videos.insert`).
- Reuse existing per-thread Supabase client via `app.db.supabase()`.
- All new code goes under `app/shorts/` and `tests/shorts/`. Migration files use the existing `supabase/migrations/YYYYMMDDHHMMSS_<name>.sql` convention.
- Tests use `pytest` with `unittest.mock` (matches existing `tests/test_reflection.py` style). No real network in tests.

---

## File Structure

**Create:**
- `supabase/migrations/20260617120000_shorts_tables.sql` — `shorts_jobs`, `shorts_clips`
- `app/shorts/__init__.py` — empty
- `app/shorts/wayin_client.py` — thin client for the WayinVideo REST API
- `app/shorts/youtube_upload.py` — resumable YouTube upload helper
- `app/shorts/pipeline.py` — per-job processing (stream → upload, with local-fallback)
- `app/shorts/poller.py` — APScheduler-backed status polling
- `app/shorts/routes.py` — FastAPI router (`POST /shorts/jobs`, `GET /shorts/jobs/{id}`, `GET /shorts/jobs`)
- `app/static/shorts.html` — minimal dashboard page
- `tests/shorts/__init__.py` — empty
- `tests/shorts/test_wayin_client.py`
- `tests/shorts/test_youtube_upload.py`
- `tests/shorts/test_pipeline.py`

**Modify:**
- `app/config.py` — add `WAYINVIDEO_API_KEY`, `WAYINVIDEO_BASE_URL`, `SHORTS_CACHE_DIR`
- `app/main.py` — register `shorts_router`, expose `scheduler` for poller access
- `app/static/index.html` — add nav link to `/static/shorts.html` (a single `<a>`)

---

## Task 1: Database migration for `shorts_jobs` and `shorts_clips`

**Files:**
- Create: `supabase/migrations/20260617120000_shorts_tables.sql`

**Interfaces:**
- Consumes: existing `channels(id text primary key)` and `videos(id text primary key)` tables.
- Produces: two tables consumed by every later task.
  - `shorts_jobs(id bigserial pk, channel_id text fk→channels(id), source_video_id text nullable, source_url text not null, wayinvideo_project_id text, status text default 'CREATED', error_message text, created_at timestamptz default now(), updated_at timestamptz default now())`
  - `shorts_clips(id bigserial pk, job_id bigint fk→shorts_jobs(id) on delete cascade, rank int not null, title text, description text, hashtags text[], start_s float, end_s float, source_url text, yt_video_id text, upload_status text default 'PENDING', upload_error text, local_path text, created_at timestamptz default now(), updated_at timestamptz default now(), unique(job_id, rank))`

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260617120000_shorts_tables.sql`:

```sql
-- Shorts automation prototype (docs/superpowers/plans/2026-06-17-shorts-prototype.md).
-- Job rows track a single "clip this YouTube video" request submitted to the
-- WayinVideo API. Clip rows track individual generated shorts and their
-- per-upload state on YouTube.

create table if not exists shorts_jobs (
    id                      bigserial primary key,
    channel_id              text        not null references channels(id),
    source_video_id         text,
    source_url              text        not null,
    wayinvideo_project_id   text,
    -- WayinVideo lifecycle: CREATED → QUEUED → ONGOING → SUCCEEDED / FAILED.
    -- We add UPLOADING and DONE for the post-WayinVideo phase.
    status                  text        not null default 'CREATED',
    error_message           text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);
create index if not exists shorts_jobs_channel_idx on shorts_jobs(channel_id);
create index if not exists shorts_jobs_status_idx  on shorts_jobs(status);

create table if not exists shorts_clips (
    id              bigserial primary key,
    job_id          bigint      not null references shorts_jobs(id) on delete cascade,
    rank            int         not null,
    title           text,
    description     text,
    hashtags        text[],
    start_s         float,
    end_s           float,
    -- WayinVideo-hosted mp4 URL returned when export is enabled.
    source_url      text,
    yt_video_id     text,
    -- PENDING → UPLOADING → UPLOADED / FAILED.
    upload_status   text        not null default 'PENDING',
    upload_error    text,
    -- Set only when streaming upload failed and we cached the file on disk.
    local_path      text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (job_id, rank)
);
create index if not exists shorts_clips_job_idx on shorts_clips(job_id);
```

- [ ] **Step 2: Apply the migration**

Run: `supabase db push` (or whatever the local convention is — check existing migration runbook in repo README if unsure).

Expected: `supabase` reports the migration applied. Verify in Supabase Studio that `shorts_jobs` and `shorts_clips` exist with the columns listed above.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260617120000_shorts_tables.sql
git commit -m "feat(shorts): add shorts_jobs and shorts_clips tables"
```

---

## Task 2: Config additions

**Files:**
- Modify: `app/config.py` (add three settings inside the `class Settings` block, near other `os.getenv` lines around line 36)

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.WAYINVIDEO_API_KEY: str`, `settings.WAYINVIDEO_BASE_URL: str` (default `https://wayinvideo-api.wayin.ai/api/v2`), `settings.SHORTS_CACHE_DIR: str` (default `./shorts_cache`).

- [ ] **Step 1: Add the settings**

In `app/config.py`, inside `class Settings`, after the line `AUTOPILOT_TICK_SECONDS = int(os.getenv("AUTOPILOT_TICK_SECONDS") or "120")`, append:

```python
    # WayinVideo (https://wayinvideo-api.wayin.ai) — shorts automation prototype.
    WAYINVIDEO_API_KEY  = os.getenv("WAYINVIDEO_API_KEY", "")
    WAYINVIDEO_BASE_URL = os.getenv("WAYINVIDEO_BASE_URL", "https://wayinvideo-api.wayin.ai/api/v2")
    # Local disk cache used only as fallback when streaming upload to YouTube fails.
    SHORTS_CACHE_DIR    = os.getenv("SHORTS_CACHE_DIR", "./shorts_cache")
```

- [ ] **Step 2: Commit**

```bash
git add app/config.py
git commit -m "feat(shorts): add WayinVideo and cache settings"
```

---

## Task 3: WayinVideo client

**Files:**
- Create: `app/shorts/__init__.py` (empty)
- Create: `app/shorts/wayin_client.py`
- Create: `tests/shorts/__init__.py` (empty)
- Create: `tests/shorts/test_wayin_client.py`

**Interfaces:**
- Consumes: `settings.WAYINVIDEO_API_KEY`, `settings.WAYINVIDEO_BASE_URL`.
- Produces:
  - `submit_clipping(video_url: str) -> str` — returns `project_id`. Raises `WayinVideoError` on non-200.
  - `get_status(project_id: str) -> dict` — returns the `data` payload (always contains `status`; on `SUCCEEDED` includes a `clips` list; on `FAILED` includes `error_message`).
  - `class WayinVideoError(RuntimeError)` — raised on HTTP errors.

> Note for implementer: WayinVideo's public docs (March 2026) describe the lifecycle and `data` envelope but don't pin the exact JSON shape of clipping responses. Treat clip dicts as opaque and pass them through; later tasks only read `title`, `description`, `hashtags`, `start_s`/`end_s`, and a clip video URL. When the real API returns different field names, update the *clip normalization* step in Task 5, not this client.

- [ ] **Step 1: Write the failing tests**

Create `tests/shorts/__init__.py` as an empty file.

Create `tests/shorts/test_wayin_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def _mock_response(status_code: int, json_body: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


def test_submit_clipping_returns_project_id():
    with patch("app.shorts.wayin_client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"data": {"project_id": "prj_abc"}})
        from app.shorts.wayin_client import submit_clipping
        pid = submit_clipping("https://www.youtube.com/watch?v=xyz")
    assert pid == "prj_abc"
    args, kwargs = mock_post.call_args
    assert "/clipping" in args[0] or "/clipping" in kwargs.get("url", "")
    assert kwargs["headers"]["Authorization"].startswith("Bearer ")
    assert kwargs["headers"]["x-wayinvideo-api-version"] == "v2"
    assert kwargs["json"]["video_url"] == "https://www.youtube.com/watch?v=xyz"
    assert kwargs["json"]["export"] is True


def test_submit_clipping_raises_on_http_error():
    with patch("app.shorts.wayin_client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(429, {"error": "rate limited"})
        from app.shorts.wayin_client import submit_clipping, WayinVideoError
        with pytest.raises(WayinVideoError, match="429"):
            submit_clipping("https://www.youtube.com/watch?v=xyz")


def test_get_status_returns_data_payload():
    with patch("app.shorts.wayin_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {
            "data": {"project_id": "prj_abc", "status": "ONGOING"}
        })
        from app.shorts.wayin_client import get_status
        data = get_status("prj_abc")
    assert data["status"] == "ONGOING"
    args, kwargs = mock_get.call_args
    assert "prj_abc" in args[0] or "prj_abc" in kwargs.get("url", "")


def test_get_status_raises_on_http_error():
    with patch("app.shorts.wayin_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(500, {"error": "boom"})
        from app.shorts.wayin_client import get_status, WayinVideoError
        with pytest.raises(WayinVideoError, match="500"):
            get_status("prj_abc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/shorts/test_wayin_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.shorts.wayin_client'`.

- [ ] **Step 3: Write the implementation**

Create `app/shorts/__init__.py` as an empty file.

Create `app/shorts/wayin_client.py`:

```python
import logging
import httpx

from app.config import settings

log = logging.getLogger("midas.shorts.wayin")


class WayinVideoError(RuntimeError):
    """Non-2xx response from the WayinVideo API."""


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.WAYINVIDEO_API_KEY}",
        "x-wayinvideo-api-version": "v2",
    }


def submit_clipping(video_url: str) -> str:
    """Submit an AI Clipping job. Returns project_id."""
    url = f"{settings.WAYINVIDEO_BASE_URL}/clipping"
    resp = httpx.post(
        url,
        headers=_headers(),
        json={"video_url": video_url, "export": True},
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise WayinVideoError(f"WayinVideo submit failed {resp.status_code}: {resp.text}")
    return resp.json()["data"]["project_id"]


def get_status(project_id: str) -> dict:
    """Poll a project. Returns the `data` payload (includes status, clips, error_message)."""
    url = f"{settings.WAYINVIDEO_BASE_URL}/clipping/{project_id}"
    resp = httpx.get(url, headers=_headers(), timeout=30.0)
    if resp.status_code != 200:
        raise WayinVideoError(f"WayinVideo status failed {resp.status_code}: {resp.text}")
    return resp.json()["data"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/shorts/test_wayin_client.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/__init__.py app/shorts/wayin_client.py tests/shorts/__init__.py tests/shorts/test_wayin_client.py
git commit -m "feat(shorts): WayinVideo API client"
```

---

## Task 4: YouTube upload helper

**Files:**
- Create: `app/shorts/youtube_upload.py`
- Create: `tests/shorts/test_youtube_upload.py`

**Interfaces:**
- Consumes: `youtube_for_channel(channel_id)` from `app.youtube_client`.
- Produces:
  - `upload_short(channel_id: str, source: BinaryIO | str, title: str, description: str, tags: list[str]) -> str` — `source` is either a path string OR a readable binary file-like (used for the streaming case). Returns the new `yt_video_id`. Raises whatever `googleapiclient.errors.HttpError` raises on failure (caller decides what to do).
  - `class YouTubeUploadError(RuntimeError)` — raised on non-retryable errors after the resumable upload loop gives up.

- [ ] **Step 1: Write the failing tests**

Create `tests/shorts/test_youtube_upload.py`:

```python
import io
from unittest.mock import patch, MagicMock


def _fake_youtube_insert(returned_video_id: str = "vid_new"):
    """Build a fake youtube object whose .videos().insert().next_chunk() loop returns vid id."""
    fake_yt = MagicMock()
    insert_req = MagicMock()
    # next_chunk returns (status, response) per googleapiclient resumable loop.
    insert_req.next_chunk.side_effect = [
        (None, None),
        (None, {"id": returned_video_id}),
    ]
    fake_yt.videos.return_value.insert.return_value = insert_req
    return fake_yt, insert_req


def test_upload_short_from_file_path_returns_video_id(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fakebytes")
    fake_yt, _ = _fake_youtube_insert("vid_xyz")
    with patch("app.shorts.youtube_upload.youtube_for_channel", return_value=fake_yt):
        from app.shorts.youtube_upload import upload_short
        vid = upload_short("UC_chan", str(src), "Title", "Desc", ["#tag"])
    assert vid == "vid_xyz"


def test_upload_short_from_stream_returns_video_id():
    stream = io.BytesIO(b"fakebytes")
    fake_yt, _ = _fake_youtube_insert("vid_stream")
    with patch("app.shorts.youtube_upload.youtube_for_channel", return_value=fake_yt):
        from app.shorts.youtube_upload import upload_short
        vid = upload_short("UC_chan", stream, "T", "D", [])
    assert vid == "vid_stream"


def test_upload_short_sets_private_visibility(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fakebytes")
    fake_yt, insert_req = _fake_youtube_insert()
    with patch("app.shorts.youtube_upload.youtube_for_channel", return_value=fake_yt):
        from app.shorts.youtube_upload import upload_short
        upload_short("UC_chan", str(src), "T", "D", [])
    insert_kwargs = fake_yt.videos.return_value.insert.call_args.kwargs
    body = insert_kwargs["body"]
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["snippet"]["title"] == "T"
    assert "snippet,status" == insert_kwargs["part"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/shorts/test_youtube_upload.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.shorts.youtube_upload'`.

- [ ] **Step 3: Write the implementation**

Create `app/shorts/youtube_upload.py`:

```python
import io
import logging
from typing import BinaryIO

from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from app.youtube_client import youtube_for_channel

log = logging.getLogger("midas.shorts.upload")

# 8 MB chunks: a balance between memory and round-trip count for resumable upload.
_CHUNK_SIZE = 8 * 1024 * 1024


class YouTubeUploadError(RuntimeError):
    """Raised when the resumable upload loop terminates without a video id."""


def upload_short(
    channel_id: str,
    source: BinaryIO | str,
    title: str,
    description: str,
    tags: list[str],
) -> str:
    """Upload one short to YouTube, returns the new yt_video_id.

    `source` is either a filesystem path (str) or a binary file-like object
    opened for reading. Privacy is hardcoded to `private` for the prototype.
    """
    yt = youtube_for_channel(channel_id)

    if isinstance(source, str):
        media = MediaFileUpload(source, mimetype="video/mp4", chunksize=_CHUNK_SIZE, resumable=True)
    else:
        media = MediaIoBaseUpload(source, mimetype="video/mp4", chunksize=_CHUNK_SIZE, resumable=True)

    body = {
        "snippet": {
            "title": title[:100],          # YT title cap
            "description": description or "",
            "tags": tags or [],
            "categoryId": "22",            # People & Blogs
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }

    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload progress: %d%%", int(status.progress() * 100))

    if not response or "id" not in response:
        raise YouTubeUploadError(f"Upload finished without video id: {response!r}")
    return response["id"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/shorts/test_youtube_upload.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/youtube_upload.py tests/shorts/test_youtube_upload.py
git commit -m "feat(shorts): resumable private YouTube upload helper"
```

---

## Task 5: Pipeline — stream-or-fallback per-clip processing

**Files:**
- Create: `app/shorts/pipeline.py`
- Create: `tests/shorts/test_pipeline.py`

**Interfaces:**
- Consumes:
  - `app.shorts.wayin_client.get_status(project_id) -> dict`
  - `app.shorts.youtube_upload.upload_short(channel_id, source, title, description, tags) -> str`
  - `app.db.supabase()`
  - `settings.SHORTS_CACHE_DIR`
- Produces:
  - `normalize_clips(raw_clips: list[dict]) -> list[dict]` — coerces WayinVideo's clip dicts into the shape `{rank, title, description, hashtags, start_s, end_s, source_url}`. Tolerates missing fields and renames common synonyms (`url`/`video_url`/`download_url` → `source_url`, `start`/`start_seconds` → `start_s`, etc.).
  - `process_job_clips(job_id: int) -> None` — reads `shorts_jobs.id = job_id`, fetches each `shorts_clips` row for the job (already inserted by the poller on SUCCEEDED), runs the upload flow per clip, updates rows in place.
  - `_upload_one_clip(channel_id: str, clip_row: dict) -> dict` — internal; returns the patch dict to apply to that clip row (`yt_video_id`, `upload_status`, `upload_error`, `local_path`).

- [ ] **Step 1: Write the failing tests**

Create `tests/shorts/test_pipeline.py`:

```python
import io
import os
from unittest.mock import patch, MagicMock


def test_normalize_clips_renames_synonyms():
    from app.shorts.pipeline import normalize_clips
    raw = [
        {"rank": 1, "title": "A", "description": "d", "hashtags": ["#x"],
         "start": 12.0, "end": 25.5, "url": "https://w/clip1.mp4"},
        {"rank": 2, "title": "B", "video_url": "https://w/clip2.mp4",
         "start_seconds": 30, "end_seconds": 40},
    ]
    norm = normalize_clips(raw)
    assert norm[0]["source_url"] == "https://w/clip1.mp4"
    assert norm[0]["start_s"] == 12.0
    assert norm[0]["end_s"] == 25.5
    assert norm[1]["source_url"] == "https://w/clip2.mp4"
    assert norm[1]["start_s"] == 30
    assert norm[1]["hashtags"] == []  # default empty list when missing


def test_normalize_clips_fills_rank_if_missing():
    from app.shorts.pipeline import normalize_clips
    raw = [{"title": "A", "url": "u1"}, {"title": "B", "url": "u2"}]
    norm = normalize_clips(raw)
    assert [c["rank"] for c in norm] == [1, 2]


def test_upload_one_clip_streams_then_succeeds():
    """Happy path: streaming upload returns a video id, no local file written."""
    clip = {"id": 5, "rank": 1, "title": "T", "description": "D", "hashtags": ["#a"],
            "source_url": "https://w/clip.mp4"}
    fake_stream_resp = MagicMock()
    fake_stream_resp.iter_bytes.return_value = iter([b"abc"])
    fake_stream_resp.raise_for_status = MagicMock()
    fake_stream_ctx = MagicMock()
    fake_stream_ctx.__enter__.return_value = fake_stream_resp
    fake_stream_ctx.__exit__.return_value = False

    with patch("app.shorts.pipeline.httpx.stream", return_value=fake_stream_ctx), \
         patch("app.shorts.pipeline.upload_short", return_value="vid_ok") as up:
        from app.shorts.pipeline import _upload_one_clip
        patch_dict = _upload_one_clip("UC_chan", clip)

    assert patch_dict["yt_video_id"] == "vid_ok"
    assert patch_dict["upload_status"] == "UPLOADED"
    assert patch_dict.get("local_path") is None
    assert up.called


def test_upload_one_clip_falls_back_to_disk_on_stream_failure(tmp_path, monkeypatch):
    """Streaming upload fails → download to disk → retry → record yt_video_id."""
    monkeypatch.setattr("app.shorts.pipeline.settings.SHORTS_CACHE_DIR", str(tmp_path))

    clip = {"id": 7, "rank": 2, "title": "T2", "description": "D",
            "hashtags": [], "source_url": "https://w/clip.mp4"}

    # First stream() call (streaming upload) — its consumer (upload_short) will raise.
    fake_stream_resp = MagicMock()
    fake_stream_resp.iter_bytes.return_value = iter([b"abc"])
    fake_stream_resp.raise_for_status = MagicMock()
    fake_stream_ctx = MagicMock()
    fake_stream_ctx.__enter__.return_value = fake_stream_resp
    fake_stream_ctx.__exit__.return_value = False

    # Second stream() call (download to disk) — succeeds.
    fake_dl_resp = MagicMock()
    fake_dl_resp.iter_bytes.return_value = iter([b"x" * 100])
    fake_dl_resp.raise_for_status = MagicMock()
    fake_dl_ctx = MagicMock()
    fake_dl_ctx.__enter__.return_value = fake_dl_resp
    fake_dl_ctx.__exit__.return_value = False

    upload_calls = []

    def fake_upload(channel_id, source, title, description, tags):
        upload_calls.append(source)
        if len(upload_calls) == 1:
            raise RuntimeError("network glitch")
        return "vid_fallback"

    with patch("app.shorts.pipeline.httpx.stream", side_effect=[fake_stream_ctx, fake_dl_ctx]), \
         patch("app.shorts.pipeline.upload_short", side_effect=fake_upload):
        from app.shorts.pipeline import _upload_one_clip
        patch_dict = _upload_one_clip("UC_chan", clip)

    assert patch_dict["yt_video_id"] == "vid_fallback"
    assert patch_dict["upload_status"] == "UPLOADED"
    assert patch_dict["local_path"] is not None
    assert os.path.exists(patch_dict["local_path"])


def test_upload_one_clip_records_failure_when_disk_retry_also_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("app.shorts.pipeline.settings.SHORTS_CACHE_DIR", str(tmp_path))
    clip = {"id": 9, "rank": 3, "title": "T", "description": "",
            "hashtags": [], "source_url": "https://w/clip.mp4"}

    fake_resp = MagicMock()
    fake_resp.iter_bytes.return_value = iter([b"abc"])
    fake_resp.raise_for_status = MagicMock()
    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value = fake_resp
    fake_ctx.__exit__.return_value = False

    with patch("app.shorts.pipeline.httpx.stream", side_effect=[fake_ctx, fake_ctx]), \
         patch("app.shorts.pipeline.upload_short", side_effect=RuntimeError("boom")):
        from app.shorts.pipeline import _upload_one_clip
        patch_dict = _upload_one_clip("UC_chan", clip)

    assert patch_dict["upload_status"] == "FAILED"
    assert "boom" in patch_dict["upload_error"]
    # The downloaded fallback file should be preserved for manual upload.
    assert patch_dict["local_path"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/shorts/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.shorts.pipeline'`.

- [ ] **Step 3: Write the implementation**

Create `app/shorts/pipeline.py`:

```python
import logging
import os
from typing import Any

import httpx

from app.config import settings
from app.db import supabase
from app.shorts.youtube_upload import upload_short

log = logging.getLogger("midas.shorts.pipeline")

# Synonyms WayinVideo may emit for the same logical field. The first present
# key wins. Adjust here when the real response shape diverges.
_URL_KEYS   = ("source_url", "video_url", "download_url", "url", "mp4_url")
_START_KEYS = ("start_s", "start_seconds", "start", "start_time")
_END_KEYS   = ("end_s",   "end_seconds",   "end",   "end_time")


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def normalize_clips(raw: list[dict]) -> list[dict]:
    """Coerce WayinVideo clip dicts to our internal shape."""
    out: list[dict] = []
    for i, c in enumerate(raw, start=1):
        out.append({
            "rank":        c.get("rank") or i,
            "title":       c.get("title") or "",
            "description": c.get("description") or "",
            "hashtags":    list(c.get("hashtags") or []),
            "start_s":     _first(c, _START_KEYS),
            "end_s":       _first(c, _END_KEYS),
            "source_url":  _first(c, _URL_KEYS),
        })
    return out


def _stream_upload(channel_id: str, clip: dict) -> str:
    """Stream WayinVideo's mp4 directly into a YouTube resumable upload."""
    with httpx.stream("GET", clip["source_url"], timeout=None, follow_redirects=True) as r:
        r.raise_for_status()
        # Wrap the chunk iterator in a file-like object that .read() can consume.
        reader = _IterReader(r.iter_bytes())
        return upload_short(channel_id, reader, clip["title"], clip["description"], clip["hashtags"])


def _download_then_upload(channel_id: str, clip: dict) -> tuple[str, str]:
    """Download to SHORTS_CACHE_DIR/<job_id>/<rank>.mp4, then upload from disk."""
    cache_dir = os.path.join(settings.SHORTS_CACHE_DIR, str(clip.get("job_id", "_")))
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, f"{clip['rank']}.mp4")
    with httpx.stream("GET", clip["source_url"], timeout=None, follow_redirects=True) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    vid = upload_short(channel_id, local_path, clip["title"], clip["description"], clip["hashtags"])
    return vid, local_path


def _upload_one_clip(channel_id: str, clip: dict) -> dict:
    """Try streaming upload first; on failure, download to disk and retry.

    Returns a patch dict for the shorts_clips row. The local_path is preserved
    even on final failure so the operator can manually upload later.
    """
    # 1) Streaming attempt.
    try:
        vid = _stream_upload(channel_id, clip)
        return {"yt_video_id": vid, "upload_status": "UPLOADED", "upload_error": None, "local_path": None}
    except Exception as e:
        log.warning("Streaming upload failed for clip rank=%s: %s — falling back to disk", clip.get("rank"), e)

    # 2) Disk fallback.
    try:
        vid, local_path = _download_then_upload(channel_id, clip)
        return {"yt_video_id": vid, "upload_status": "UPLOADED", "upload_error": None, "local_path": local_path}
    except Exception as e:
        log.error("Disk-fallback upload failed for clip rank=%s: %s", clip.get("rank"), e)
        # Try to surface the local_path even if upload itself blew up.
        local_path = os.path.join(
            settings.SHORTS_CACHE_DIR, str(clip.get("job_id", "_")), f"{clip['rank']}.mp4"
        )
        return {
            "upload_status": "FAILED",
            "upload_error":  f"{type(e).__name__}: {e}"[:1000],
            "local_path":    local_path if os.path.exists(local_path) else None,
        }


def process_job_clips(job_id: int) -> None:
    """Upload every clip on this job, sequentially, in rank order."""
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        log.error("process_job_clips: job %s not found", job_id)
        return
    channel_id = job["channel_id"]

    clips = (
        sb.table("shorts_clips").select("*").eq("job_id", job_id)
        .order("rank").execute().data or []
    )
    sb.table("shorts_jobs").update({"status": "UPLOADING"}).eq("id", job_id).execute()

    for clip in clips:
        sb.table("shorts_clips").update({"upload_status": "UPLOADING"}).eq("id", clip["id"]).execute()
        clip_with_job = {**clip, "job_id": job_id}
        patch_dict = _upload_one_clip(channel_id, clip_with_job)
        sb.table("shorts_clips").update(patch_dict).eq("id", clip["id"]).execute()

    final_clips = sb.table("shorts_clips").select("upload_status").eq("job_id", job_id).execute().data or []
    all_ok = all(c["upload_status"] == "UPLOADED" for c in final_clips)
    sb.table("shorts_jobs").update({
        "status": "DONE" if all_ok else "FAILED",
        "error_message": None if all_ok else "One or more clips failed to upload",
    }).eq("id", job_id).execute()


class _IterReader:
    """Adapt an iterator of bytes chunks to a `.read(n)`-style file-like object.

    googleapiclient's MediaIoBaseUpload calls read(chunksize) repeatedly; this
    buffers iter_bytes() output and serves it out in those chunks.
    """
    def __init__(self, it):
        self._it = it
        self._buf = bytearray()
        self._eof = False

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            # Drain everything.
            while not self._eof:
                self._pull()
            out = bytes(self._buf)
            self._buf.clear()
            return out
        while len(self._buf) < n and not self._eof:
            self._pull()
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _pull(self):
        try:
            self._buf += next(self._it)
        except StopIteration:
            self._eof = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/shorts/test_pipeline.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/pipeline.py tests/shorts/test_pipeline.py
git commit -m "feat(shorts): per-clip stream-or-fallback upload pipeline"
```

---

## Task 6: Poller + FastAPI routes

**Files:**
- Create: `app/shorts/poller.py`
- Create: `app/shorts/routes.py`

**Interfaces:**
- Consumes:
  - `submit_clipping`, `get_status`, `WayinVideoError` from `app.shorts.wayin_client`
  - `normalize_clips`, `process_job_clips` from `app.shorts.pipeline`
  - `supabase()` from `app.db`
  - `scheduler` from `app.main` (imported lazily inside `schedule_poll` to dodge circular import)
- Produces:
  - `poller.poll_job(job_id: int) -> None` — single-tick poll function. Reads job, calls `get_status`, updates row; on `SUCCEEDED`, normalizes & inserts clip rows then calls `process_job_clips`; on still-running, reschedules itself 30s later; on `FAILED`, stores `error_message`.
  - `poller.schedule_poll(job_id: int, delay_seconds: int = 0) -> None` — adds a one-shot APScheduler job.
  - `routes.router` — APIRouter with prefix `/shorts`:
    - `POST /shorts/jobs` body `{"channel_id": str, "source_url": str}` → returns `{"job_id": int}`
    - `GET  /shorts/jobs` → list of recent jobs (latest 50)
    - `GET  /shorts/jobs/{job_id}` → job + its clips

- [ ] **Step 1: Write the poller**

Create `app/shorts/poller.py`:

```python
import logging
from datetime import datetime, timezone, timedelta

from app.db import supabase
from app.shorts.wayin_client import get_status, WayinVideoError
from app.shorts.pipeline import normalize_clips, process_job_clips

log = logging.getLogger("midas.shorts.poller")

_POLL_INTERVAL_SECONDS = 30
# Hard ceiling so a runaway WayinVideo job doesn't keep scheduling forever.
_MAX_AGE_HOURS = 4


def schedule_poll(job_id: int, delay_seconds: int = 0) -> None:
    # Lazy import: app.main imports this module → can't import main at module load.
    from app.main import scheduler
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    scheduler.add_job(
        poll_job,
        "date",
        run_date=run_at,
        args=[job_id],
        id=f"shorts_poll_{job_id}_{int(run_at.timestamp())}",
        misfire_grace_time=120,
    )


def poll_job(job_id: int) -> None:
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        log.error("poll_job: job %s not found", job_id)
        return

    if job["status"] in ("DONE", "FAILED"):
        return

    age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
    if age_hours > _MAX_AGE_HOURS:
        sb.table("shorts_jobs").update({
            "status": "FAILED",
            "error_message": f"Timed out after {_MAX_AGE_HOURS}h",
        }).eq("id", job_id).execute()
        return

    project_id = job.get("wayinvideo_project_id")
    if not project_id:
        log.error("poll_job: job %s has no wayinvideo_project_id", job_id)
        return

    try:
        data = get_status(project_id)
    except WayinVideoError as e:
        log.warning("WayinVideo status error for job %s: %s — retry in %ds", job_id, e, _POLL_INTERVAL_SECONDS)
        schedule_poll(job_id, _POLL_INTERVAL_SECONDS)
        return

    status = data.get("status", "ONGOING")
    sb.table("shorts_jobs").update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", job_id).execute()

    if status in ("CREATED", "QUEUED", "ONGOING"):
        schedule_poll(job_id, _POLL_INTERVAL_SECONDS)
        return

    if status == "FAILED":
        sb.table("shorts_jobs").update({"error_message": data.get("error_message", "unknown")}).eq("id", job_id).execute()
        return

    if status == "SUCCEEDED":
        raw_clips = data.get("clips") or data.get("data", {}).get("clips") or []
        normalized = normalize_clips(raw_clips)
        if not normalized:
            sb.table("shorts_jobs").update({
                "status": "FAILED",
                "error_message": "WayinVideo returned 0 clips",
            }).eq("id", job_id).execute()
            return
        rows = [{"job_id": job_id, **c} for c in normalized]
        sb.table("shorts_clips").upsert(rows, on_conflict="job_id,rank").execute()
        process_job_clips(job_id)
        return

    log.warning("Unknown WayinVideo status %r for job %s", status, job_id)
    schedule_poll(job_id, _POLL_INTERVAL_SECONDS)
```

- [ ] **Step 2: Write the routes**

Create `app/shorts/routes.py`:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import supabase
from app.shorts.wayin_client import submit_clipping, WayinVideoError
from app.shorts.poller import schedule_poll

router = APIRouter(prefix="/shorts", tags=["shorts"])


class CreateJob(BaseModel):
    channel_id: str
    source_url: str


@router.post("/jobs")
def create_job(body: CreateJob):
    sb = supabase()
    chan = sb.table("channels").select("id").eq("id", body.channel_id).single().execute().data
    if not chan:
        raise HTTPException(404, f"Channel {body.channel_id} not found")

    inserted = sb.table("shorts_jobs").insert({
        "channel_id": body.channel_id,
        "source_url": body.source_url,
        "status":     "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]

    try:
        project_id = submit_clipping(body.source_url)
    except WayinVideoError as e:
        sb.table("shorts_jobs").update({
            "status": "FAILED",
            "error_message": str(e)[:1000],
        }).eq("id", job_id).execute()
        raise HTTPException(502, f"WayinVideo rejected the submission: {e}")

    sb.table("shorts_jobs").update({
        "status": "QUEUED",
        "wayinvideo_project_id": project_id,
    }).eq("id", job_id).execute()

    schedule_poll(job_id, delay_seconds=15)
    return {"job_id": job_id, "wayinvideo_project_id": project_id}


@router.get("/jobs")
def list_jobs():
    sb = supabase()
    return sb.table("shorts_jobs").select("*").order("id", desc=True).limit(50).execute().data or []


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        raise HTTPException(404, "Job not found")
    clips = sb.table("shorts_clips").select("*").eq("job_id", job_id).order("rank").execute().data or []
    return {"job": job, "clips": clips}
```

- [ ] **Step 3: Smoke-import the new modules**

Run: `python -c "from app.shorts import poller, routes; print('ok')"`
Expected: prints `ok`. (Confirms there are no import-time syntax errors. Circular import with `app.main.scheduler` is fine because `schedule_poll` imports lazily.)

- [ ] **Step 4: Commit**

```bash
git add app/shorts/poller.py app/shorts/routes.py
git commit -m "feat(shorts): job submission, polling, and HTTP routes"
```

---

## Task 7: Wire router into `app/main.py`

**Files:**
- Modify: `app/main.py` (add import + `app.include_router`)

**Interfaces:**
- Consumes: `app.shorts.routes.router`
- Produces: HTTP endpoints registered on the FastAPI app.

- [ ] **Step 1: Add import**

In `app/main.py`, find the block of `from app.<module> import router as <foo>_router` lines (around lines 9–22). After `from app.reflection import reflect as reflection_reflect, router as reflection_router`, add:

```python
from app.shorts.routes import router as shorts_router
```

- [ ] **Step 2: Register the router**

Find where the other routers are registered (search for `app.include_router(reflection_router)` or the closest analogue). Immediately after that line, add:

```python
app.include_router(shorts_router)
```

- [ ] **Step 3: Verify the app boots and the routes are mounted**

Run: `python -c "from app.main import app; print([r.path for r in app.routes if getattr(r, 'path', '').startswith('/shorts')])"`
Expected: prints a list containing `/shorts/jobs` and `/shorts/jobs/{job_id}`.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat(shorts): mount /shorts router"
```

---

## Task 8: Minimal dashboard page

**Files:**
- Create: `app/static/shorts.html`
- Modify: `app/static/index.html` (one nav link)

**Interfaces:**
- Consumes: `GET /auth/channels`, `POST /shorts/jobs`, `GET /shorts/jobs`, `GET /shorts/jobs/{id}`.
- Produces: a page at `/static/shorts.html`.

- [ ] **Step 1: Write the dashboard page**

Create `app/static/shorts.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Shorts — Midas</title>
  <style>
    body { font: 14px/1.4 system-ui, sans-serif; max-width: 960px; margin: 24px auto; padding: 0 16px; }
    h1 { margin-bottom: 8px; }
    label { display: block; margin: 12px 0 4px; font-weight: 600; }
    select, input, button { font: inherit; padding: 6px 8px; }
    input[type=text] { width: 100%; box-sizing: border-box; }
    button { cursor: pointer; }
    table { border-collapse: collapse; width: 100%; margin-top: 16px; }
    th, td { border-bottom: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }
    .status-DONE      { color: #0a7a2f; font-weight: 600; }
    .status-FAILED    { color: #b00020; font-weight: 600; }
    .status-UPLOADING { color: #b07a00; }
    .muted { color: #666; font-size: 12px; }
  </style>
</head>
<body>
  <h1>Shorts</h1>
  <p class="muted">Prototype: pick a channel, paste a YouTube URL, generate shorts via WayinVideo, auto-upload as <b>private</b>.</p>

  <label for="channel">Channel</label>
  <select id="channel"></select>

  <label for="url">YouTube URL</label>
  <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=..." />

  <p><button id="generate">Generate shorts</button></p>

  <h2>Jobs</h2>
  <table id="jobs">
    <thead><tr><th>ID</th><th>Channel</th><th>URL</th><th>Status</th><th>Error</th><th>Clips</th></tr></thead>
    <tbody></tbody>
  </table>

<script>
async function loadChannels() {
  const r = await fetch('/auth/channels');
  const channels = await r.json();
  const sel = document.getElementById('channel');
  sel.innerHTML = '';
  for (const c of channels) {
    const o = document.createElement('option');
    o.value = c.id;
    o.textContent = (c.name || c.id) + ' (' + c.id + ')';
    sel.appendChild(o);
  }
}

async function loadJobs() {
  const r = await fetch('/shorts/jobs');
  const jobs = await r.json();
  const tbody = document.querySelector('#jobs tbody');
  tbody.innerHTML = '';
  for (const j of jobs) {
    const detail = await fetch('/shorts/jobs/' + j.id).then(r => r.json());
    const clipsHtml = (detail.clips || []).map(c => {
      const link = c.yt_video_id
        ? `<a href="https://studio.youtube.com/video/${c.yt_video_id}/edit" target="_blank">${c.yt_video_id}</a>`
        : (c.local_path ? `<span class="muted">local: ${c.local_path}</span>` : '');
      return `<div>#${c.rank} <span class="status-${c.upload_status}">${c.upload_status}</span> — ${c.title || ''} ${link}</div>`;
    }).join('');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${j.id}</td>
      <td>${j.channel_id}</td>
      <td><a href="${j.source_url}" target="_blank">${j.source_url}</a></td>
      <td class="status-${j.status}">${j.status}</td>
      <td class="muted">${j.error_message || ''}</td>
      <td>${clipsHtml || '<span class="muted">—</span>'}</td>`;
    tbody.appendChild(tr);
  }
}

document.getElementById('generate').addEventListener('click', async () => {
  const channel_id = document.getElementById('channel').value;
  const source_url = document.getElementById('url').value.trim();
  if (!channel_id || !source_url) { alert('Pick a channel and paste a URL.'); return; }
  const r = await fetch('/shorts/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel_id, source_url }),
  });
  if (!r.ok) { alert('Submit failed: ' + (await r.text())); return; }
  document.getElementById('url').value = '';
  loadJobs();
});

loadChannels();
loadJobs();
setInterval(loadJobs, 10000);
</script>
</body>
</html>
```

- [ ] **Step 2: Add a nav link in `index.html`**

Open `app/static/index.html`. Locate the existing navigation/header area (search for the first `<a href="` that points to another in-app page). Add a sibling link:

```html
<a href="/static/shorts.html">Shorts</a>
```

If there is no existing nav, add this somewhere near the top of `<body>`:

```html
<p><a href="/static/shorts.html">Shorts</a></p>
```

- [ ] **Step 3: Manual smoke test**

Boot the app (`uvicorn app.main:app --reload`), open `http://localhost:8000/static/shorts.html`, verify:
1. Channel dropdown populates from `/auth/channels`.
2. Pasting a YouTube URL and clicking "Generate shorts" creates a job row that appears in the table within 10s.
3. Status transitions visibly: `CREATED → QUEUED → ONGOING → SUCCEEDED → UPLOADING → DONE` (or `FAILED`).
4. On `DONE`, each clip row shows a `vid_*` link that opens in YouTube Studio at the new private video.

- [ ] **Step 4: Commit**

```bash
git add app/static/shorts.html app/static/index.html
git commit -m "feat(shorts): dashboard page"
```

---

## Self-Review Notes

- **Spec coverage:**
  - Pick a YT video → Task 8 (dashboard form).
  - Sequential shorts via WayinVideo → Tasks 3, 5, 6 (submit, poll, normalize, process in rank order).
  - Upload each short as private → Task 4 (`privacyStatus="private"` hardcoded).
  - Stream straight into YT upload → Task 5 `_stream_upload` via `_IterReader`.
  - Local download backup if YT upload fails → Task 5 `_download_then_upload`; preserved on row even if disk-retry also fails.
  - No polling host running → Task 6 uses the existing APScheduler in `app/main.py` via one-shot `date` jobs.
  - No new OAuth scope needed → confirmed pre-plan; existing `youtube` scope covers `videos.insert`.

- **Known fuzzy edge:** the exact JSON shape of WayinVideo's clip list isn't documented in the snippet provided. Task 5's `normalize_clips` tolerates synonyms, and the implementer is told to adjust there once a real response is observed. Everything else only reads our normalized shape.
