# Shorts Cutter Slice 0 — Extraction + Modal Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove *YouTube URL → vertical shorts in R2* end-to-end from a script, in a fresh `shorts-cutter` repo whose engine was extracted from Midas with full git history, and benchmark Modal's cold-start.

**Architecture:** Extract the framework-free `app/shorts/cutter/*` leaf (verified: only external reach is one `BGUTIL_POT_HTTP_BASE_URL` env var) into a new repo as `engine/`, history-preserved via `git filter-repo`. Wrap `engine.download.fetch_video()` + `engine.cut_video()` as a Modal L4 GPU function; upload the produced clips to Cloudflare R2. No auth, no UI, no billing — this slice proves the compute path and settles the cold-start question.

**Tech Stack:** Python 3.11+, Modal (serverless GPU), Cloudflare R2 (boto3 S3 client), yt-dlp + bgutil POT provider + Node runtime + residential proxy, the existing ML stack (torch/demucs/faster-whisper/ultralytics/opencv/librosa).

## Global Constraints

- **Engine is untouched logic:** the only edits to extracted engine files are the import-path rename `app.shorts.cutter.X` → `engine.X`. No behavior changes in this slice.
- **Import seam:** `engine` imports nothing from `worker`. `worker` imports `engine`. Nothing in this repo imports `app.*` (the Midas namespace must not survive extraction).
- **Midas is never modified.** All `filter-repo` surgery happens on a throwaway clone.
- **yt-dlp pin is exact:** `yt-dlp==2026.6.9` (newer releases broke YouTube extraction — not a floor).
- **POT provider version-matched:** `bgutil-ytdlp-pot-provider==1.3.1` plugin ↔ same-version POT server. A skew mints unusable tokens.
- **JS runtime required in the worker image:** without Node/Deno, yt-dlp cannot solve YouTube's n-challenge and every video reports "not available".
- **GPU tier:** L4 (`gpu="L4"` on Modal). Fallback platform if cold-start is unacceptable: RunPod Serverless.
- **Repo creation is the user's action:** this slice produces a ready *local* repo; the user creates the GitHub remote and pushes.

## Prerequisites (user must provision before execution)

These need real accounts/credentials the implementer cannot create:

- **Modal account** + `modal token new` run locally (CLI auth).
- **Cloudflare R2 bucket** + S3 credentials: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
- **Residential proxy** endpoint + creds (`PROXY_URL`) for YouTube downloads from Modal's shared IPs.
- **A short test YouTube URL** (a music video ≤ 2 min) for the end-to-end run.
- `pip install git-filter-repo` (confirmed **not** currently installed).

## File Structure (new `shorts-cutter` repo)

- `engine/` — lifted verbatim from `app/shorts/cutter/*` (13 modules), imports renamed. Owns the ML pipeline + YouTube download.
- `tests/` — lifted from `tests/shorts/cutter/*` (15 files). The extraction correctness gate.
- `worker/modal_app.py` — Modal app: image definition + the `run_job` GPU function. The only place ML + download deps install.
- `worker/r2.py` — R2 upload helper (`upload_clips`). No ML deps.
- `scripts/run_job.py` — local driver: URL → invoke Modal → print R2 URLs.
- `scripts/benchmark_coldstart.py` — cold-start measurement harness.
- `requirements-engine.txt` — the ML stack (from Midas `requirements-ml.txt`).
- `requirements-download.txt` — `yt-dlp==2026.6.9`, `bgutil-ytdlp-pot-provider==1.3.1`.
- `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`.
- `docs/COLDSTART-RESULTS.md` — written by the benchmark; the Modal-vs-RunPod decision record.

---

### Task 1: Extract the engine with history preserved

**Files:**
- Create: the entire new `shorts-cutter` repo (from filtered Midas history)
- Uses: a throwaway clone of Midas (never the working copy)

**Interfaces:**
- Produces: a local git repo containing only `app/shorts/cutter/*` and `tests/shorts/cutter/*` with full commit history/blame.

- [ ] **Step 1: Install git-filter-repo**

Run: `pip install git-filter-repo`
Expected: `git filter-repo --version` prints a version.

- [ ] **Step 2: Make a throwaway clone of Midas (safety)**

```bash
cd /tmp
rm -rf midas-extract
git clone /Users/jugaadchhabra/Documents/Github/Midas midas-extract
cd midas-extract
```
Expected: a full clone at `/tmp/midas-extract`. The real repo is never touched by later steps.

- [ ] **Step 3: Filter to only the cutter + its tests, preserving history**

```bash
cd /tmp/midas-extract
git filter-repo --path app/shorts/cutter --path tests/shorts/cutter --force
```
Expected: history now contains only those two paths.

- [ ] **Step 4: Verify history/blame survived**

Run: `git log --oneline -- app/shorts/cutter | wc -l` and `git log --follow --oneline app/shorts/cutter/pipeline.py | head`
Expected: multiple commits (not a single squashed commit); `pipeline.py` shows its real authored history.

- [ ] **Step 5: Create the new repo directory and move the filtered tree in**

```bash
mkdir -p ~/Documents/Github/shorts-cutter
cd ~/Documents/Github/shorts-cutter
git init -b main
git remote add origin /tmp/midas-extract
git pull origin main --no-edit
git remote remove origin
```
Expected: `git log` in `shorts-cutter` shows the preserved cutter history; working tree has `app/shorts/cutter/` and `tests/shorts/cutter/`.

- [ ] **Step 6: Commit the checkpoint**

```bash
git add -A && git commit -m "chore: import cutter engine from Midas (history-preserved)" --allow-empty
```

---

### Task 2: Rename package to `engine` and relocate tests

**Files:**
- Modify: move `app/shorts/cutter/` → `engine/`, `tests/shorts/cutter/` → `tests/`
- Modify: all 13 import sites `from app.shorts.cutter.X` → `from engine.X`

**Interfaces:**
- Produces: `import engine`, `from engine.pipeline import cut_video`, `from engine.download import fetch_video, is_youtube_url, refresh_pot_provider` all resolve.

- [ ] **Step 1: Establish the Midas test baseline (what "green" means)**

In the *Midas* repo run the cutter tests and record the pass/fail profile (Midas memory notes ~9 cv2/librosa offline failures are pre-existing):
Run: `cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/shorts/cutter -q | tail -5`
Expected: note the exact passed/failed counts — this is the baseline the extracted repo must match (no *new* failures).

- [ ] **Step 2: Move the directories with git (preserve per-file history)**

```bash
cd ~/Documents/Github/shorts-cutter
git mv app/shorts/cutter engine
git mv tests/shorts/cutter tests
rmdir app/shorts app 2>/dev/null; rmdir tests/shorts 2>/dev/null || true
```
Expected: `engine/` and `tests/` exist at repo root; `app/` gone.

- [ ] **Step 3: Rewrite the import paths**

```bash
cd ~/Documents/Github/shorts-cutter
grep -rl "app.shorts.cutter" engine tests | xargs sed -i '' 's/app\.shorts\.cutter/engine/g'
```
(Linux: use `sed -i` without the `''`.)

- [ ] **Step 4: Verify no Midas namespace survives**

Run: `grep -rn "app.shorts.cutter\|from app\b\|import app\b" engine tests`
Expected: **no output** (empty). Any hit is a failed rename.

- [ ] **Step 5: Run the extracted tests — the correctness gate**

Run: `cd ~/Documents/Github/shorts-cutter && python -m pytest tests -q | tail -5`
Expected: pass/fail profile **matches the Task-2 Step-1 baseline** (same tests pass; only the known pre-existing cv2/librosa offline failures remain). No new failures, no import errors.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor: rename cutter package app.shorts.cutter -> engine"
```

---

### Task 3: Repo scaffolding + dependency split

**Files:**
- Create: `requirements-engine.txt`, `requirements-download.txt`, `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`

**Interfaces:**
- Produces: a fresh venv can `pip install -r requirements-engine.txt` and `import engine` succeeds (import-only; ML model downloads happen at runtime).

- [ ] **Step 1: Write `requirements-engine.txt` (copied pins from Midas requirements-ml.txt)**

```
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
```

- [ ] **Step 2: Write `requirements-download.txt`**

```
yt-dlp==2026.6.9
bgutil-ytdlp-pot-provider==1.3.1
```

- [ ] **Step 3: Write `.env.example`**

```
BGUTIL_POT_HTTP_BASE_URL=http://127.0.0.1:4416
PROXY_URL=
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=shorts-cutter-output
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.pyc
.env
.venv/
work/
*.mp4
```

- [ ] **Step 5: Write a minimal `pyproject.toml`**

```toml
[project]
name = "shorts-cutter"
version = "0.0.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 6: Write `README.md`** — one paragraph: what it is (YouTube URL → vertical shorts), the `engine`/`worker` seam, and "engine extracted from Midas, history-preserved."

- [ ] **Step 7: Verify a clean import**

```bash
python -m venv /tmp/sc-venv && /tmp/sc-venv/bin/pip install -q -r requirements-engine.txt
/tmp/sc-venv/bin/python -c "import engine; from engine.pipeline import cut_video; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "chore: repo scaffolding + dependency split (engine vs download)"
```

---

### Task 4: Modal image with ML + YouTube-download runtime

**Files:**
- Create: `worker/modal_app.py` (image definition portion)

**Interfaces:**
- Produces: a Modal `Image` object `sc_image` with ML deps, yt-dlp, the bgutil POT provider server, a Node runtime, and ffmpeg installed; and a started POT provider reachable at `BGUTIL_POT_HTTP_BASE_URL`.

- [ ] **Step 1: Define the image (Node + ffmpeg + Python deps + POT server)**

```python
import modal

sc_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "curl", "ca-certificates", "gnupg")
    # Node runtime — required for yt-dlp's n-challenge JS solver
    .run_commands(
        "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
        "apt-get install -y nodejs",
    )
    # bgutil POT provider server (version-matched to the plugin, 1.3.1)
    .run_commands("npm install -g bgutil-ytdlp-pot-provider@1.3.1")
    .pip_install_from_requirements("requirements-engine.txt")
    .pip_install_from_requirements("requirements-download.txt")
    .add_local_python_source("engine")
)

app = modal.App("shorts-cutter")
```

- [ ] **Step 2: Verify the image builds**

Run: `modal run worker/modal_app.py::_noop` (add a tiny `@app.function(image=sc_image) def _noop(): return "ok"` temporarily)
Expected: image builds and prints `ok`. Node present: extend `_noop` to `subprocess.run(["node","--version"])` and confirm it prints a v20 version.

- [ ] **Step 3: Commit**

```bash
git add worker/modal_app.py && git commit -m "feat(worker): Modal image with ML + yt-dlp + POT provider + Node"
```

---

### Task 5: Modal GPU function — download + cut_video

**Files:**
- Modify: `worker/modal_app.py` (add `run_job`)

**Interfaces:**
- Consumes: `engine.download.fetch_video(url, dest_dir) -> tuple[Path, str]`, `engine.pipeline.cut_video(source: Path, work_dir: Path, preferred_name: str, ...) -> dict` (writes clips to `work_dir/clips`), `engine.download.refresh_pot_provider(base_url=None)`.
- Produces: `run_job.remote(youtube_url: str) -> list[bytes]` returning the rendered clip file bytes (uploaded to R2 in Task 6; returned as bytes here so this task is testable without R2).

- [ ] **Step 1: Start the POT server in-container, then download + cut**

```python
import os, subprocess, time
from pathlib import Path

@app.function(image=sc_image, gpu="L4", timeout=1800,
              secrets=[modal.Secret.from_name("shorts-cutter")])
def run_job(youtube_url: str) -> list[bytes]:
    from engine.download import fetch_video, refresh_pot_provider
    from engine.pipeline import cut_video

    base = os.environ.setdefault("BGUTIL_POT_HTTP_BASE_URL", "http://127.0.0.1:4416")
    server = subprocess.Popen(["bgutil-pot-server", "--port", "4416"])
    time.sleep(3)
    refresh_pot_provider(base)

    work = Path("/tmp/work"); (work / "clips").mkdir(parents=True, exist_ok=True)
    source, _title = fetch_video(youtube_url, work)
    cut_video(source, work, preferred_name="short", cut_mode="highlights")

    clips = sorted((work / "clips").glob("*.mp4"))
    server.terminate()
    return [c.read_bytes() for c in clips]
```
(If the bgutil server binary name differs, resolve it from `npm ls -g` output during Task 4; adjust `["bgutil-pot-server", ...]` accordingly.)

- [ ] **Step 2: Run end-to-end against the test URL**

Run: `modal run worker/modal_app.py::run_job --youtube-url "<SHORT_TEST_URL>"`
Expected: completes without "video not available"; returns a non-empty list; log shows the pipeline stages (analysing framing → separating vocals → transcribing → planning cuts → rendering).

- [ ] **Step 3: Troubleshooting gate (only if Step 2 fails)**

If "video not available": check the Modal log for `JS runtimes: none` (→ Node not on PATH in the GPU function — fix image) or token errors (→ POT server/plugin version skew or proxy needed). Add `PROXY_URL` to the `shorts-cutter` Modal secret and thread it into `ytdlp_options()` if YouTube blocks Modal IPs.

- [ ] **Step 4: Commit**

```bash
git add worker/modal_app.py && git commit -m "feat(worker): run_job GPU function (download + cut_video)"
```

---

### Task 6: Upload output clips to R2

**Files:**
- Create: `worker/r2.py`
- Modify: `worker/modal_app.py` (call `upload_clips`, return keys/URLs instead of bytes)

**Interfaces:**
- Consumes: R2 secret env (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`).
- Produces: `upload_clips(clip_paths: list[Path], job_id: str) -> list[str]` returning presigned download URLs.

- [ ] **Step 1: Write the failing test for the key layout (pure function, no network)**

```python
# tests/test_r2_keys.py
from worker.r2 import clip_key
def test_clip_key_layout():
    assert clip_key("job123", 0) == "jobs/job123/clip_000.mp4"
    assert clip_key("job123", 12) == "jobs/job123/clip_012.mp4"
```

- [ ] **Step 2: Run it, expect failure**

Run: `python -m pytest tests/test_r2_keys.py -v`
Expected: FAIL (`worker.r2` / `clip_key` not defined).

- [ ] **Step 3: Implement `worker/r2.py`**

```python
import os
from pathlib import Path
import boto3

def clip_key(job_id: str, index: int) -> str:
    return f"jobs/{job_id}/clip_{index:03d}.mp4"

def _client():
    acct = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )

def upload_clips(clip_paths: list[Path], job_id: str) -> list[str]:
    s3, bucket, urls = _client(), os.environ["R2_BUCKET"], []
    for i, path in enumerate(clip_paths):
        key = clip_key(job_id, i)
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": "video/mp4"})
        urls.append(s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=86400))
    return urls
```

- [ ] **Step 4: Run the test, expect pass**

Run: `python -m pytest tests/test_r2_keys.py -v`
Expected: PASS. Add `boto3` to `requirements-download.txt`.

- [ ] **Step 5: Wire into `run_job`**

Replace the `return [c.read_bytes() ...]` with:
```python
from worker.r2 import upload_clips
return upload_clips(clips, job_id=youtube_url.split("=")[-1][:11] or "job")
```
Add `worker` to the Modal image via `.add_local_python_source("engine", "worker")`.

- [ ] **Step 6: Run end-to-end → clips land in R2**

Run: `modal run worker/modal_app.py::run_job --youtube-url "<SHORT_TEST_URL>"`
Expected: returns presigned URLs; opening one downloads a playable vertical `.mp4`; the objects appear in the R2 bucket.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(worker): upload output clips to R2, return presigned URLs"
```

---

### Task 7: End-to-end driver script + cold-start benchmark

**Files:**
- Create: `scripts/run_job.py`, `scripts/benchmark_coldstart.py`, `docs/COLDSTART-RESULTS.md`

**Interfaces:**
- Consumes: `run_job` (Modal function).
- Produces: `docs/COLDSTART-RESULTS.md` — the Modal-vs-RunPod decision record (the spec's Slice-0 gate).

- [ ] **Step 1: Write `scripts/run_job.py`**

```python
import sys
from worker.modal_app import run_job
if __name__ == "__main__":
    urls = run_job.remote(sys.argv[1])
    print("\n".join(urls))
```
Run: `python scripts/run_job.py "<SHORT_TEST_URL>"` → prints presigned URLs.

- [ ] **Step 2: Write `scripts/benchmark_coldstart.py`**

Measure wall-clock for (a) a cold invocation (after Modal has scaled to zero — wait > the container idle window, or use a fresh app deploy) and (b) a warm invocation immediately after. Repeat cold measurement 3×.

```python
import time, statistics, sys
from worker.modal_app import run_job

def timed(url):
    t = time.monotonic(); run_job.remote(url); return time.monotonic() - t

if __name__ == "__main__":
    url = sys.argv[1]
    warm = timed(url)                      # container now warm
    colds = []
    for _ in range(3):
        input("Wait for scale-to-zero (idle window), then press Enter for a COLD run...")
        colds.append(timed(url))
    print(f"warm={warm:.1f}s cold_median={statistics.median(colds):.1f}s colds={colds}")
```

- [ ] **Step 3: Run the benchmark and record results**

Run: `python scripts/benchmark_coldstart.py "<SHORT_TEST_URL>"`
Write `docs/COLDSTART-RESULTS.md` with: warm time, cold median, the 3 cold samples, and a verdict line — **"Modal cold-start acceptable for a paid product? YES/NO. If NO → switch worker to RunPod Serverless (spec fallback)."** Acceptance heuristic: cold overhead (cold − warm) under ~30s is fine; a job already takes tens of seconds and users see live progress.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: end-to-end run script + cold-start benchmark + results"
```

- [ ] **Step 5: Hand off to the user for repo creation**

Slice 0 is a local, tests-green, video-in/clips-out repo. Tell the user the results and hand them the push step (they own the outward-facing GitHub remote):
```bash
# user runs, choosing name/visibility:
gh repo create shorts-cutter --private --source=. --remote=origin --push
```

---

## Self-Review

**1. Spec coverage (Slice 0 scope only):**
- History-preserving extraction → Tasks 1–2 ✅
- Import seam / no `app.*` survival → Task 2 Step 4 ✅
- Dependency split (engine vs download; web carries no ML) → Task 3 ✅
- Revive YouTube download (yt-dlp pin, POT version-match, Node runtime, proxy) → Tasks 3–5 + Global Constraints ✅
- Modal L4 wrapper of `cut_video` → Tasks 4–5 ✅
- R2 output + presigned download → Task 6 ✅
- Prove "video in → clips out, no UI" → Tasks 5–7 ✅
- Cold-start benchmark = the Slice-0 gate → Task 7 ✅
- Repo creation is user's action → Task 7 Step 5 ✅
- (Auth, credits, billing, landing = Slices 1–4, out of scope for this plan.)

**2. Placeholder scan:** Concrete commands/code throughout. The two intentional `<...>` are the user-supplied test URL and credentials, listed in Prerequisites — not plan placeholders. The bgutil server binary name has an explicit resolution step (Task 5 Step 1 note) rather than an assumption.

**3. Type consistency:** `cut_video(source, work_dir, preferred_name, ...)` and `fetch_video(url, dest_dir) -> (Path, str)` match the verified Midas signatures. `clip_key(job_id, index) -> str` and `upload_clips(paths, job_id) -> list[str]` are consistent between test (Task 6 Step 1), implementation (Step 3), and caller (Step 5).
