# NAS-Sourced Shorts Cutter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a NAS (SMB) source path to the shorts cutter — cut every rhyme video in a language folder, write the clips and move the source to a matching COMPLETED folder — selectable per job, alongside the untouched YouTube/yt-dlp path.

**Architecture:** Purely additive. A new `NASService` (SMB, with a `local` mode for tests) reads/writes the NAS. A shared `enqueue_language_jobs()` helper scans a language folder and inserts `shorts_jobs` rows tagged with `source_nas_path`. The existing dispatcher runs them; `run_shorts_job` gains a branch that routes `source_nas_path` jobs to a new NAS flow (no YouTube upload). Nothing is deleted.

**Tech Stack:** Python, FastAPI, Supabase (Postgres via `app.db.supabase()`), `smbprotocol`/`smbclient`, pytest.

## Global Constraints

- **Delete nothing.** All existing code (`download.py`, `youtube_upload.py`, legacy `/shorts/jobs`, `/videos/{id}/short`, `/clips/{id}/upload`, autopilot shorts action) stays and keeps working. New code sits alongside.
- **No YouTube upload in the NAS flow.** NAS in → NAS out only.
- Settings live on `app.config.Settings` (UPPERCASE attrs) and are read via `from app.config import settings`.
- DB access is always `from app.db import supabase` then `supabase().table(...)`.
- NAS paths passed to `NASService` are **relative to the share** (`//10.1.1.3/DATA`); callers prepend `NAS_SOURCE_ROOT_PATH` / `NAS_DESTINATION_ROOT_PATH`.
- Real NAS values (already in `.env`): source root `Animations/SHORTS CUTTER/RHYMES`, dest root `Animations/SHORTS CUTTER/COMPLETED`, 11 language folders: `BANGLA BHOJPURI ENGLISH GUJARATI HARYANVI HINDI MALAYALAM MARATHI PUNJABI RAJASTHANI TAMIL`.
- Video extensions recognized as sources/clips: `.mp4 .mov .mkv .webm .avi`.
- Poison-source guard: skip a source file with ≥ 3 FAILED jobs (`MAX_SHORTS_RETRY_ATTEMPTS = 3`, mirrors `app/autopilot.py`).

---

## File Structure

- **Create** `app/services/__init__.py` — package marker (if `app/services/` doesn't exist).
- **Create** `app/services/nas_service.py` — SMB/local NAS access: `list_video_files`, `copy_to_local`, `copy_from_local`, `move`, `makedirs`. Module singleton `nas_service`.
- **Create** `app/shorts/nas_source.py` — `list_source_languages`, `uncut_source_paths`, `uncut_count`, `enqueue_language_jobs`.
- **Modify** `app/config.py` — add NAS settings.
- **Modify** `app/shorts/routes.py` — add `POST /shorts/cut`, `GET /shorts/languages`.
- **Modify** `app/shorts/runner.py` — add `_run_nas_shorts_job` + branch in `run_shorts_job`.
- **Create** `supabase/migrations/20260722120000_shorts_nas_source.sql` — schema additions.
- **Create** `scripts/cut_language.py` — headless CLI trigger.
- **Create** tests: `tests/services/test_nas_service.py`, `tests/shorts/test_nas_source.py`, `tests/shorts/test_nas_routes.py`, `tests/shorts/test_runner_nas.py`.

Requirement: add `smbprotocol` to `requirements.txt` (folded into Task 1).

---

### Task 1: NAS settings + dependency

**Files:**
- Modify: `app/config.py:120-123` (insert new settings before `settings = Settings()`)
- Modify: `requirements.txt`
- Test: `tests/test_nas_settings.py`

**Interfaces:**
- Produces: `settings.NAS_MODE`, `settings.NAS_SERVER`, `settings.NAS_SHARE`, `settings.NAS_USERNAME`, `settings.NAS_PASSWORD`, `settings.NAS_DOMAIN` (str), `settings.NAS_PORT` (int), `settings.NAS_SOURCE_ROOT_PATH`, `settings.NAS_DESTINATION_ROOT_PATH`, `settings.NAS_LOCAL_ROOT` (all str).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nas_settings.py
def test_nas_settings_have_expected_defaults():
    from app.config import Settings
    s = Settings()
    assert s.NAS_MODE in ("smb", "local")
    assert isinstance(s.NAS_PORT, int)
    # Root paths default to the real NAS layout when unset in env.
    assert s.NAS_SOURCE_ROOT_PATH
    assert s.NAS_DESTINATION_ROOT_PATH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_nas_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'NAS_MODE'`

- [ ] **Step 3: Add the settings**

In `app/config.py`, immediately before line `settings = Settings()` (inside the class, so keep it indented with the other attrs — add just before the class ends, e.g. after the `KEYFRAME_FFMPEG_TIMEOUT` line):

```python
    # --- NAS (shorts cutter source) ---
    # SMB share holding rhyme source videos, organized as
    # <NAS_SOURCE_ROOT_PATH>/<LANGUAGE>/<file>.mp4. Cut clips + the moved
    # source land under <NAS_DESTINATION_ROOT_PATH>/<LANGUAGE>/. "local" mode
    # (a plain filesystem root) exists for tests and dev without a NAS.
    NAS_MODE            = os.getenv("NAS_MODE", "smb").lower()
    NAS_SERVER          = os.getenv("NAS_SERVER", "")
    NAS_SHARE           = os.getenv("NAS_SHARE", "")
    NAS_USERNAME        = os.getenv("NAS_USERNAME", "")
    NAS_PASSWORD        = os.getenv("NAS_PASSWORD", "")
    NAS_DOMAIN          = os.getenv("NAS_DOMAIN", "")
    NAS_PORT            = int(os.getenv("NAS_PORT") or "445")
    NAS_SOURCE_ROOT_PATH      = os.getenv("NAS_SOURCE_ROOT_PATH", "Animations/SHORTS CUTTER/RHYMES")
    NAS_DESTINATION_ROOT_PATH = os.getenv("NAS_DESTINATION_ROOT_PATH", "Animations/SHORTS CUTTER/COMPLETED")
    # local-mode root (mode="local"): a directory that stands in for the share.
    NAS_LOCAL_ROOT      = os.getenv("NAS_LOCAL_ROOT", "./nas_data")
```

Then add `smbprotocol` to `requirements.txt` (append a line):

```
smbprotocol
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_nas_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py requirements.txt tests/test_nas_settings.py
git commit -m "feat(nas): add NAS settings and smbprotocol dependency"
```

---

### Task 2: NASService (SMB + local mode)

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/nas_service.py`
- Test: `tests/services/__init__.py`, `tests/services/test_nas_service.py`

**Interfaces:**
- Consumes: `settings.NAS_*` from Task 1.
- Produces (module singleton `nas_service` and class `NASService`):
  - `list_video_files(relative_dir: str) -> list[str]` — sorted filenames (basename only) with a video extension; `[]` if the dir is missing.
  - `copy_to_local(relative_path: str, local_dest: Path) -> Path` — stream NAS file → local path (creates parent dirs); returns `local_dest`.
  - `copy_from_local(local_src: Path, relative_path: str) -> None` — stream local file → NAS (creates NAS parent dirs).
  - `move(src_relative: str, dst_relative: str) -> None` — move within the share (creates dst parent dirs).
  - `makedirs(relative_dir: str) -> None`.

- [ ] **Step 1: Write the failing tests (local mode against a temp dir)**

```python
# tests/services/test_nas_service.py
from pathlib import Path
import pytest
from app.services.nas_service import NASService


def _svc(tmp_path):
    svc = NASService()
    svc.mode = "local"
    svc.local_root = Path(tmp_path)
    return svc


def test_list_video_files_filters_and_sorts(tmp_path):
    d = tmp_path / "HINDI"
    d.mkdir()
    (d / "b.mp4").write_bytes(b"x")
    (d / "a.mov").write_bytes(b"x")
    (d / "notes.txt").write_bytes(b"x")
    (d / ".DS_Store").write_bytes(b"x")
    svc = _svc(tmp_path)
    assert svc.list_video_files("HINDI") == ["a.mov", "b.mp4"]


def test_list_video_files_missing_dir_returns_empty(tmp_path):
    assert _svc(tmp_path).list_video_files("NOPE") == []


def test_copy_to_local_streams_bytes(tmp_path):
    (tmp_path / "HINDI").mkdir()
    (tmp_path / "HINDI" / "song.mp4").write_bytes(b"video-bytes")
    svc = _svc(tmp_path)
    dest = tmp_path / "work" / "song.mp4"
    out = svc.copy_to_local("HINDI/song.mp4", dest)
    assert out == dest
    assert dest.read_bytes() == b"video-bytes"


def test_copy_from_local_creates_dirs_and_writes(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"clip-bytes")
    svc = _svc(tmp_path)
    svc.copy_from_local(src, "COMPLETED/HINDI/clip.mp4")
    assert (tmp_path / "COMPLETED" / "HINDI" / "clip.mp4").read_bytes() == b"clip-bytes"


def test_move_relocates_file_and_creates_dest_dir(tmp_path):
    (tmp_path / "RHYMES" / "HINDI").mkdir(parents=True)
    (tmp_path / "RHYMES" / "HINDI" / "song.mp4").write_bytes(b"v")
    svc = _svc(tmp_path)
    svc.move("RHYMES/HINDI/song.mp4", "COMPLETED/HINDI/song.mp4")
    assert not (tmp_path / "RHYMES" / "HINDI" / "song.mp4").exists()
    assert (tmp_path / "COMPLETED" / "HINDI" / "song.mp4").read_bytes() == b"v"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/services/test_nas_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.nas_service'`

- [ ] **Step 3: Create the package marker**

Create `app/services/__init__.py` (empty) and `tests/services/__init__.py` (empty).

- [ ] **Step 4: Implement the service**

```python
# app/services/nas_service.py
"""NAS access for the shorts cutter. SMB in production; a plain-filesystem
'local' mode makes it testable and usable without a NAS.

All relative paths are relative to the SMB share root (//SERVER/SHARE). In
local mode they resolve under `local_root`, a directory that stands in for
the share."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


class NASService:
    def __init__(self) -> None:
        self.mode = settings.NAS_MODE
        self.server = settings.NAS_SERVER
        self.share = settings.NAS_SHARE
        self.local_root = Path(settings.NAS_LOCAL_ROOT).resolve()
        self._connected = False

    # --- path helpers ---------------------------------------------------
    def _rel(self, relative_path: str) -> str:
        return relative_path.strip("/").replace("\\", "/")

    def _remote(self, relative_path: str) -> str:
        win = self._rel(relative_path).replace("/", "\\")
        return rf"\\{self.server}\{self.share}\{win}"

    def _local(self, relative_path: str) -> Path:
        return self.local_root / self._rel(relative_path)

    def _connect(self) -> None:
        if self.mode != "smb" or self._connected:
            return
        import smbclient
        kwargs = {"username": settings.NAS_USERNAME,
                  "password": settings.NAS_PASSWORD,
                  "port": settings.NAS_PORT}
        domain = (settings.NAS_DOMAIN or "").strip()
        if domain:
            kwargs["username"] = f"{domain}\\{settings.NAS_USERNAME}"
        smbclient.register_session(self.server, **kwargs)
        self._connected = True

    # --- operations -----------------------------------------------------
    def makedirs(self, relative_dir: str) -> None:
        if self.mode == "local":
            self._local(relative_dir).mkdir(parents=True, exist_ok=True)
            return
        import smbclient
        self._connect()
        smbclient.makedirs(self._remote(relative_dir), exist_ok=True)

    def list_video_files(self, relative_dir: str) -> list[str]:
        if self.mode == "local":
            d = self._local(relative_dir)
            if not d.is_dir():
                return []
            names = [e.name for e in d.iterdir()
                     if e.is_file() and e.suffix.lower() in VIDEO_EXTENSIONS]
            return sorted(names)
        import smbclient
        self._connect()
        base = self._remote(relative_dir)
        if not smbclient.path.exists(base):
            return []
        names = [e.name for e in smbclient.scandir(base)
                 if not e.is_dir() and Path(e.name).suffix.lower() in VIDEO_EXTENSIONS]
        return sorted(names)

    def copy_to_local(self, relative_path: str, local_dest: Path) -> Path:
        local_dest = Path(local_dest)
        local_dest.parent.mkdir(parents=True, exist_ok=True)
        if self.mode == "local":
            shutil.copyfile(self._local(relative_path), local_dest)
            return local_dest
        import smbclient
        self._connect()
        with smbclient.open_file(self._remote(relative_path), mode="rb") as src, \
                open(local_dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return local_dest

    def copy_from_local(self, local_src: Path, relative_path: str) -> None:
        parent = str(Path(self._rel(relative_path)).parent)
        self.makedirs(parent)
        if self.mode == "local":
            shutil.copyfile(local_src, self._local(relative_path))
            return
        import smbclient
        self._connect()
        with open(local_src, "rb") as src, \
                smbclient.open_file(self._remote(relative_path), mode="wb") as dst:
            shutil.copyfileobj(src, dst)

    def move(self, src_relative: str, dst_relative: str) -> None:
        parent = str(Path(self._rel(dst_relative)).parent)
        self.makedirs(parent)
        if self.mode == "local":
            shutil.move(str(self._local(src_relative)), str(self._local(dst_relative)))
            return
        import smbclient
        self._connect()
        smbclient.rename(self._remote(src_relative), self._remote(dst_relative))


nas_service = NASService()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/pytest tests/services/test_nas_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add app/services/__init__.py app/services/nas_service.py tests/services/
git commit -m "feat(nas): NASService with SMB + local modes"
```

---

### Task 3: DB migration

**Files:**
- Create: `supabase/migrations/20260722120000_shorts_nas_source.sql`

**Interfaces:**
- Produces columns consumed by Tasks 4–6: `shorts_jobs.language`, `shorts_jobs.source_nas_path`, `shorts_clips.nas_path`, `channels.nas_folder`; `shorts_jobs.channel_id` becomes nullable.

- [ ] **Step 1: Write the migration**

```sql
-- supabase/migrations/20260722120000_shorts_nas_source.sql
-- NAS-sourced shorts: jobs can originate from a NAS language folder instead
-- of a YouTube URL. Additive — the YouTube path is unchanged.
alter table shorts_jobs
    add column if not exists language        text,
    add column if not exists source_nas_path text;

-- NAS jobs have no channel; existing YouTube jobs still set it.
alter table shorts_jobs
    alter column channel_id drop not null;

alter table shorts_clips
    add column if not exists nas_path text;

-- Deploy-time autopilot mapping: which language folder a channel pulls from.
-- NULL for every channel today, so autopilot shorts stays inert until set.
alter table channels
    add column if not exists nas_folder text;
```

- [ ] **Step 2: Apply the migration**

Run the project's normal migration apply (Supabase). If using the Supabase CLI:

Run: `supabase db push`
Expected: applies `20260722120000_shorts_nas_source.sql` with no error.

(If `channel_id` has no NOT NULL constraint in this environment, the `drop not null` is a harmless no-op error — verify the column exists and is nullable before continuing.)

- [ ] **Step 3: Verify columns exist**

Run (psql or Supabase SQL editor):
```sql
select column_name, is_nullable from information_schema.columns
where table_name = 'shorts_jobs' and column_name in ('language','source_nas_path','channel_id');
```
Expected: three rows; `channel_id` `is_nullable = YES`.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260722120000_shorts_nas_source.sql
git commit -m "feat(nas): migration for NAS-sourced shorts columns"
```

---

### Task 4: Enqueue helper

**Files:**
- Create: `app/shorts/nas_source.py`
- Test: `tests/shorts/test_nas_source.py`

**Interfaces:**
- Consumes: `nas_service.list_video_files` (Task 2); `settings.NAS_SOURCE_ROOT_PATH` (Task 1); `supabase()` (`app.db`).
- Produces:
  - `list_source_languages() -> list[str]` — subfolders under the source root.
  - `uncut_source_paths(language: str) -> list[str]` — `"<LANG>/<file>"` paths with no in-flight job and under the FAILED retry cap.
  - `uncut_count(language: str) -> int`.
  - `enqueue_language_jobs(language: str, *, channel_id: str | None = None, autopilot: bool = False, limit: int | None = None, cut_mode: str = "highlights", camera_motion: str = "calm") -> int` — inserts `CREATED` jobs; returns count. Raises `ValueError` for an unknown language.
  - Constant `WORKING_STATUSES` (in-flight set) and `MAX_SHORTS_RETRY_ATTEMPTS = 3`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/shorts/test_nas_source.py
from unittest.mock import MagicMock, patch
import pytest


def _sb_with_jobs(existing_jobs, insert_recorder):
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value.in_.return_value.execute.return_value.data = existing_jobs
        def _insert(fields):
            insert_recorder.append(fields)
            i = MagicMock()
            i.execute.return_value.data = [{"id": len(insert_recorder), **fields}]
            return i
        t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


def test_enqueue_rejects_unknown_language():
    from app.shorts import nas_source
    with patch.object(nas_source, "list_source_languages", return_value=["HINDI"]):
        with pytest.raises(ValueError):
            nas_source.enqueue_language_jobs("KLINGON")


def test_enqueue_skips_in_flight_and_capped_files():
    from app.shorts import nas_source
    files = ["a.mp4", "b.mp4", "c.mp4", "d.mp4"]
    existing = [
        {"source_nas_path": "HINDI/b.mp4", "status": "DOWNLOADING"},   # in-flight -> skip
        {"source_nas_path": "HINDI/c.mp4", "status": "FAILED"},
        {"source_nas_path": "HINDI/c.mp4", "status": "FAILED"},
        {"source_nas_path": "HINDI/c.mp4", "status": "FAILED"},        # 3 fails -> skip
    ]
    recorder = []
    with patch.object(nas_source, "list_source_languages", return_value=["HINDI"]), \
         patch.object(nas_source.nas_service, "list_video_files", return_value=files), \
         patch.object(nas_source, "supabase", return_value=_sb_with_jobs(existing, recorder)):
        n = nas_source.enqueue_language_jobs("HINDI")
    assert n == 2                                   # a.mp4 and d.mp4 only
    paths = sorted(r["source_nas_path"] for r in recorder)
    assert paths == ["HINDI/a.mp4", "HINDI/d.mp4"]
    assert all(r["status"] == "CREATED" and r["language"] == "HINDI" for r in recorder)


def test_enqueue_respects_limit():
    from app.shorts import nas_source
    recorder = []
    with patch.object(nas_source, "list_source_languages", return_value=["HINDI"]), \
         patch.object(nas_source.nas_service, "list_video_files", return_value=["a.mp4", "b.mp4", "c.mp4"]), \
         patch.object(nas_source, "supabase", return_value=_sb_with_jobs([], recorder)):
        n = nas_source.enqueue_language_jobs("HINDI", limit=2)
    assert n == 2
    assert len(recorder) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/shorts/test_nas_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.shorts.nas_source'`

- [ ] **Step 3: Implement the helper**

```python
# app/shorts/nas_source.py
"""Scan a NAS language folder and enqueue one shorts_job per uncut video.

Shared by the manual POST /shorts/cut endpoint and (at deploy time) the
autopilot shorts action. Additive — YouTube-URL jobs are unaffected."""
from __future__ import annotations

import logging
from collections import defaultdict

from app.config import settings
from app.db import supabase
from app.services.nas_service import nas_service

log = logging.getLogger("midas.shorts.nas_source")

# A job a worker has queued or is actively running (mirrors runner.WORKING_STATUSES).
WORKING_STATUSES = ("CREATED", "DOWNLOADING", "ANALYSING", "RENDERING", "UPLOADING")
# A source whose cut keeps failing is left in place (not moved), so without a cap
# it would be re-enqueued forever. Same value/rationale as app/autopilot.py.
MAX_SHORTS_RETRY_ATTEMPTS = 3


def list_source_languages() -> list[str]:
    """Language subfolders under the source root."""
    # nas_service exposes files, not dirs; list dirs directly per mode.
    if nas_service.mode == "local":
        base = nas_service._local(settings.NAS_SOURCE_ROOT_PATH)
        if not base.is_dir():
            return []
        return sorted([e.name for e in base.iterdir() if e.is_dir()])
    import smbclient
    nas_service._connect()
    base = nas_service._remote(settings.NAS_SOURCE_ROOT_PATH)
    if not smbclient.path.exists(base):
        return []
    return sorted([e.name for e in smbclient.scandir(base) if e.is_dir()])


def uncut_source_paths(language: str) -> list[str]:
    """`<LANG>/<file>` paths with no in-flight job and under the FAILED cap."""
    files = nas_service.list_video_files(f"{settings.NAS_SOURCE_ROOT_PATH}/{language}")
    paths = [f"{language}/{name}" for name in files]
    if not paths:
        return []
    rows = (supabase().table("shorts_jobs")
            .select("source_nas_path,status")
            .in_("source_nas_path", paths).execute().data) or []
    in_flight: set[str] = set()
    failed: dict[str, int] = defaultdict(int)
    for r in rows:
        p = r.get("source_nas_path")
        status = (r.get("status") or "").upper()
        if not p:
            continue
        if status in WORKING_STATUSES:
            in_flight.add(p)
        elif status == "FAILED":
            failed[p] += 1
    return [p for p in paths
            if p not in in_flight and failed[p] < MAX_SHORTS_RETRY_ATTEMPTS]


def uncut_count(language: str) -> int:
    return len(uncut_source_paths(language))


def enqueue_language_jobs(language: str, *, channel_id: str | None = None,
                          autopilot: bool = False, limit: int | None = None,
                          cut_mode: str = "highlights",
                          camera_motion: str = "calm") -> int:
    if language not in list_source_languages():
        raise ValueError(f"Unknown NAS language folder: {language!r}")
    todo = uncut_source_paths(language)
    if limit is not None:
        todo = todo[:limit]
    for path in todo:
        supabase().table("shorts_jobs").insert({
            "channel_id":          channel_id,
            "language":            language,
            "source_nas_path":     path,
            "cut_mode":            cut_mode,
            "camera_motion":       camera_motion,
            "autopilot_generated": autopilot,
            "status":              "CREATED",
        }).execute()
    log.info("NAS enqueue: %d job(s) for language %s", len(todo), language)
    return len(todo)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/shorts/test_nas_source.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/shorts/nas_source.py tests/shorts/test_nas_source.py
git commit -m "feat(nas): enqueue_language_jobs helper (scan folder -> jobs)"
```

---

### Task 5: Trigger endpoints

**Files:**
- Modify: `app/shorts/routes.py` (add near the other `router` endpoints, after `list_jobs`)
- Test: `tests/shorts/test_nas_routes.py`

**Interfaces:**
- Consumes: `enqueue_language_jobs`, `list_source_languages`, `uncut_count` (Task 4).
- Produces: `POST /shorts/cut` → `{"language": str, "enqueued": int}`; `GET /shorts/languages` → `[{"language": str, "uncut": int}, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/shorts/test_nas_routes.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_cut_endpoint_enqueues():
    with patch("app.shorts.routes.enqueue_language_jobs", return_value=7) as enq:
        resp = client.post("/shorts/cut", json={"language": "hindi"})
    assert resp.status_code == 200
    assert resp.json() == {"language": "HINDI", "enqueued": 7}
    enq.assert_called_once_with("HINDI")


def test_cut_endpoint_unknown_language_is_400():
    with patch("app.shorts.routes.enqueue_language_jobs", side_effect=ValueError("nope")):
        resp = client.post("/shorts/cut", json={"language": "KLINGON"})
    assert resp.status_code == 400


def test_languages_endpoint_lists_counts():
    with patch("app.shorts.routes.list_source_languages", return_value=["HINDI", "TAMIL"]), \
         patch("app.shorts.routes.uncut_count", side_effect=[3, 0]):
        resp = client.get("/shorts/languages")
    assert resp.status_code == 200
    assert resp.json() == [{"language": "HINDI", "uncut": 3}, {"language": "TAMIL", "uncut": 0}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/shorts/test_nas_routes.py -v`
Expected: FAIL — 404 on `/shorts/cut` (route not defined) / ImportError on patch target.

- [ ] **Step 3: Add the endpoints**

In `app/shorts/routes.py`, add the import near the top (after the existing `from app.shorts...` imports):

```python
from app.shorts.nas_source import (
    enqueue_language_jobs, list_source_languages, uncut_count,
)
```

Then add these endpoints after the `list_jobs` function:

```python
class CutLanguage(BaseModel):
    language: str


@router.post("/cut")
def cut_language(body: CutLanguage):
    """Enqueue a shorts job for every uncut video in a NAS language folder."""
    language = body.language.strip().upper()
    try:
        enqueued = enqueue_language_jobs(language)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log.info("NAS cut: %d job(s) queued for %s", enqueued, language)
    return {"language": language, "enqueued": enqueued}


@router.get("/languages")
def languages():
    """NAS source language folders with their uncut video counts."""
    return [{"language": lang, "uncut": uncut_count(lang)}
            for lang in list_source_languages()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/shorts/test_nas_routes.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/shorts/routes.py tests/shorts/test_nas_routes.py
git commit -m "feat(nas): POST /shorts/cut and GET /shorts/languages"
```

---

### Task 6: Runner NAS branch

**Files:**
- Modify: `app/shorts/runner.py` (add branch in `run_shorts_job` after the job is fetched; add `_run_nas_shorts_job`)
- Test: `tests/shorts/test_runner_nas.py`

**Interfaces:**
- Consumes: `nas_service` (Task 2); `settings.NAS_SOURCE_ROOT_PATH`, `settings.NAS_DESTINATION_ROOT_PATH` (Task 1); existing `_cut_video`, `_set_job`, `_notify_macos`, `safe_name`.
- Produces: `_run_nas_shorts_job(job_id: int, job: dict) -> None`; `run_shorts_job` routes `source_nas_path` jobs to it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/shorts/test_runner_nas.py
from pathlib import Path
from unittest.mock import MagicMock, patch


def _fake_sb(job_row, recorder):
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = job_row
        def _update(fields):
            recorder.append((name, "update", fields))
            u = MagicMock()
            u.eq.return_value.execute.return_value.data = [{}]
            return u
        def _insert(fields):
            recorder.append((name, "insert", fields))
            i = MagicMock()
            i.execute.return_value.data = [{"id": 1, **fields}]
            return i
        t.update.side_effect = _update
        t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


NAS_JOB = {"id": 9, "channel_id": None, "language": "HINDI",
           "source_nas_path": "HINDI/song.mp4", "cut_mode": "highlights",
           "camera_motion": "calm", "status": "CREATED"}


def test_nas_job_cuts_pushes_clips_and_moves_source(tmp_path):
    recorder = []
    clips = [{"path": str(tmp_path / "c1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0, "verdict": "PASS"}]
    (tmp_path / "c1.mp4").write_bytes(b"clip")
    nas = MagicMock()
    nas.copy_to_local.return_value = tmp_path / "src" / "song.mp4"

    with patch("app.shorts.runner.supabase", return_value=_fake_sb(NAS_JOB, recorder)), \
         patch("app.shorts.runner.nas_service", nas), \
         patch("app.shorts.runner._cut_video",
               return_value={"clips": clips, "message": "ok", "language": "hi", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as st:
        st.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        st.NAS_SOURCE_ROOT_PATH = "RHYMES"
        st.NAS_DESTINATION_ROOT_PATH = "COMPLETED"
        from app.shorts.runner import run_shorts_job
        run_shorts_job(9)

    up.assert_not_called()                                     # no YouTube upload
    nas.copy_from_local.assert_called_once()                   # clip pushed to NAS
    _, kwargs_or_args = nas.copy_from_local.call_args
    nas.move.assert_called_once_with("RHYMES/HINDI/song.mp4", "COMPLETED/HINDI/song.mp4")
    clip_inserts = [f for (tbl, op, f) in recorder if tbl == "shorts_clips" and op == "insert"]
    assert clip_inserts and clip_inserts[0]["nas_path"] == "COMPLETED/HINDI/c1.mp4"
    assert clip_inserts[0]["upload_status"] == "SAVED"
    assert any(op == "update" and f.get("status") == "DONE" for (_, op, f) in recorder)


def test_nas_job_leaves_source_on_cut_failure(tmp_path):
    recorder = []
    nas = MagicMock()
    nas.copy_to_local.return_value = tmp_path / "src" / "song.mp4"
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(NAS_JOB, recorder)), \
         patch("app.shorts.runner.nas_service", nas), \
         patch("app.shorts.runner._cut_video", side_effect=RuntimeError("boom")), \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as st:
        st.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        st.NAS_SOURCE_ROOT_PATH = "RHYMES"
        st.NAS_DESTINATION_ROOT_PATH = "COMPLETED"
        from app.shorts.runner import run_shorts_job
        run_shorts_job(9)
    nas.move.assert_not_called()                               # source stays for retry
    assert any(op == "update" and f.get("status") == "FAILED" for (_, op, f) in recorder)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/shorts/test_runner_nas.py -v`
Expected: FAIL — the NAS job falls through to the legacy path (`_fetch_video` called with a NAS path, or `nas_service` not imported).

- [ ] **Step 3: Add the import and branch**

In `app/shorts/runner.py`, add the import near the top imports:

```python
from app.services.nas_service import nas_service
from app.shorts.cutter.util import safe_name
```

In `run_shorts_job`, right after the `if not job:` guard (after line ~59, before `job_dir = ...`), insert:

```python
    if job.get("source_nas_path"):
        return _run_nas_shorts_job(job_id, job)
```

Then add the new function (place it after `run_shorts_job`):

```python
def _run_nas_shorts_job(job_id: int, job: dict) -> None:
    """Cut a NAS-sourced video: copy from NAS, cut, push clips + move the source
    into COMPLETED/<language>/. No YouTube upload."""
    sb = supabase()
    job_dir = Path(settings.SHORTS_CACHE_DIR) / str(job_id)
    language = job["language"]
    src_rel = job["source_nas_path"]                 # e.g. "HINDI/song.mp4"
    filename = src_rel.rsplit("/", 1)[-1]
    dest_dir = f"{settings.NAS_DESTINATION_ROOT_PATH}/{language}"
    try:
        _set_job(job_id, status="DOWNLOADING", progress=5, progress_label="fetching from NAS")
        local_src = nas_service.copy_to_local(
            f"{settings.NAS_SOURCE_ROOT_PATH}/{src_rel}", job_dir / "src" / filename)
        title = safe_name(Path(filename).stem)

        def progress(stage: str, percent: int) -> None:
            status = "RENDERING" if "render" in stage else "ANALYSING"
            _set_job(job_id, status=status, progress=percent, progress_label=stage)

        result = _cut_video(
            local_src, job_dir, preferred_name=title,
            cut_mode=job.get("cut_mode") or "highlights",
            camera_motion=job.get("camera_motion") or "calm", progress=progress,
        )
        clips = result["clips"]

        _set_job(job_id, status="UPLOADING", progress=95,
                 progress_label=f"saving {len(clips)} clips to NAS")
        for clip in clips:
            clip_name = Path(clip["path"]).name
            nas_path = f"{dest_dir}/{clip_name}"
            nas_service.copy_from_local(Path(clip["path"]), nas_path)
            sb.table("shorts_clips").insert({
                "job_id": job_id, "rank": clip["rank"],
                "title": f"{title.replace('_', ' ')} — Part {clip['rank']}"[:100],
                "description": "", "hashtags": ["shorts"],
                "start_s": clip["start_s"], "end_s": clip["end_s"],
                "local_path": clip["path"], "nas_path": nas_path,
                "upload_status": "SAVED",
            }).execute()

        # Move the consumed source out of RHYMES so it is never re-cut.
        nas_service.move(f"{settings.NAS_SOURCE_ROOT_PATH}/{src_rel}",
                         f"{dest_dir}/{filename}")
        _set_job(job_id, status="DONE", progress=100, progress_label="done")
        _notify_macos("Midas Shorts", f"Job {job_id}: {len(clips)} clips cut from {filename}")
    except Exception as exc:
        log.exception("NAS job %s failed", job_id)
        _set_job(job_id, status="FAILED", error_message=str(exc)[:1000])
        _notify_macos("Midas Shorts", f"Job {job_id} failed: {exc}"[:120])
    finally:
        shutil.rmtree(job_dir / "src", ignore_errors=True)
        shutil.rmtree(job_dir / "tmp", ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/shorts/test_runner_nas.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full shorts suite (no regressions in the legacy path)**

Run: `venv/bin/pytest tests/shorts -v`
Expected: PASS (all, including the pre-existing `test_runner.py` YouTube path)

- [ ] **Step 6: Commit**

```bash
git add app/shorts/runner.py tests/shorts/test_runner_nas.py
git commit -m "feat(nas): runner branch for NAS-sourced jobs (no upload)"
```

---

### Task 7: Headless CLI trigger

**Files:**
- Create: `scripts/cut_language.py`

**Interfaces:**
- Consumes: `enqueue_language_jobs`, `list_source_languages` (Task 4).

- [ ] **Step 1: Write the CLI**

```python
# scripts/cut_language.py
"""Enqueue NAS shorts jobs for a language folder from the command line.

Usage:
    python -m scripts.cut_language HINDI
    python -m scripts.cut_language --list
"""
import sys

from app.shorts.nas_source import enqueue_language_jobs, list_source_languages


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m scripts.cut_language <LANGUAGE> | --list")
        return 0
    if argv[0] == "--list":
        for lang in list_source_languages():
            print(lang)
        return 0
    language = argv[0].strip().upper()
    try:
        n = enqueue_language_jobs(language)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Enqueued {n} job(s) for {language}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 2: Smoke-test the help path**

Run: `venv/bin/python -m scripts.cut_language --help`
Expected: prints usage, exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/cut_language.py
git commit -m "feat(nas): CLI to enqueue a language folder"
```

---

### Task 8: End-to-end verification against the real NAS

**Files:** none (manual verification)

- [ ] **Step 1: List languages live**

Run: `venv/bin/python -m scripts.cut_language --list`
Expected: prints the 11 folders (BANGLA … TAMIL).

- [ ] **Step 2: Confirm the uncut count endpoint works**

Start the app, then:
Run: `curl -s localhost:8000/shorts/languages`
Expected: JSON array of `{language, uncut}` with non-zero counts.

- [ ] **Step 3: Cut a single test file end-to-end**

Pick the smallest source file, temporarily move the rest out (or trust the one-at-a-time dispatcher), then:
Run: `curl -s -X POST localhost:8000/shorts/cut -H 'content-type: application/json' -d '{"language":"HINDI"}'`
Then watch: `curl -s localhost:8000/shorts/jobs | python -m json.tool`
Expected: jobs move CREATED → DOWNLOADING → ... → DONE. Verify on the NAS that `COMPLETED/HINDI/` now holds the clips **and** the moved source, and the source is gone from `RHYMES/HINDI/`.

- [ ] **Step 4: Note the result** (no commit — verification only). If anything fails, capture the job's `error_message` and stop.

---

## Notes for the executor

- Run all pytest via the repo venv: `venv/bin/pytest`.
- The `NASService` internals `_local`, `_remote`, `_connect` are used by `nas_source.list_source_languages` (dir listing, which the service doesn't expose as a public method) — keep their signatures.
- Task 3 (migration) must be applied before Tasks 4–6 run against a real DB, but the unit tests mock Supabase so they pass without it.
- Legacy path is untouched: `tests/shorts/test_runner.py` must stay green (Task 6, Step 5).
