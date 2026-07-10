# Shorts Docker Deployment (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the local shorts cutter (and autopilot shorts) run inside Midas's deployed Docker image on the dedicated Windows/amd64 machine, so `docker compose up -d` gives a working end-to-end cutter.

**Architecture:** The prebuilt image `ghcr.io/jugaadchhabra/midas:latest` (CI-built on push to main, pulled by the machine's `docker compose up -d`) gains the ML stack (CPU torch). The bgutil PO-token provider runs as an HTTP **sidecar** container (not the local node script), and `download.py` gains an HTTP-provider mode selected by an env var. Clips persist on a named volume. CI builds amd64-only.

**Tech Stack:** Docker, docker-compose, GitHub Actions (docker-publish.yml), yt-dlp bgutil HTTP provider, the ported cutter.

**Spec:** `docs/superpowers/specs/2026-07-09-shorts-entrypoints-design.md` (Phase A).

## Global Constraints

- Target machine: Windows "DESIGN-PC7", **amd64/x86_64** (Ryzen 9 7900X, 32 GB RAM, ~144 GB free disk), Docker Desktop (Linux containers via WSL2). **CPU-only cuts** — do NOT add CUDA/GPU (the pipeline is tuned for CPU byte-determinism; RTX 3050 is a future option, not v1).
- Deploy flow: push to main → GitHub Actions `docker-publish.yml` builds+pushes `ghcr.io/jugaadchhabra/midas:latest` → machine runs `docker compose up -d` (`pull_policy: always`). Compose + `.env` live in the repo, so the machine must `git pull` the updated compose/.env before `up -d`.
- Branch: fresh branch off main. Python venv `venv/`, tests `venv/bin/pytest`.
- The cutter package stays framework-free; only `download.py` changes (add HTTP-provider mode). Startup must stay light (no eager cv2/torch on `import app.main`).
- Full suite green before each commit (162 on main after B2 merges; this plan assumes B2 is merged first).
- Commit messages end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: `download.py` — HTTP PO-token provider mode

**Files:**
- Modify: `app/shorts/cutter/download.py`
- Test: `tests/shorts/cutter/test_download.py`

**Interfaces:**
- Produces: `ytdlp_options()` uses the bgutil **HTTP** provider (`youtubepot-bgutilhttp`) when env `BGUTIL_POT_HTTP_BASE_URL` is set (Docker); otherwise falls back to the local **script** provider (`youtubepot-bgutilscript`) when the script file exists (Mac); otherwise neither (graceful degradation).

- [ ] **Step 1: Write the failing tests** — add to `tests/shorts/cutter/test_download.py`:

```python
def test_ytdlp_options_uses_http_provider_when_env_set(monkeypatch):
    monkeypatch.setenv("BGUTIL_POT_HTTP_BASE_URL", "http://bgutil-provider:4416")
    from app.shorts.cutter.download import ytdlp_options
    opts = ytdlp_options()
    ea = opts["extractor_args"]
    assert ea["youtubepot-bgutilhttp"]["base_url"] == ["http://bgutil-provider:4416"]
    assert "youtubepot-bgutilscript" not in ea   # HTTP takes precedence over script


def test_ytdlp_options_falls_back_to_script_when_env_absent(monkeypatch):
    monkeypatch.delenv("BGUTIL_POT_HTTP_BASE_URL", raising=False)
    from app.shorts.cutter.download import ytdlp_options, BGUTIL_POT_SCRIPT
    opts = ytdlp_options()
    ea = opts["extractor_args"]
    assert "youtubepot-bgutilhttp" not in ea
    # script provider present iff the local script exists (env-independent, matches CI)
    assert ("youtubepot-bgutilscript" in ea) == BGUTIL_POT_SCRIPT.is_file()
```

- [ ] **Step 2: Run to verify they fail** — `venv/bin/pytest tests/shorts/cutter/test_download.py -q` → FAIL (`youtubepot-bgutilhttp` KeyError).

- [ ] **Step 3: Implement.** Add `import os` at the top of `download.py`, and change `ytdlp_options()`'s provider-selection tail (the `if BGUTIL_POT_SCRIPT.is_file():` block) to:

```python
    http_base = os.getenv("BGUTIL_POT_HTTP_BASE_URL")
    if http_base:
        # Docker: a bgutil-provider sidecar mints tokens over HTTP.
        options["extractor_args"]["youtubepot-bgutilhttp"] = {"base_url": [http_base]}
    elif BGUTIL_POT_SCRIPT.is_file():
        # Mac: mint tokens per request via the local node script.
        options["extractor_args"]["youtubepot-bgutilscript"] = {
            "script_path": [str(BGUTIL_POT_SCRIPT)],
        }
    return options
```

- [ ] **Step 4: Run tests** — `venv/bin/pytest tests/shorts/cutter/test_download.py -q && venv/bin/pytest tests/ -q`. Expected PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/cutter/download.py tests/shorts/cutter/test_download.py
git commit -m "feat: download supports bgutil HTTP PO-token provider (Docker) with local-script fallback"
```

---

### Task 2: Dockerfile — install the ML stack (CPU torch)

**Files:**
- Modify: `Dockerfile`

**Interfaces:**
- Produces: an image with torch/opencv/faster-whisper/ultralytics/demucs importable, CPU-only, ffmpeg present. No node (HTTP provider is a sidecar).

- [ ] **Step 1: Edit `Dockerfile`.** After the existing `RUN pip install --no-cache-dir -r requirements.txt` line, add a CPU-torch install then the rest of the ML deps:

```dockerfile
# Local shorts cutter ML stack (CPU-only — see docs Phase A). Install torch from
# the CPU wheel index so the image doesn't pull ~2 GB of unused CUDA libs, then
# the remaining ML deps. ffmpeg is already installed above.
COPY requirements-ml.txt .
RUN pip install --no-cache-dir torch==2.12.1 torchvision==0.27.1 torchaudio==2.11.0 \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements-ml.txt
```
(The second install sees torch/vision/audio already satisfied at the pinned versions and installs the rest — opencv, faster-whisper, ultralytics, demucs, bgutil-ytdlp-pot-provider, etc.)

- [ ] **Step 2: Local build smoke-test** (Docker Desktop must be running; this is a real build, several minutes):

```bash
cd ~/Documents/Github/Midas
docker build --platform linux/amd64 -t midas-mltest .
docker run --rm --platform linux/amd64 midas-mltest python -c "import torch, cv2, faster_whisper, ultralytics, demucs, yt_dlp; print('ml ok', torch.__version__)"
```
Expected: `ml ok 2.12.1`. If the CPU torch wheel for cp313/linux-amd64 isn't found, STOP and report — may need a torch version bump for the CPU index.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat: Dockerfile installs CPU torch + shorts-cutter ML stack"
```

---

### Task 3: docker-compose — bgutil sidecar, cache volume, env

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example` (add the new var; drop dead `WAYINVIDEO_*` keys)

**Interfaces:**
- Produces: a `bgutil-provider` sidecar service; the `midas` service gets `BGUTIL_POT_HTTP_BASE_URL=http://bgutil-provider:4416`, `SHORTS_CACHE_DIR=/app/shorts_cache`, and a `shorts_cache` named volume mounted there.

- [ ] **Step 1: Edit `docker-compose.yml`.** Add the sidecar service, and extend the `midas` service's `environment` and `volumes`:

```yaml
services:
  midas:
    # ...existing image/ports/env_file...
    environment:
      CLIENT_SECRETS_FILE: /app/client_secret.json
      KEYFRAMES_LOCAL_DIR: /app/storage/keyframes
      BGUTIL_POT_HTTP_BASE_URL: http://bgutil-provider:4416
      SHORTS_CACHE_DIR: /app/shorts_cache
    volumes:
      - ./client_secret.json:/app/client_secret.json:ro
      - midas_storage:/app/storage
      - shorts_cache:/app/shorts_cache
    depends_on:
      - bgutil-provider
    # ...existing restart/healthcheck...

  bgutil-provider:
    image: brainicism/bgutil-ytdlp-pot-provider:latest
    container_name: bgutil-provider
    restart: unless-stopped
    # serves PO tokens on :4416 inside the compose network; no host port needed

volumes:
  midas_storage:
  shorts_cache:
```

- [ ] **Step 2: Edit `.env.example`.** Remove the `WAYINVIDEO_*` block (dead since the port). `BGUTIL_POT_HTTP_BASE_URL` and `SHORTS_CACHE_DIR` are set in compose `environment:` so they don't need `.env` entries, but add a documented commented line:

```
# Set in docker-compose.yml (bgutil sidecar). Leave unset on the Mac to use the local node script.
# BGUTIL_POT_HTTP_BASE_URL=http://bgutil-provider:4416
```

- [ ] **Step 3: Validate compose syntax**

```bash
cd ~/Documents/Github/Midas && docker compose config >/dev/null && echo "compose valid"
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: compose adds bgutil PO-token sidecar, shorts_cache volume, provider env; drop dead WAYINVIDEO vars"
```

---

### Task 4: CI — build amd64-only

**Files:**
- Modify: `.github/workflows/docker-publish.yml`

**Interfaces:**
- Produces: the published `ghcr.io/jugaadchhabra/midas:latest` is a single-arch **linux/amd64** image (the heavy ML image is not QEMU-emulated for arm64).

- [ ] **Step 1: Edit the build step.** Change `platforms: linux/amd64,linux/arm64` to `platforms: linux/amd64`. (The QEMU setup step can stay; it's a no-op for a single native arch.)

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/docker-publish.yml
git commit -m "ci: build midas image amd64-only (ML image too heavy to emulate arm64)"
```

- [ ] **Step 3: Note on CI build time.** The first ML image build will be slow (large layers). GHA layer cache (`cache-from/to: type=gha` already configured) makes subsequent builds fast. If the build exceeds the runner time limit, split the ML pip install into its own cached layer (already the case — it's a distinct `RUN`).

---

### Task 5: Merge to main + deployed end-to-end (USER-driven)

**Files:** none (deploy + verify).

- [ ] **Step 1: Merge this branch to main and push.** CI builds+pushes the new `:latest` (amd64, ML). Watch the Tests + Build-and-Push workflows go green (`gh run watch`). The ML build is slow the first time.

- [ ] **Step 2: On DESIGN-PC7 (Windows):**
  1. `git pull` in the Midas repo checkout (to get the updated `docker-compose.yml` / `.env.example`).
  2. Ensure `.env` has the real secrets (Supabase, OpenRouter, client_secret.json present).
  3. `docker compose pull && docker compose up -d`.
  4. `docker compose ps` — both `midas` and `bgutil-provider` healthy.
  5. `docker compose logs -f midas` — confirm startup complete, autopilot scheduler started, no import errors.

- [ ] **Step 3: Backfill duration + verify the manual path.** In the dashboard for a connected channel, trigger a **full sync** (so existing videos get `duration_seconds` populated for the autopilot picker). Then use the per-video **"Make shorts"** button on a long-form video and confirm the job walks DOWNLOADING→…→DONE and uploads clips as private (this proves the cutter + ffmpeg + the bgutil HTTP provider all work in the container).

- [ ] **Step 4: Verify autopilot shorts fires.** Enable "Auto-generate shorts" on a channel (videos/day=1). Within a tick or two, confirm a `shorts_jobs` row with `autopilot_generated=true` appears for the newest un-cut long-form video **under 4 min**, and that compilations are skipped. Confirm top-N upload (only the cap's worth of clips upload; the rest sit PENDING).

- [ ] **Step 5: Disk check.** After a few cuts, `docker system df` and check the `shorts_cache` volume size. If it grows unbounded, add a periodic cleanup (out of scope here — note it as an ops follow-up: prune `shorts_cache/<job>` dirs older than N days).

## Out of scope (follow-ups)

- GPU/CUDA acceleration (RTX 3050) — CPU-only for v1.
- Automatic `shorts_cache` retention/pruning (manual/ops for now).
- A one-off duration backfill for old videos (the full-sync in Step 3 covers it per channel).
