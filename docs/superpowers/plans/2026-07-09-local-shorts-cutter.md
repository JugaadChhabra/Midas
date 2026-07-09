# Local Shorts Cutter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the WayinVideo third-party clipping API in Midas's shorts feature with the local RhymeShortsCutter pipeline, ported in as `app/shorts/cutter/`.

**Architecture:** The cutter's pipeline modules move into a framework-free subpackage `app/shorts/cutter/` (no FastAPI/Supabase imports allowed inside). A new `app/shorts/runner.py` runs jobs in a background thread, writing progress to the existing `shorts_jobs` Supabase table and auto-uploading rendered clips as private shorts via the existing `upload_short()`. `wayin_client.py`, `poller.py`, and the old `app/shorts/pipeline.py` are deleted.

**Tech Stack:** FastAPI, Supabase (postgrest), yt-dlp + bgutil PO-token script, faster-whisper, demucs, ultralytics YOLO, OpenCV, ffmpeg.

**Spec:** `docs/superpowers/specs/2026-07-09-local-shorts-cutter-design.md`

## Global Constraints

- Source codebase: `~/Downloads/RhymeShortsCutter_Mac` (call it `$SRC`). Copy from its **working tree** (it contains an uncommitted native-quality download fix that must be ported).
- Midas repo root: `~/Documents/Github/Midas`. Python: `venv/bin/python`, tests: `venv/bin/pytest` (note: `venv`, not `.venv`).
- Nothing under `app/shorts/cutter/` may import `fastapi`, `app.db`, or `app.config`. Cutter errors are raised as `CutterError`, never `HTTPException`.
- ML deps go in a NEW file `requirements-ml.txt` (exact pins below), NOT in `requirements.txt` — the Dockerfile installs `requirements.txt` and must not gain the ML stack. (Deviation from spec wording, which said "requirements.txt gains the ML stack"; the spec also requires Docker not to install it, and a separate file is the only way to satisfy both.)
- Heavy imports (torch/cv2/whisper) must be lazy: imported inside functions, not at module top level of anything `app.main` imports at startup. If they're missing, raise `CutterError("ML dependencies not installed — run: pip install -r requirements-ml.txt")`.
- Job status vocabulary: `CREATED → DOWNLOADING → ANALYSING → RENDERING → UPLOADING → DONE / FAILED`. One job at a time (409 on concurrent create).
- Run the full Midas suite (`venv/bin/pytest tests/ -q`) before every commit; it must stay green.
- Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Commit pending work in the source repo

The cutter repo has an uncommitted quality fix (native-resolution downloads) plus its test. Lock it in so `$SRC`'s history is clean before the port, and so the copies below have a fixed provenance.

**Files:**
- Modify (commit only): `~/Downloads/RhymeShortsCutter_Mac/main.py`, `tests/test_main_wiring.py`, `static/index.html`

**Steps:**

- [ ] **Step 1: Run the cutter's tests**

```bash
cd ~/Downloads/RhymeShortsCutter_Mac && .venv/bin/python -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 2: Commit**

```bash
cd ~/Downloads/RhymeShortsCutter_Mac
git add main.py tests/test_main_wiring.py static/index.html
git commit -m "feat: download at native upload quality — uncapped bv*+ba into mkv"
```

---

### Task 2: ML dependencies in Midas

**Files:**
- Create: `~/Documents/Github/Midas/requirements-ml.txt`
- Modify: `~/Documents/Github/Midas/requirements.txt` (bump yt-dlp pin only)
- Modify: `~/Documents/Github/Midas/README.md` (one setup line)

**Interfaces:**
- Produces: importable `torch`, `cv2`, `faster_whisper`, `ultralytics`, `demucs`, `yt_dlp` in Midas's venv for all later tasks.

**Steps:**

- [ ] **Step 1: Create `requirements-ml.txt`** — exact pins from the cutter's proven-working venv. torchaudio is pinned only because demucs imports it; do not upgrade it independently (this exact trio of torch pins is the combination known to work on this Mac).

```
# Local shorts cutter ML stack — NOT installed in Docker (see Dockerfile note).
# Pins mirror the working venv of the original RhymeShortsCutter_Mac app.
torch==2.12.1
torchvision==0.27.1
torchaudio==2.11.0
ultralytics==8.4.86
opencv-python==5.0.0.93
faster-whisper==1.2.1
ctranslate2==4.8.0
demucs==4.0.1
librosa==0.11.0
soundfile==0.14.0
av==18.0.0
numpy==2.4.6
bgutil-ytdlp-pot-provider
```

- [ ] **Step 2: Bump yt-dlp in `requirements.txt`**

Change the line `yt-dlp>=2024.1.0` to `yt-dlp>=2026.7.4` (PO-token/mweb support requires a current build).

- [ ] **Step 3: Install and verify**

```bash
cd ~/Documents/Github/Midas
venv/bin/pip install -r requirements.txt -r requirements-ml.txt
venv/bin/python -c "import torch, cv2, faster_whisper, ultralytics, demucs, yt_dlp; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Add a setup line to README.md** under the Install section:

```markdown
For the local shorts cutter (heavy ML deps, local runs only — not needed in Docker):
`pip install -r requirements-ml.txt`. Also requires `ffmpeg` and `node` on PATH.
```

- [ ] **Step 5: Run suite and commit**

```bash
venv/bin/pytest tests/ -q
git add requirements-ml.txt requirements.txt README.md
git commit -m "feat: add local shorts-cutter ML dependency set (requirements-ml.txt)"
```

---

### Task 3: Move the six framework-free pipeline modules + their tests

**Files:**
- Create: `app/shorts/cutter/__init__.py`, `app/shorts/cutter/errors.py`
- Create (copied): `app/shorts/cutter/{cutplan,framing,grading,selection,structure,vocals}.py`
- Create (copied): `tests/shorts/cutter/__init__.py` and `tests/shorts/cutter/test_{cutplan,cutplan_finesse,framing,framing_hold,grading,grading_ext,selection,structure,vocals,vocals_mono}.py`

**Interfaces:**
- Produces: `app.shorts.cutter.cutplan` (Stanza, TranscriptSegment, MAX_CLIP_SECONDS, full_coverage_stanzas, lyric_pause_candidates, finesse_boundaries, pad_clip), `…framing`, `…grading.grade_clips`, `…selection.plan_highlights`, `…structure.build_structure`, `…vocals.{load_mix_mono, vocal_silence_analysis}` — same signatures as the flat modules in `$SRC`.
- Produces: `app.shorts.cutter.errors.CutterError`.

**Steps:**

- [ ] **Step 1: Copy modules and tests**

```bash
cd ~/Documents/Github/Midas
SRC=~/Downloads/RhymeShortsCutter_Mac
mkdir -p app/shorts/cutter tests/shorts/cutter
touch app/shorts/cutter/__init__.py tests/shorts/cutter/__init__.py
for m in cutplan framing grading selection structure vocals; do cp $SRC/$m.py app/shorts/cutter/$m.py; done
for t in cutplan cutplan_finesse framing framing_hold grading grading_ext selection structure vocals vocals_mono; do cp $SRC/tests/test_$t.py tests/shorts/cutter/test_$t.py; done
```

- [ ] **Step 2: Create `app/shorts/cutter/errors.py`**

```python
class CutterError(RuntimeError):
    """Any failure inside the framework-free cutter pipeline."""
```

- [ ] **Step 3: Rewrite flat imports to package imports**

The only cross-module imports are `from cutplan import …` (in `grading.py`, `selection.py`, `structure.py`). In the copied files and tests:

```bash
cd ~/Documents/Github/Midas
sed -i '' 's/^from cutplan import /from app.shorts.cutter.cutplan import /' app/shorts/cutter/{grading,selection,structure}.py
sed -i '' -E 's/^from (cutplan|framing|grading|selection|structure|vocals) import /from app.shorts.cutter.\1 import /' tests/shorts/cutter/test_*.py
```
Then verify no flat imports remain: `grep -rn "^from \(cutplan\|framing\|grading\|selection\|structure\|vocals\) import" app/shorts/cutter/ tests/shorts/cutter/` → no output.

- [ ] **Step 4: Run the moved tests**

```bash
venv/bin/pytest tests/shorts/cutter/ -q
```
Expected: all pass (they were green in `$SRC`; only imports changed).

- [ ] **Step 5: Run full suite and commit**

```bash
venv/bin/pytest tests/ -q
git add app/shorts/cutter tests/shorts/cutter
git commit -m "feat: port framework-free cutter pipeline modules from RhymeShortsCutter"
```

---

### Task 4: `cutter/util.py` and `cutter/download.py` (+ bgutil PO-token script)

**Files:**
- Create: `app/shorts/cutter/util.py`, `app/shorts/cutter/download.py`
- Create (copied): `tools/bgutil-pot/` (from `$SRC/tools/bgutil-pot/`, stays gitignored)
- Modify: `.gitignore` (add `tools/bgutil-pot/` and `shorts_cache/` if missing)
- Test: `tests/shorts/cutter/test_download.py`

**Interfaces:**
- Consumes: `CutterError` from Task 3.
- Produces: `util.safe_name(value: str, fallback: str = "video") -> str`, `util.clamp(value, low, high) -> float`, `util.even(value) -> int`.
- Produces: `download.is_youtube_url(url: str) -> bool`, `download.ytdlp_options() -> dict`, `download.fetch_video(url: str, dest_dir: Path) -> tuple[Path, str]` (returns downloaded path + safe title; raises `CutterError`).

**Steps:**

- [ ] **Step 1: Write the failing test** — `tests/shorts/cutter/test_download.py`. Port the URL-regex cases from `$SRC/tests/test_jobs.py` and the options assertions from `$SRC/tests/test_main_wiring.py::test_ytdlp_options_use_mweb_and_po_token_script`:

```python
from pathlib import Path

from app.shorts.cutter.download import is_youtube_url, ytdlp_options


def test_youtube_urls_accepted():
    for url in [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=1s",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "youtube.com/watch?v=dQw4w9WgXcQ",
    ]:
        assert is_youtube_url(url), url


def test_non_youtube_urls_rejected():
    for url in ["https://vimeo.com/12345", "https://example.com/watch?v=dQw4w9WgXcQ", "not a url", ""]:
        assert not is_youtube_url(url), url


def test_ytdlp_options_native_quality_mweb_and_po_token():
    options = ytdlp_options()
    assert options["format"] == "bv*+ba/b"          # no height/codec cap
    assert options["merge_output_format"] == "mkv"
    clients = options["extractor_args"]["youtube"]["player_client"]
    assert clients[0] == "mweb" and "default" in clients
    script = options["extractor_args"]["youtubepot-bgutilscript"]["script_path"][0]
    assert Path(script).is_file()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
venv/bin/pytest tests/shorts/cutter/test_download.py -q
```
Expected: FAIL — `ModuleNotFoundError: app.shorts.cutter.download`.

- [ ] **Step 3: Copy the bgutil PO-token tool and gitignore it**

```bash
cp -R ~/Downloads/RhymeShortsCutter_Mac/tools ~/Documents/Github/Midas/tools
```
Append to `.gitignore` (if not present): `tools/bgutil-pot/` and `shorts_cache/`.

- [ ] **Step 4: Write `app/shorts/cutter/util.py`** — move `safe_name`, `clamp`, `even` verbatim from `$SRC/main.py:102-113`:

```python
from __future__ import annotations

import re
from pathlib import Path


def safe_name(value: str, fallback: str = "video") -> str:
    value = Path(value).stem
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value[:80] or fallback


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def even(value: float) -> int:
    return max(2, int(round(value / 2) * 2))
```

- [ ] **Step 5: Write `app/shorts/cutter/download.py`** — port `$SRC/main.py:871-915` (`BGUTIL_POT_SCRIPT`, `ytdlp_options`, `fetch_with_ytdlp`) and `$SRC/jobs.py:11-19` (URL regex), swapping `HTTPException` for `CutterError` and parameterizing the output dir:

```python
"""Native-quality YouTube download: yt-dlp with mweb client + bgutil PO tokens."""
from __future__ import annotations

import re
from pathlib import Path

from app.shorts.cutter.errors import CutterError
from app.shorts.cutter.util import safe_name

MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024 * 1024

# app/shorts/cutter/download.py -> repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
BGUTIL_POT_SCRIPT = _REPO_ROOT / "tools" / "bgutil-pot" / "server" / "build" / "generate_once.js"

# Keep in sync with the client-side check in app/static/shorts.html.
YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.|m\.)?"
    r"(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)"
    r"[A-Za-z0-9_-]{11}([&?/].*)?$"
)


def is_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_RE.match(url.strip()))


def ytdlp_options() -> dict:
    # The user's channel videos are PO-token-gated: without a token YouTube caps
    # downloads at 360p (or returns no formats at all when embedding is disabled).
    # bgutil's script mode mints tokens per request via node; mweb is the client
    # that actually serves full-quality https formats with a token, with the
    # default client rotation kept as fallback for videos where mweb misses.
    options = {
        # Grab the true best streams at the source's native resolution/fps —
        # above 1080p YouTube only serves VP9/AV1, so no codec/container filter.
        # MKV holds any codec pair; the pipeline re-renders clips to mp4 anyway.
        "format": "bv*+ba/b",
        "merge_output_format": "mkv",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        # YouTube requires a JS runtime for anti-bot challenges; node ships on this Mac.
        "js_runtimes": {"deno": {"path": None}, "node": {"path": None}},
        "remote_components": ["ejs:github"],
        "extractor_args": {"youtube": {"player_client": ["mweb", "default"]}},
    }
    if BGUTIL_POT_SCRIPT.is_file():
        options["extractor_args"]["youtubepot-bgutilscript"] = {
            "script_path": [str(BGUTIL_POT_SCRIPT)],
        }
    return options


def fetch_video(url: str, dest_dir: Path) -> tuple[Path, str]:
    """Download `url` into dest_dir at native quality. Returns (path, safe title)."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise CutterError("ML dependencies not installed — run: pip install -r requirements-ml.txt") from exc
    dest_dir.mkdir(parents=True, exist_ok=True)
    options = ytdlp_options()
    options["outtmpl"] = str(dest_dir / "source_%(id)s.%(ext)s")
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url.strip(), download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise CutterError(f"Could not download this video link: {exc}") from exc
    requested = (info or {}).get("requested_downloads") or []
    downloaded_path = Path(requested[0]["filepath"]) if requested else None
    if downloaded_path is None or not downloaded_path.is_file():
        raise CutterError("The link did not produce a playable video file. Check that the video is public.")
    return downloaded_path, safe_name(str(info.get("title") or "downloaded_video"))
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
venv/bin/pytest tests/shorts/cutter/test_download.py -q && venv/bin/pytest tests/ -q
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/shorts/cutter/util.py app/shorts/cutter/download.py tests/shorts/cutter/test_download.py .gitignore
git commit -m "feat: cutter download module — native-quality yt-dlp with PO tokens"
```

---

### Task 5: `cutter/transcribe.py`

**Files:**
- Create: `app/shorts/cutter/transcribe.py`
- Test (copied+adapted): `tests/shorts/cutter/test_transcribe_retry.py`

**Interfaces:**
- Consumes: `CutterError`.
- Produces: `get_whisper_model()`, `transcribe_multilingual(source: Path, duration: float, silence_windows, language: str | None) -> tuple[str, float, list, list]`, `should_retry_without_vad(...)`, `save_transcript(...)`, `format_srt_time(seconds: float) -> str` — same signatures as in `$SRC/main.py`.

**Steps:**

- [ ] **Step 1: Copy the test and adapt its import**

```bash
cp ~/Downloads/RhymeShortsCutter_Mac/tests/test_transcribe_retry.py tests/shorts/cutter/test_transcribe_retry.py
sed -i '' 's/^from main import /from app.shorts.cutter.transcribe import /' tests/shorts/cutter/test_transcribe_retry.py
sed -i '' 's/^from cutplan import /from app.shorts.cutter.cutplan import /' tests/shorts/cutter/test_transcribe_retry.py
```

- [ ] **Step 2: Run to verify it fails** — `venv/bin/pytest tests/shorts/cutter/test_transcribe_retry.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Create `app/shorts/cutter/transcribe.py`** by moving these blocks from `$SRC/main.py` verbatim, then adjusting only imports/globals:

- `WHISPER_MODEL_NAME = "small"` (line 62), `_WHISPER_MODEL = None` + `_MODEL_LOCK = threading.Lock()` (lines 78-79 — the lock moves here; YOLO gets its own lock in Task 6)
- `get_whisper_model` (lines 154-170) — replace its `HTTPException(status_code=500, detail=…)` raises with `CutterError(…)` keeping the same message text; keep the `faster_whisper` import inside the function (lazy)
- `should_retry_without_vad` (lines 464-485)
- `transcribe_multilingual` (lines 487-566)
- `save_transcript` (lines 568-596), `format_srt_time` (lines 598-603)

Module header:

```python
"""Multilingual Whisper transcription and transcript/SRT output."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from app.shorts.cutter.cutplan import Stanza, TranscriptSegment
from app.shorts.cutter.errors import CutterError
```
(Check the moved bodies for any other names they reference — e.g. if `transcribe_multilingual`/`save_transcript` use `np`, add `import numpy as np`. Resolve every NameError by importing from the same module the name lived in, never by importing FastAPI.)

- [ ] **Step 4: Run tests** — `venv/bin/pytest tests/shorts/cutter/test_transcribe_retry.py -q` then full suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/cutter/transcribe.py tests/shorts/cutter/test_transcribe_retry.py
git commit -m "feat: cutter transcribe module — Whisper loading, transcription, SRT"
```

---

### Task 6: `cutter/render.py` (YOLO analysis + ffmpeg rendering)

**Files:**
- Create: `app/shorts/cutter/render.py`
- Test (copied+adapted): `tests/shorts/cutter/test_colour_fallback.py`

**Interfaces:**
- Consumes: `util.{clamp, even, safe_name}`, `framing.*`, `CutterError`.
- Produces: `require_ffmpeg() -> str`, `source_metadata(source: Path) -> tuple[float, int, int]`, `render_vertical(source, master, smart, temp_dir, camera_motion) -> dict`, `export_clip(master, destination, start, end) -> None`, `analyse_smart_crop(source, camera_motion)`, `colour_subject_x(frame) -> float | None`, dataclasses `CropPoint`, `VisualBeat`, constants `ANALYSIS_FPS`, `CAMERA_SPEED_FRACS`, `DEFAULT_CAMERA_MOTION`, `MIN_BOX_AREA_RATIO`.

**Steps:**

- [ ] **Step 1: Copy the test and adapt imports**

```bash
cp ~/Downloads/RhymeShortsCutter_Mac/tests/test_colour_fallback.py tests/shorts/cutter/test_colour_fallback.py
sed -i '' 's/^from main import /from app.shorts.cutter.render import /' tests/shorts/cutter/test_colour_fallback.py
sed -i '' 's/^from framing import /from app.shorts.cutter.framing import /' tests/shorts/cutter/test_colour_fallback.py
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError`.

- [ ] **Step 3: Create `app/shorts/cutter/render.py`** by moving these blocks from `$SRC/main.py` verbatim (adjusting imports/exceptions only):

- Constants: `ANALYSIS_FPS` (line 61), `CAMERA_SPEED_FRACS`, `DEFAULT_CAMERA_MOTION`, `MIN_BOX_AREA_RATIO` (lines 65-67); module globals `_YOLO_MODEL`, `_YOLO_MODEL_NAME`, `_YOLO_DEVICE` (lines 75-77) plus a fresh `_YOLO_LOCK = threading.Lock()`
- Dataclasses `CropPoint`, `VisualBeat` (lines 87-99)
- `require_ffmpeg` (116-121): `HTTPException` → `CutterError`, message becomes `"FFmpeg was not found. Install it (brew install ffmpeg) and restart Midas."`
- `pick_detection_setup` (123-132), `get_yolo_model` (134-152; `HTTPException` → `CutterError`, keep lazy `ultralytics`/`torch` imports inside)
- `source_metadata` (172-186), `crop_geometry` (188-197), `normalise_camera_motion` (199-202)
- `scene_histogram` (204-211), `character_boxes` (213-239), `colour_subject_x` (241-283), `analyse_smart_crop` (285-385)
- `ffmpeg_filter_path` (387-389), `run_ffmpeg` (391-399; `HTTPException` → `CutterError`), `write_crop_commands` (401-415), `render_vertical` (417-462), `export_clip` (606-618)

Module header:

```python
"""Smart-crop analysis (YOLO + scene/colour heuristics) and ffmpeg rendering."""
from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.shorts.cutter.errors import CutterError
from app.shorts.cutter.framing import (
    FrameSample, apply_colour_fallback, assign_scene_ids, character_beats,
    fill_gaps_per_scene, group_targets, lead_room_offsets, scene_cut_times,
    solve_camera_path, solve_camera_path_hold, split_on_target_jumps,
    PREFERRED_LABELS,
)
from app.shorts.cutter.util import clamp, even, safe_name
```
Note: `cv2`/`numpy` at top level here is fine — `render.py` is only imported lazily (Task 7/8 keep it out of app startup). If YOLO weights (`yolo11m.pt`/`yolo11n.pt`) are referenced by filename in `pick_detection_setup`/`get_yolo_model`, keep the names — ultralytics auto-downloads them to the working directory on first use.

- [ ] **Step 4: Run tests** — moved test + full suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/cutter/render.py tests/shorts/cutter/test_colour_fallback.py
git commit -m "feat: cutter render module — smart-crop analysis and ffmpeg rendering"
```

---

### Task 7: `cutter/pipeline.py` — the public `cut_video()` entry point

**Files:**
- Create: `app/shorts/cutter/pipeline.py`
- Modify: `app/shorts/cutter/__init__.py`
- Test: `tests/shorts/cutter/test_pipeline_api.py`

**Interfaces:**
- Consumes: everything from Tasks 3-6.
- Produces: `cut_video(source: Path, work_dir: Path, preferred_name: str, cut_mode: str = "highlights", camera_motion: str = "calm", progress: Callable[[str, int], None] | None = None) -> dict`. Return dict keys: `clips` (list of `{"path": str, "rank": int, "start_s": float, "end_s": float}`), `message` (str), `language` (str), `cut_mode` (str). Clips + transcript land in `work_dir / "clips"`; scratch in `work_dir / "tmp"` is deleted before returning.
- Produces: `app.shorts.cutter.__init__` re-exports nothing heavy — only `from app.shorts.cutter.errors import CutterError` (lazy-import rule).

**Steps:**

- [ ] **Step 1: Write the failing test** — `tests/shorts/cutter/test_pipeline_api.py`. It exercises the orchestration shape with the heavy stages monkeypatched, which is exactly what the runner depends on:

```python
from pathlib import Path

from app.shorts.cutter.cutplan import Stanza


def test_cut_video_returns_clip_records(tmp_path, monkeypatch):
    import app.shorts.cutter.pipeline as pipeline

    source = tmp_path / "source.mkv"
    source.write_bytes(b"fake")

    def fake_render_vertical(src, master, smart, temp_dir, camera_motion):
        Path(master).write_bytes(b"master")
        return {"mode": "Smart Follow", "scene_cut_times": [], "sample_times": [],
                "sample_targets": [], "camera_xs": [], "crop_size": [None],
                "visual_beats": [], "intended_offsets": []}

    monkeypatch.setattr(pipeline, "render_vertical", fake_render_vertical)
    monkeypatch.setattr(pipeline, "source_metadata", lambda s: (30.0, 1920, 1080))
    monkeypatch.setattr(pipeline, "vocal_silence_analysis", lambda s, t: (_ for _ in ()).throw(RuntimeError("no demucs in test")))
    monkeypatch.setattr(pipeline, "transcribe_multilingual",
                        lambda src, dur, windows, language=None: ("en", 0.9, [], []))
    monkeypatch.setattr(pipeline, "full_coverage_stanzas",
                        lambda *a, **k: [Stanza(start=0.0, end=10.0, text="a"),
                                         Stanza(start=10.0, end=20.0, text="b")])
    monkeypatch.setattr(pipeline, "grade_clips", lambda *a, **k: [
        {"verdict": "PASS", "reasons": []}, {"verdict": "PASS", "reasons": []}])
    monkeypatch.setattr(pipeline, "save_transcript", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "export_clip",
                        lambda master, dest, start, end: Path(dest).write_bytes(b"clip"))

    stages = []
    result = pipeline.cut_video(source, tmp_path / "job", "My_Video",
                                progress=lambda stage, pct: stages.append((stage, pct)))

    assert len(result["clips"]) == 2
    first = result["clips"][0]
    assert first["rank"] == 1 and first["start_s"] == 0.0 and first["end_s"] == 10.0
    assert Path(first["path"]).is_file()
    assert result["language"] == "en"
    assert not (tmp_path / "job" / "tmp").exists()       # scratch cleaned up
    assert any("render" in s for s, _ in stages)         # progress reported
```
Note: if `Stanza`'s constructor differs (check `$SRC/cutplan.py`), build the two stanzas with its real fields — the test must construct them exactly as `cutplan.Stanza` defines.

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError: …pipeline`.

- [ ] **Step 3: Write `app/shorts/cutter/pipeline.py`** — this is `$SRC/main.py:645-805` (`process_video`) with: paths parameterized (`work_dir/clips`, `work_dir/tmp` instead of module-level `OUTPUT_DIR`/`TEMP_DIR`), `smart=True`/`cut_by_stanza=True` fixed (drop those params and the non-stanza early-return branch at lines 676-679), the zip/URL tail (lines 774, 795-802) dropped, and the return shape changed to clip records:

```python
"""Cut a source video into vertical Shorts. Framework-free public entry point."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from app.shorts.cutter.cutplan import (
    MAX_CLIP_SECONDS, Stanza, full_coverage_stanzas, lyric_pause_candidates,
)
from app.shorts.cutter.grading import grade_clips
from app.shorts.cutter.render import (
    DEFAULT_CAMERA_MOTION, export_clip, render_vertical, source_metadata,
)
from app.shorts.cutter.selection import plan_highlights
from app.shorts.cutter.structure import build_structure
from app.shorts.cutter.transcribe import save_transcript, transcribe_multilingual
from app.shorts.cutter.util import safe_name
from app.shorts.cutter.vocals import load_mix_mono, vocal_silence_analysis


def _normalise_cut_mode(value: str | None) -> str:
    value = str(value or "highlights").strip().lower()
    return value if value in {"highlights", "coverage"} else "highlights"


def cut_video(
    source: Path,
    work_dir: Path,
    preferred_name: str,
    cut_mode: str = "highlights",
    camera_motion: str = DEFAULT_CAMERA_MOTION,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    cut_mode = _normalise_cut_mode(cut_mode)

    def _tick(stage: str, percent: int) -> None:
        if progress is not None:
            progress(stage, percent)

    clips_dir = work_dir / "clips"
    temp_job = work_dir / "tmp"
    clips_dir.mkdir(parents=True, exist_ok=True)
    temp_job.mkdir(parents=True, exist_ok=True)
    try:
        master = temp_job / f"{safe_name(preferred_name)}_vertical_master.mp4"
        _tick("analysing framing", 15)
        crop_info = render_vertical(source, master, True, temp_job, camera_motion)

        # ---- body of $SRC/main.py:681-766 goes here VERBATIM, with only these
        # substitutions: `job_folder` -> `clips_dir`, `smart` -> True (it is
        # always smart now), and the `result = {...}` line replaced as below.
        # (duration/vocal/transcription/stanza-planning/grading/save_transcript)
        # ----

        clip_records = []
        for index, stanza in enumerate(stanzas, start=1):
            _tick("rendering clips", 80 + int(15 * (index - 1) / max(len(stanzas), 1)))
            clip_name = f"{safe_name(preferred_name)}_stanza_{index:02}_{int(stanza.start):04d}s.mp4"
            clip_path = clips_dir / clip_name
            export_clip(master, clip_path, stanza.start, stanza.end)
            clip_records.append({
                "path": str(clip_path), "rank": index,
                "start_s": float(stanza.start), "end_s": float(stanza.end),
            })

        passed = sum(1 for g in grades if g["verdict"] == "PASS")
        mode_word = "highlight" if selection_diag is not None else "full-coverage"
        return {
            "clips": clip_records,
            "cut_mode": "highlights" if selection_diag is not None else "coverage",
            "language": language,
            "message": (
                f"{crop_info.get('mode', 'Smart Follow')}: {len(clip_records)} {mode_word} Shorts created. "
                f"{passed} of {len(grades)} clips passed all quality checks."
                + (f" Vocal analysis unavailable ({vocal_error}); cuts unverified." if vocal is None else "")
            ),
        }
    finally:
        shutil.rmtree(temp_job, ignore_errors=True)
```
The `# ---- body …` marker is an instruction to transplant `$SRC/main.py:681-766` literally (vocal analysis, transcription, highlight/coverage stanza planning, `grade_clips`, `save_transcript` — including the `song_structure.json` / `highlight_candidates.json` diagnostic writes, which now land in `clips_dir`). `MAX_CLIP_SECONDS` replaces the old `max_clip_seconds` parameter. Do not paraphrase that body; copy it.

- [ ] **Step 4: Update `app/shorts/cutter/__init__.py`**

```python
from app.shorts.cutter.errors import CutterError

__all__ = ["CutterError"]
```
(`cut_video` is deliberately NOT re-exported here — importing it pulls cv2/torch, and `__init__` must stay light so `app.main` can start without the ML stack.)

- [ ] **Step 5: Run tests** — new test + full suite. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/shorts/cutter/pipeline.py app/shorts/cutter/__init__.py tests/shorts/cutter/test_pipeline_api.py
git commit -m "feat: cutter pipeline — cut_video() public entry point"
```

---

### Task 8: Supabase migration — progress fields

**Files:**
- Create: `supabase/migrations/20260709120000_shorts_local_cutter.sql`

**Interfaces:**
- Produces: columns `shorts_jobs.progress int`, `shorts_jobs.progress_label text`, `shorts_jobs.cut_mode text` used by Tasks 9-11.

**Steps:**

- [ ] **Step 1: Write the migration**

```sql
-- Local shorts cutter (docs/superpowers/specs/2026-07-09-local-shorts-cutter-design.md).
-- Replaces WayinVideo: jobs now run in-process, so the row carries live progress.
-- New status vocabulary: CREATED → DOWNLOADING → ANALYSING → RENDERING →
-- UPLOADING → DONE / FAILED. Historical Wayin statuses (QUEUED, ONGOING,
-- SUCCEEDED) remain on old rows and are treated as terminal by the app.
-- wayinvideo_project_id stays as a dead column; shorts_clips.source_url is
-- null for new rows (clips are local files, local_path is always set).

alter table shorts_jobs add column if not exists progress int not null default 0;
alter table shorts_jobs add column if not exists progress_label text;
alter table shorts_jobs add column if not exists cut_mode text;
alter table shorts_jobs add column if not exists camera_motion text;
```

- [ ] **Step 2: Push and verify**

```bash
cd ~/Documents/Github/Midas && supabase db push
```
Expected: migration applies cleanly. Verify: `venv/bin/python -c "from app.db import supabase; print(supabase().table('shorts_jobs').select('id,progress,progress_label,cut_mode').limit(1).execute().data)"` → no error.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260709120000_shorts_local_cutter.sql
git commit -m "feat: shorts_jobs progress columns for local cutter"
```

---

### Task 9: `app/shorts/runner.py` — job orchestration

**Files:**
- Create: `app/shorts/runner.py`
- Test: `tests/shorts/test_runner.py`

**Interfaces:**
- Consumes: `cut_video` result shape from Task 7, `fetch_video` from Task 4, `upload_short(channel_id, source: str, title, description, tags) -> str` (existing, unchanged).
- Produces: `has_active_job() -> bool`, `start_job_thread(job_id: int) -> threading.Thread`, `run_shorts_job(job_id: int) -> None`, `reap_stuck_jobs() -> int`, `WORKING_STATUSES: tuple[str, ...]`. Task 10's routes and `app.main` depend on exactly these names.

**Steps:**

- [ ] **Step 1: Write the failing tests** — `tests/shorts/test_runner.py`. Follow the house style of `tests/test_sync.py` (MagicMock supabase, recorder pattern):

```python
from unittest.mock import MagicMock, patch


def _fake_sb(job_row, recorder):
    """supabase() stand-in: single() returns job_row; update/insert are recorded."""
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = job_row
        t.select.return_value.in_.return_value.limit.return_value.execute.return_value.data = []

        def _update(fields):
            recorder.append((name, "update", fields))
            u = MagicMock()
            u.eq.return_value.execute.return_value.data = [{}]
            return u

        def _insert(fields):
            recorder.append((name, "insert", fields))
            i = MagicMock()
            i.execute.return_value.data = [{"id": 77, **fields}]
            return i

        t.update.side_effect = _update
        t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


JOB = {"id": 5, "channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ",
       "cut_mode": "highlights", "status": "CREATED"}


def test_run_shorts_job_happy_path(tmp_path):
    recorder = []
    clips = [{"path": str(tmp_path / "c1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0}]
    (tmp_path / "c1.mp4").write_bytes(b"clip")

    with patch("app.shorts.runner.supabase", return_value=_fake_sb(JOB, recorder)), \
         patch("app.shorts.runner._fetch_video", return_value=(tmp_path / "src.mkv", "My_Video")), \
         patch("app.shorts.runner._cut_video", return_value={"clips": clips, "message": "ok", "language": "en", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short", return_value="yt_abc123") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(5)

    up.assert_called_once()
    assert up.call_args.args[0] == "UC123"
    inserts = [(t, f) for t, op, f in recorder if op == "insert"]
    assert inserts and inserts[0][0] == "shorts_clips"
    assert inserts[0][1]["local_path"] == clips[0]["path"]
    job_updates = [f for t, op, f in recorder if t == "shorts_jobs" and op == "update"]
    assert any(u.get("status") == "DOWNLOADING" for u in job_updates)
    assert any(u.get("status") == "UPLOADING" for u in job_updates)
    assert job_updates[-1]["status"] == "DONE"


def test_run_shorts_job_marks_failed_on_error(tmp_path):
    recorder = []
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(JOB, recorder)), \
         patch("app.shorts.runner._fetch_video", side_effect=RuntimeError("boom")), \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(5)

    job_updates = [f for t, op, f in recorder if t == "shorts_jobs" and op == "update"]
    assert job_updates[-1]["status"] == "FAILED"
    assert "boom" in job_updates[-1]["error_message"]


def test_reap_stuck_jobs():
    sb = MagicMock()
    stuck = [{"id": 1}, {"id": 2}]
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = stuck
    with patch("app.shorts.runner.supabase", return_value=sb):
        from app.shorts.runner import reap_stuck_jobs
        assert reap_stuck_jobs() == 2
```

- [ ] **Step 2: Run to verify they fail** — `venv/bin/pytest tests/shorts/test_runner.py -q` → `ModuleNotFoundError: app.shorts.runner`.

- [ ] **Step 3: Write `app/shorts/runner.py`**

```python
"""Local shorts-cutter job orchestration. Replaces the WayinVideo poller.

Jobs run in a plain daemon thread (minutes of CPU: Whisper + YOLO + ffmpeg).
All state lives in the shorts_jobs/shorts_clips tables; the UI polls those.
The cutter itself is imported lazily so app startup never pays the torch tax
and a container without requirements-ml.txt fails with a clear message only
when a job is actually created.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path

from app.config import settings
from app.db import supabase
from app.shorts.youtube_upload import upload_short

log = logging.getLogger("midas.shorts.runner")

WORKING_STATUSES = ("CREATED", "DOWNLOADING", "ANALYSING", "RENDERING", "UPLOADING")


def _fetch_video(url: str, dest_dir: Path):
    from app.shorts.cutter.download import fetch_video
    return fetch_video(url, dest_dir)


def _cut_video(*args, **kwargs):
    from app.shorts.cutter.pipeline import cut_video
    return cut_video(*args, **kwargs)


def _set_job(job_id: int, **fields) -> None:
    supabase().table("shorts_jobs").update(fields).eq("id", job_id).execute()


def has_active_job() -> bool:
    rows = (supabase().table("shorts_jobs").select("id")
            .in_("status", list(WORKING_STATUSES)).limit(1).execute().data) or []
    return bool(rows)


def start_job_thread(job_id: int) -> threading.Thread:
    thread = threading.Thread(target=run_shorts_job, args=(job_id,),
                              daemon=True, name=f"shorts-job-{job_id}")
    thread.start()
    return thread


def run_shorts_job(job_id: int) -> None:
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        log.error("run_shorts_job: job %s not found", job_id)
        return
    job_dir = Path(settings.SHORTS_CACHE_DIR) / str(job_id)
    source = None
    try:
        _set_job(job_id, status="DOWNLOADING", progress=5, progress_label="downloading video")
        source, title = _fetch_video(job["source_url"], job_dir / "src")

        def progress(stage: str, percent: int) -> None:
            status = "RENDERING" if "render" in stage else "ANALYSING"
            _set_job(job_id, status=status, progress=percent, progress_label=stage)

        result = _cut_video(
            source, job_dir, preferred_name=title,
            cut_mode=job.get("cut_mode") or "highlights",
            camera_motion=job.get("camera_motion") or "calm", progress=progress,
        )

        clips = result["clips"]
        _set_job(job_id, status="UPLOADING", progress=95,
                 progress_label=f"uploading {len(clips)} clips to YouTube")
        all_ok = True
        for clip in clips:
            clip_title = f"{title.replace('_', ' ')} — Part {clip['rank']}"[:100]
            row = sb.table("shorts_clips").insert({
                "job_id": job_id, "rank": clip["rank"], "title": clip_title,
                "description": "", "hashtags": ["shorts"],
                "start_s": clip["start_s"], "end_s": clip["end_s"],
                "local_path": clip["path"], "upload_status": "UPLOADING",
            }).execute().data[0]
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

        _set_job(job_id, status="DONE" if all_ok else "FAILED", progress=100,
                 progress_label="done",
                 error_message=None if all_ok else "One or more clips failed to upload")
        _notify_macos("Midas Shorts",
                      f"Job {job_id}: {len(clips)} clips cut, "
                      f"{'all uploaded' if all_ok else 'some uploads FAILED'}")
    except Exception as exc:
        log.exception("Job %s failed", job_id)
        _set_job(job_id, status="FAILED", error_message=str(exc)[:1000])
        _notify_macos("Midas Shorts", f"Job {job_id} failed: {exc}"[:120])
    finally:
        shutil.rmtree(job_dir / "src", ignore_errors=True)
        shutil.rmtree(job_dir / "tmp", ignore_errors=True)


def reap_stuck_jobs() -> int:
    """Fail jobs stranded in a working status by a mid-job server restart."""
    sb = supabase()
    stuck = (sb.table("shorts_jobs").select("id")
             .in_("status", list(WORKING_STATUSES)).execute().data) or []
    for row in stuck:
        sb.table("shorts_jobs").update({
            "status": "FAILED", "error_message": "server restarted mid-job",
        }).eq("id", row["id"]).execute()
    if stuck:
        log.warning("Reaped %d stuck shorts job(s) on startup", len(stuck))
    return len(stuck)


def _notify_macos(title: str, body: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{body}" with title "{title}"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:
        pass  # notification is best-effort
```

- [ ] **Step 4: Run tests** — `venv/bin/pytest tests/shorts/test_runner.py -q` then full suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/runner.py tests/shorts/test_runner.py
git commit -m "feat: shorts runner — background-thread cutter jobs with Supabase progress"
```

---

### Task 10: Rewire routes, delete Wayin, wire startup reaper

**Files:**
- Modify: `app/shorts/routes.py` (full rewrite below)
- Modify: `app/main.py` (reaper call in lifespan)
- Modify: `app/config.py` (delete the `WAYINVIDEO_*` block, lines 41-56; keep `SHORTS_CACHE_DIR` with a reworded comment: `# Working/cache dir for locally cut shorts.`)
- Delete: `app/shorts/wayin_client.py`, `app/shorts/poller.py`, `app/shorts/pipeline.py`, `tests/shorts/test_wayin_client.py`, `tests/shorts/test_pipeline.py`
- Test: `tests/shorts/test_routes.py` (new); keep `tests/shorts/test_youtube_upload.py` as-is

**Interfaces:**
- Consumes: `has_active_job`, `start_job_thread` from Task 9; `is_youtube_url` from Task 4.
- Produces: `POST /shorts/jobs` accepting `{channel_id, source_url, cut_mode?, camera_motion?}` → `{"job_id": int}`; 400 non-YouTube URL, 404 unknown channel, 409 job already running. `GET /shorts/jobs` and `GET /shorts/jobs/{id}` unchanged.

**Steps:**

- [ ] **Step 1: Write the failing tests** — `tests/shorts/test_routes.py`:

```python
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _sb_with_channel(found=True):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        {"id": "UC123"} if found else None)
    tbl.insert.return_value.execute.return_value.data = [{"id": 42}]
    return sb


BODY = {"channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ"}


def test_create_job_starts_thread():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel()), \
         patch("app.shorts.routes.has_active_job", return_value=False), \
         patch("app.shorts.routes.start_job_thread") as start:
        r = _client().post("/shorts/jobs", json={**BODY, "cut_mode": "coverage"})
    assert r.status_code == 200 and r.json() == {"job_id": 42}
    start.assert_called_once_with(42)


def test_create_job_rejects_non_youtube_url():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel()):
        r = _client().post("/shorts/jobs", json={**BODY, "source_url": "https://vimeo.com/1"})
    assert r.status_code == 400


def test_create_job_conflicts_when_job_running():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel()), \
         patch("app.shorts.routes.has_active_job", return_value=True):
        r = _client().post("/shorts/jobs", json=BODY)
    assert r.status_code == 409


def test_create_job_unknown_channel_404():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel(found=False)):
        r = _client().post("/shorts/jobs", json=BODY)
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

```bash
venv/bin/pytest tests/shorts/test_routes.py -q
```
Expected: FAIL (`has_active_job` not in routes / 409 branch missing / cut_mode not accepted).

- [ ] **Step 3: Rewrite `app/shorts/routes.py`** (complete file):

```python
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import supabase
from app.shorts.cutter.download import is_youtube_url
from app.shorts.runner import has_active_job, start_job_thread

log = logging.getLogger("midas.shorts.routes")

router = APIRouter(prefix="/shorts", tags=["shorts"])


class CreateJob(BaseModel):
    channel_id: str
    source_url: str
    cut_mode: str = "highlights"        # highlights | coverage
    camera_motion: str = "calm"         # locked | calm | follow


@router.post("/jobs")
def create_job(body: CreateJob):
    sb = supabase()
    chan = sb.table("channels").select("id").eq("id", body.channel_id).single().execute().data
    if not chan:
        raise HTTPException(404, f"Channel {body.channel_id} not found")
    if not is_youtube_url(body.source_url):
        raise HTTPException(400, "source_url must be a YouTube video link")
    if has_active_job():
        raise HTTPException(409, "A shorts job is already running; wait for it to finish")

    inserted = sb.table("shorts_jobs").insert({
        "channel_id":    body.channel_id,
        "source_url":    body.source_url,
        "cut_mode":      body.cut_mode,
        "camera_motion": body.camera_motion,
        "status":        "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]
    start_job_thread(job_id)
    log.info("Shorts job %d created for %s", job_id, body.source_url)
    return {"job_id": job_id}


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
Note: `app.shorts.cutter.download` imports no ML libs at module level (yt_dlp is lazy inside `fetch_video`), so this keeps startup light.

- [ ] **Step 4: Delete the Wayin modules and their tests**

```bash
git rm app/shorts/wayin_client.py app/shorts/poller.py app/shorts/pipeline.py \
       tests/shorts/test_wayin_client.py tests/shorts/test_pipeline.py
```
Then remove the `WAYINVIDEO_*` settings block from `app/config.py` (the `# WayinVideo …` comment through `WAYINVIDEO_CAPTIONS`, keeping `SHORTS_CACHE_DIR`), and grep for stragglers: `grep -rn "wayin" app/ tests/ --include="*.py" -i` → only historical comments in migrations may remain.

- [ ] **Step 5: Wire the reaper into `app/main.py` lifespan** — inside the `lifespan` function, immediately before `scheduler.start()`:

```python
    from app.shorts.runner import reap_stuck_jobs
    try:
        reap_stuck_jobs()
    except Exception:
        log.exception("Startup reap of stuck shorts jobs failed")
```

- [ ] **Step 6: Run tests** — `venv/bin/pytest tests/ -q`. Expected: PASS (route tests green, no import errors from deleted modules).

- [ ] **Step 7: Commit**

```bash
git add -A app/ tests/
git commit -m "feat: shorts routes drive local cutter; delete WayinVideo integration"
```

---

### Task 11: shorts.html — cut mode toggle + progress bar

**Files:**
- Modify: `app/static/shorts.html`

**Interfaces:**
- Consumes: `POST /shorts/jobs` body with `cut_mode`; `progress`/`progress_label`/`status` fields on job rows from `GET /shorts/jobs`.

**Steps:**

- [ ] **Step 1: Add the cut-mode control** next to the existing URL input in the create-job form (around `app/static/shorts.html:253`'s form):

```html
<select id="cut-mode">
  <option value="highlights" selected>Highlights (best moments)</option>
  <option value="coverage">Full coverage (whole song)</option>
</select>
<select id="camera-motion">
  <option value="locked">Camera: locked</option>
  <option value="calm" selected>Camera: calm</option>
  <option value="follow">Camera: follow</option>
</select>
```
And include both in the create-job fetch body:

```javascript
const cut_mode = document.getElementById('cut-mode').value;
const camera_motion = document.getElementById('camera-motion').value;
// existing fetch('/shorts/jobs', …) body gains: cut_mode, camera_motion
body: JSON.stringify({ channel_id, source_url, cut_mode, camera_motion })
```

- [ ] **Step 2: Add a progress cell to the jobs table renderer** (the row template near `app/static/shorts.html:193`). Working statuses show a bar + label; terminal statuses show the status text as today:

```javascript
const WORKING = ['CREATED', 'DOWNLOADING', 'ANALYSING', 'RENDERING', 'UPLOADING'];
function progressCell(j) {
  if (!WORKING.includes(j.status)) return escapeHtml(j.status);
  const pct = Math.max(0, Math.min(100, j.progress || 0));
  return `<div class="prog"><div class="prog-bar" style="width:${pct}%"></div></div>` +
         `<small>${escapeHtml(j.progress_label || j.status.toLowerCase())} ${pct}%</small>`;
}
```
With CSS matching the page's existing look:

```css
.prog { width: 120px; height: 6px; background: #2a2a2a; border-radius: 3px; overflow: hidden; }
.prog-bar { height: 100%; background: #4caf50; transition: width .5s; }
```
(Adapt colours to the page's existing palette — read the file's `<style>` block and reuse its variables/tones rather than introducing new ones.)

- [ ] **Step 3: Client-side URL check** — before the create fetch, mirror the server regex loosely: if the URL doesn't contain `youtube.com/watch`, `youtube.com/shorts/`, or `youtu.be/`, show the page's existing error style instead of posting.

- [ ] **Step 4: Manual check** — start the server (`venv/bin/uvicorn app.main:app --port 8000`), open `http://localhost:8000/shorts`, confirm: mode dropdown renders, job list still renders, no console errors. (Job creation is exercised for real in Task 12.)

- [ ] **Step 5: Commit**

```bash
git add app/static/shorts.html
git commit -m "feat: shorts page — cut-mode toggle and live progress bar"
```

---

### Task 12: End-to-end verification, then archive the source repo

**Files:**
- Modify (final commit): `~/Downloads/RhymeShortsCutter_Mac/README.md`

**Steps:**

- [ ] **Step 1: Full-suite check** — `venv/bin/pytest tests/ -q` → green.

- [ ] **Step 2: Real end-to-end run** — this is the spec's definition of done. Start the server, then via the `/shorts` page (or curl) create a job with a real YouTube URL on the connected channel:

```bash
curl -s -X POST localhost:8000/shorts/jobs -H 'content-type: application/json' \
  -d '{"channel_id": "<connected channel id>", "source_url": "<real video url>", "cut_mode": "highlights"}'
```
Verify, in order:
1. Job row advances DOWNLOADING → ANALYSING → RENDERING → UPLOADING → DONE (watch the UI progress bar; `watch curl -s localhost:8000/shorts/jobs/<id>` also works).
2. Downloaded source in `shorts_cache/<id>/src/` is native quality (check `ffprobe` height matches the video's max published resolution), and is deleted after the job finishes.
3. Clips exist in `shorts_cache/<id>/clips/` as 9:16 mp4s.
4. `shorts_clips` rows have `upload_status=UPLOADED` and `yt_video_id` set; the videos appear in YouTube Studio as **private** shorts.
5. A second `POST /shorts/jobs` while the job runs returns 409.
6. macOS notification fired on completion.

If any step fails: STOP, debug, fix, re-run. Do not proceed to archiving with a failing E2E.

- [ ] **Step 3: Archive the source repo** — only after Step 2 passes. The old repo has no GitHub remote, so archiving is a final marker commit:

```bash
cd ~/Downloads/RhymeShortsCutter_Mac
cat >> README.md <<'EOF'

---

## ⚠️ Moved

This pipeline now lives inside **Midas** (`~/Documents/Github/Midas`,
github.com/JugaadChhabra/Midas) as `app/shorts/cutter/`. This repo is frozen
as of 2026-07-09; do not develop here.
EOF
git add README.md && git commit -m "docs: frozen — pipeline moved into Midas app/shorts/cutter"
```

- [ ] **Step 4: Update project memory** — note in the Claude memory index that the cutter now lives in Midas and the RhymeShortsCutter repo is frozen.
