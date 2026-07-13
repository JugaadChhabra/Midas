# Parallel Shorts Generation — Worker-Pool Queue + CUDA

**Date:** 2026-07-13
**Status:** Approved direction, pre-implementation

## In one line

Run up to N shorts-cutter jobs at once (default 2) via a DB-backed queue drained by isolated worker subprocesses, and move YOLO detection onto the NVIDIA GPU.

## Why

Today shorts generation is strictly **one job at a time**, platform-wide. A single boolean gate — `has_active_job()` — refuses new work (manual `POST /shorts/jobs`, `POST /videos/{id}/short`) or skips it (autopilot) whenever any job is in a working status. On a 12-core / 32 GB / RTX 3050 box that leaves the machine mostly idle while a backlog of cuts waits in line. We want manual bursts and autopilot backlog to both flow through one bounded queue, and we want the GPU actually used.

## Constraints that shape the design

1. **Models are process-global singletons.** `render.py::_YOLO_MODEL` and `transcribe.py::_WHISPER_MODEL` are loaded once and shared; their locks guard *loading*, not *inference*. Two jobs calling `.predict()` / `.transcribe()` on the same object concurrently is unsafe (faster-whisper/CTranslate2 and ultralytics are not thread-safe for concurrent inference on one instance, and a shared CUDA context across threads is a PyTorch footgun). → **Isolation must be by process, not thread.**
2. **All job state already lives in the DB** (`shorts_jobs`, `shorts_clips`); the UI polls those tables. → The queue *is* the database; workers need no IPC beyond DB writes.
3. **Demucs stays on CPU, deliberately.** `vocals.py` forces `device="cpu"` for byte-for-byte determinism (CUDA/MPS introduce float jitter that changes cut outputs). This is not changing.
4. **Single local instance assumed.** No distributed coordination. (Multi-instance caveat noted below.)
5. **Hardware:** AMD Ryzen 9 7900X (12c/24t), 32 GB RAM, NVIDIA RTX 3050 (6 GB), Windows. With YOLO-only on CUDA, per-job VRAM is small, so 2 concurrent CUDA contexts fit comfortably in 6 GB and concurrency is effectively CPU-bound.

## Architecture

```
                 insert status=CREATED
  manual route  ─────────────────────────┐
  autopilot     ─────────────────────────┤
                                          ▼
                                   shorts_jobs (DB queue)
                                          ▲
              claims oldest CREATED, up to │ SHORTS_MAX_CONCURRENT_JOBS
                                          │
   APScheduler "shorts_dispatch" (every SHORTS_DISPATCH_INTERVAL_SECONDS, max_instances=1)
        │  tracks {job_id: Popen} in memory
        │  reaps exited workers (frees slots; FAILs non-terminal jobs)
        ▼
   subprocess:  python -m app.shorts.worker <job_id>
        │  own process → own YOLO/Whisper singletons + own CUDA context
        └─ calls existing run_shorts_job(job_id); writes status/progress to DB
```

### Component 1 — Dispatcher (`app/shorts/dispatcher.py`, new)

A single owner of all launching. Registered as an APScheduler interval job in `main.py`'s `lifespan` (alongside `autopilot`), `id="shorts_dispatch"`, `max_instances=1`, `coalesce=True`, interval = `SHORTS_DISPATCH_INTERVAL_SECONDS` (default 5s).

Module-level state: `_running: dict[int, subprocess.Popen]` — the in-memory source of truth for what this dispatcher launched. Because there is exactly one dispatcher, admission is serialized in memory; **no DB-level atomic claim is required.**

Each `dispatch_tick()`:

1. **Reap.** For each `(job_id, proc)` in `_running` where `proc.poll() is not None`: remove from `_running`; re-read the job; if its status is **not** terminal (`DONE`/`FAILED`), mark it `FAILED` with `error_message="worker exited unexpectedly (rc=<code>)"`. (Covers a worker that crashed before/while running the pipeline.)
2. **Fill.** While `len(_running) < SHORTS_MAX_CONCURRENT_JOBS`: fetch the oldest `CREATED` job whose `id` is **not** already in `_running` (`order by id asc, limit 1`); if none, stop. Otherwise spawn `subprocess.Popen([sys.executable, "-m", "app.shorts.worker", str(job_id)])`, store it in `_running`, and set the job's `started_at` (best-effort; the worker also sets `worker_pid`).

`dispatch_tick()` never blocks on the workers — it only polls and spawns, so the APScheduler thread returns immediately.

**Interface:** `dispatch_tick() -> None`. Depends on: `supabase()`, `settings`, `subprocess`, `sys`.

### Component 2 — Worker entrypoint (`app/shorts/worker.py`, new)

```
python -m app.shorts.worker <job_id>
```

Thin `main()`:
1. Parse `job_id` from `argv`.
2. Write `worker_pid = os.getpid()` and `started_at` onto the job row (so the reaper can find/kill an orphan after a restart).
3. Call the **existing, unchanged** `run_shorts_job(job_id)` from `app/shorts/runner.py`.
4. Exit 0 on completion; non-zero / unhandled exception → the dispatcher's reap step marks the job `FAILED`.

Because it's a fresh process, importing the cutter builds this worker's own `_YOLO_MODEL` / `_WHISPER_MODEL` and its own CUDA context. Model-load overhead (~a few seconds) is negligible against multi-minute jobs, and memory is released when the process exits.

**Interface:** CLI `python -m app.shorts.worker <job_id>`. Depends on: `run_shorts_job`, `supabase()`.

### Component 3 — CUDA for YOLO (`app/shorts/cutter/render.py`)

`pick_detection_setup()` gains a CUDA branch *first*:

```python
def pick_detection_setup() -> tuple[str, str]:
    try:
        import torch
        if torch.cuda.is_available():
            return "yolo11m.pt", "cuda"
        if torch.backends.mps.is_available():
            return "yolo11m.pt", "mps"
    except Exception:
        pass
    return "yolo11s.pt", "cpu"
```

Inference already passes `device=_YOLO_DEVICE` (render.py:237), so no other change. Whisper and Demucs are untouched (CPU).

### Component 4 — Admission changes

- **`app/shorts/routes.py`** (`create_job`, `make_short`): delete the `if has_active_job(): raise HTTPException(409, ...)` block and the `start_job_thread(job_id)` call. They now only insert `status=CREATED` and return `{job_id}`. (Optional queue-depth guard omitted for now — YAGNI.)
- **`app/autopilot.py`** (`_run_shorts_action`): replace `if has_active_job(): return` with `if active_job_count() >= settings.SHORTS_MAX_CONCURRENT_JOBS: return`, and drop the `start_job_thread(job_id)` call (insert `CREATED` only). Per-channel daily cap logic is unchanged. This keeps the pipeline topped up without piling the queue unboundedly across ticks.
- **`app/shorts/runner.py`**:
  - Note the existing `WORKING_STATUSES = ("CREATED", "DOWNLOADING", "ANALYSING", "RENDERING", "UPLOADING")` **already includes `CREATED`** — i.e. it already means "in flight (queued or running)".
  - Add `active_job_count() -> int` = count of rows whose status is in `WORKING_STATUSES` (queued + running). This is the in-flight counter the autopilot gate uses.
  - Add a narrower `IN_PROGRESS_STATUSES = WORKING_STATUSES minus "CREATED"` = `("DOWNLOADING", "ANALYSING", "RENDERING", "UPLOADING")` — jobs a worker has actually started. Only these get reaped on restart (see Component 5); `CREATED` must survive to be re-dispatched.
  - Keep `run_shorts_job` unchanged (the worker calls it). `has_active_job()` / `start_job_thread()` become unused by app code — remove `start_job_thread` (and update its test); keep `has_active_job` only if a test still needs it, else remove.

### Component 5 — Restart safety & the orphan problem

Subprocess workers **outlive** the parent process, so an app restart can leave orphaned workers still writing to the DB — the *"multi-instance / orphan-ffmpeg contention"* already recorded in project memory. Fix:

- **Schema:** add two nullable columns to `shorts_jobs`:
  - `worker_pid` `int` — set by the worker on start.
  - `started_at` `timestamptz` — set by the dispatcher/worker on launch.
- **`reap_stuck_jobs()`** (already runs once on startup in `lifespan`) is retargeted from `WORKING_STATUSES` to the narrower **`IN_PROGRESS_STATUSES`** (excludes `CREATED`): for every job a worker had actually started, if `worker_pid` is set and that PID is still alive, **kill it** via a small cross-platform helper (`os.kill` on POSIX; `taskkill /PID /F` on Windows), then mark the job `FAILED` ("server restarted mid-job"). `CREATED` jobs are **not** touched — the dispatcher re-picks them. (This is a behavior change from today, where `reap_stuck_jobs` scans `WORKING_STATUSES` and would fail queued jobs too — now harmless because nothing sat in `CREATED` under the old immediate-start model, but explicitly required under the queue.)

### Component 6 — Config (`app/config.py`)

```python
SHORTS_MAX_CONCURRENT_JOBS      = int(os.getenv("SHORTS_MAX_CONCURRENT_JOBS") or "2")
SHORTS_DISPATCH_INTERVAL_SECONDS = int(os.getenv("SHORTS_DISPATCH_INTERVAL_SECONDS") or "5")
```

## Data flow (happy path, 3 jobs queued, cap 2)

1. Three `CREATED` rows inserted (any mix of manual + autopilot).
2. `dispatch_tick`: `_running` empty → launches jobs A and B (subprocesses); C waits.
3. Workers A/B flip their jobs `DOWNLOADING → ANALYSING → RENDERING → UPLOADING`, writing progress; both run YOLO on CUDA concurrently, Whisper/Demucs/ffmpeg on CPU.
4. A finishes (`DONE`), process exits. Next `dispatch_tick`: reap frees A's slot → launches C.
5. B, C finish. Queue drains.

## Failure modes

| Failure | Handling |
|---|---|
| Worker throws mid-pipeline | `run_shorts_job`'s existing `try/except` sets `FAILED`; process exits; dispatcher frees slot. |
| Worker process crashes before setting a status | Dispatcher reap sees exited proc + non-terminal job → marks `FAILED`. |
| App restart with workers running | `reap_stuck_jobs` kills live `worker_pid`s, marks their jobs `FAILED`; `CREATED` jobs re-dispatched. |
| CUDA unavailable at runtime | `pick_detection_setup` falls back to MPS → CPU automatically. |
| Two app instances started (unsupported) | Two dispatchers → up to 2× concurrency and possible double-launch of the same `CREATED` job. Out of scope; documented as unsupported. |

## Testing

- **Dispatcher** (`tests/shorts/test_dispatcher.py`, new): with `subprocess.Popen` and `supabase()` mocked — (a) fills up to the cap and no further; (b) does not relaunch a job already in `_running`; (c) reap of an exited proc frees a slot and FAILs a non-terminal job; (d) leaves a job that finished `DONE` alone.
- **CUDA selection** (`tests/shorts/test_render_device.py`, new): monkeypatch `torch.cuda.is_available` / `torch.backends.mps.is_available` → assert `pick_detection_setup()` returns `cuda` / `mps` / `cpu` in priority order.
- **Admission** (`tests/shorts/test_routes.py`, update): `create_job` / `make_short` now insert `CREATED` and do **not** call `start_job_thread`; no 409 when another job is active.
- **Autopilot** (`tests/test_autopilot_shorts*.py`, update): gate is `active_job_count() >= cap`, not `has_active_job()`; enqueues `CREATED` without starting a thread.
- Full suite must stay green (189 currently passing).

## Out of scope (YAGNI)

- Autoscaling the concurrency cap; per-stage schedulers; GPU memory accounting.
- Distributed / multi-instance queue coordination.
- Moving Whisper or Demucs to CUDA.
- A durable "resume a half-finished cut" mechanism — the pipeline is not idempotent mid-run, so restart-interrupted jobs are failed and left for the user to retry.

## Migration / rollout

1. DB migration: `alter table shorts_jobs add column worker_pid int, add column started_at timestamptz;` (Supabase SQL).
2. Ship code behind the default `SHORTS_MAX_CONCURRENT_JOBS=2`. Setting it to `1` reproduces today's single-job behavior (useful rollback without a revert).
