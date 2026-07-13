# Parallel Shorts Queue + CUDA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-job `has_active_job()` gate with a DB-backed queue drained by isolated worker subprocesses (default 2 concurrent), and run YOLO detection on CUDA.

**Architecture:** Manual routes and autopilot insert `CREATED` job rows. One APScheduler dispatcher tick launches up to N jobs as `python -m app.shorts.worker <id>` subprocesses — each with its own model singletons and CUDA context — calling the unchanged `run_shorts_job`. All state flows through the existing `shorts_jobs`/`shorts_clips` tables. A `worker_pid` column lets the startup reaper kill orphaned workers after a restart.

**Tech Stack:** Python 3.13, FastAPI, APScheduler (already used), supabase-py (per-thread clients), PyTorch/ultralytics/faster-whisper (cutter), pytest.

Spec: `docs/superpowers/specs/2026-07-13-shorts-parallel-queue-cuda-design.md`

## Global Constraints

- **Python 3.13**; run tests with `python3 -m pytest` from the repo root (activate `venv` first: `source venv/bin/activate`).
- **Supabase clients are per-thread** (`app/db.py`) — thread pools / subprocesses are safe; each subprocess builds its own client on first `supabase()` call.
- **`WORKING_STATUSES` already includes `CREATED`** — it means "in flight (queued OR running)". The narrower `IN_PROGRESS_STATUSES` (running only) is introduced here for reaping.
- **Terminal job statuses are `DONE` and `FAILED`** only.
- **Demucs and Whisper stay on CPU.** Only YOLO moves to CUDA.
- **Default concurrency `SHORTS_MAX_CONCURRENT_JOBS = 2`.** Setting it to `1` reproduces today's single-job behavior.
- **Target OS is Windows** (also keep POSIX working): spawn workers with `sys.executable`; kill orphans with `taskkill` on Windows, `os.kill` on POSIX.
- The full suite is **189 tests green** at the start; it must stay green after every task.
- One commit per task. Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- Modify `app/config.py` — two new settings.
- Create `supabase/migrations/20260713120000_shorts_worker_pid.sql` — add `worker_pid`, `started_at`.
- Modify `app/shorts/cutter/render.py` — CUDA branch in `pick_detection_setup`.
- Modify `app/shorts/runner.py` — `IN_PROGRESS_STATUSES`, `active_job_count()`, `_kill_pid_if_alive()`, reap update; later remove `start_job_thread`/`has_active_job`.
- Create `app/shorts/worker.py` — subprocess CLI entrypoint.
- Create `app/shorts/dispatcher.py` — `dispatch_tick()` + `_running` state.
- Modify `app/shorts/routes.py` — drop the 409 gate and thread start.
- Modify `app/autopilot.py` — count-based gate, drop thread start.
- Modify `app/main.py` — register the `shorts_dispatch` scheduler job.
- Tests: create `tests/shorts/test_render_device.py`, `tests/shorts/test_worker.py`, `tests/shorts/test_dispatcher.py`, `tests/shorts/test_runner_queue.py`; update `tests/shorts/test_routes.py`, `tests/shorts/test_video_short_routes.py`, `tests/test_autopilot_shorts.py`.

---

### Task 1: Config settings

**Files:**
- Modify: `app/config.py` (after `AUTOPILOT_TICK_SECONDS`, ~line 38)
- Test: `tests/shorts/test_runner_queue.py` (new — reused by later tasks)

**Interfaces:**
- Produces: `settings.SHORTS_MAX_CONCURRENT_JOBS: int` (default 2), `settings.SHORTS_DISPATCH_INTERVAL_SECONDS: int` (default 5).

- [ ] **Step 1: Write the failing test**

Create `tests/shorts/test_runner_queue.py`:

```python
def test_shorts_concurrency_settings_defaults():
    from app.config import settings
    assert settings.SHORTS_MAX_CONCURRENT_JOBS == 2
    assert settings.SHORTS_DISPATCH_INTERVAL_SECONDS == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/shorts/test_runner_queue.py::test_shorts_concurrency_settings_defaults -v`
Expected: FAIL with `AttributeError: ... SHORTS_MAX_CONCURRENT_JOBS`.

- [ ] **Step 3: Add the settings**

In `app/config.py`, immediately after the `AUTOPILOT_TICK_SECONDS = ...` line:

```python
    # Shorts job queue: how many cutter jobs run concurrently, and how often
    # the dispatcher polls for CREATED jobs / reaps finished workers. Cap 1
    # reproduces the old single-job behavior.
    SHORTS_MAX_CONCURRENT_JOBS = int(os.getenv("SHORTS_MAX_CONCURRENT_JOBS") or "2")
    SHORTS_DISPATCH_INTERVAL_SECONDS = int(os.getenv("SHORTS_DISPATCH_INTERVAL_SECONDS") or "5")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/shorts/test_runner_queue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/shorts/test_runner_queue.py
git commit -m "feat(shorts): add concurrency + dispatch-interval settings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: DB migration — `worker_pid` / `started_at`

**Files:**
- Create: `supabase/migrations/20260713120000_shorts_worker_pid.sql`

**Interfaces:**
- Produces: columns `shorts_jobs.worker_pid int` (nullable), `shorts_jobs.started_at timestamptz` (nullable).

This task has no pytest (tests mock supabase). It ships the SQL and applies it to the live DB.

- [ ] **Step 1: Write the migration file**

Create `supabase/migrations/20260713120000_shorts_worker_pid.sql`:

```sql
-- Parallel shorts queue: track which OS process is running a job so the
-- startup reaper can kill an orphaned worker after a mid-job restart.
alter table shorts_jobs
    add column if not exists worker_pid  integer,
    add column if not exists started_at  timestamptz;
```

- [ ] **Step 2: Apply the migration to the database**

Apply via your normal Supabase migration path (the SQL editor or `supabase db push`). If applying by hand, paste the file's contents into the Supabase SQL editor and run it.

Verify:

```bash
source venv/bin/activate
python3 -c "from app.db import supabase; print([c for c in supabase().table('shorts_jobs').select('id,worker_pid,started_at').limit(1).execute().data])"
```
Expected: a row (or `[]`) printed with **no** error — confirms both columns exist.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260713120000_shorts_worker_pid.sql
git commit -m "feat(shorts): migration adds worker_pid/started_at to shorts_jobs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: CUDA device selection for YOLO

**Files:**
- Modify: `app/shorts/cutter/render.py` (`pick_detection_setup`, ~lines 58-66)
- Test: `tests/shorts/test_render_device.py` (new)

**Interfaces:**
- Modifies: `pick_detection_setup() -> tuple[str, str]` — now prefers `("yolo11m.pt", "cuda")` when `torch.cuda.is_available()`.

- [ ] **Step 1: Write the failing test**

Create `tests/shorts/test_render_device.py`:

```python
import sys
import types
from unittest.mock import patch


def _fake_torch(cuda=False, mps=False):
    t = types.ModuleType("torch")
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda)
    t.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps))
    return t


def test_pick_detection_prefers_cuda():
    from app.shorts.cutter.render import pick_detection_setup
    with patch.dict(sys.modules, {"torch": _fake_torch(cuda=True, mps=True)}):
        assert pick_detection_setup() == ("yolo11m.pt", "cuda")


def test_pick_detection_falls_back_to_mps():
    from app.shorts.cutter.render import pick_detection_setup
    with patch.dict(sys.modules, {"torch": _fake_torch(cuda=False, mps=True)}):
        assert pick_detection_setup() == ("yolo11m.pt", "mps")


def test_pick_detection_falls_back_to_cpu():
    from app.shorts.cutter.render import pick_detection_setup
    with patch.dict(sys.modules, {"torch": _fake_torch(cuda=False, mps=False)}):
        assert pick_detection_setup() == ("yolo11s.pt", "cpu")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/shorts/test_render_device.py -v`
Expected: `test_pick_detection_prefers_cuda` FAILS (returns mps or cpu, not cuda).

- [ ] **Step 3: Add the CUDA branch**

In `app/shorts/cutter/render.py`, replace the body of `pick_detection_setup`:

```python
def pick_detection_setup() -> tuple[str, str]:
    """(model_name, device). YOLO11m on GPU (CUDA or Apple MPS); YOLO11s on CPU."""
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/shorts/test_render_device.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/cutter/render.py tests/shorts/test_render_device.py
git commit -m "feat(shorts): run YOLO on CUDA when available

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `runner.py` — `IN_PROGRESS_STATUSES` + `active_job_count()`

**Files:**
- Modify: `app/shorts/runner.py` (add near `WORKING_STATUSES`, ~line 23, and a new function)
- Test: `tests/shorts/test_runner_queue.py` (extend)

**Interfaces:**
- Produces: `IN_PROGRESS_STATUSES: tuple[str, ...]`, `active_job_count() -> int` (count of rows whose status is in `WORKING_STATUSES` — i.e. queued + running).

- [ ] **Step 1: Write the failing test**

Append to `tests/shorts/test_runner_queue.py`:

```python
from unittest.mock import MagicMock, patch


def test_in_progress_statuses_excludes_created():
    from app.shorts.runner import IN_PROGRESS_STATUSES, WORKING_STATUSES
    assert "CREATED" not in IN_PROGRESS_STATUSES
    assert set(IN_PROGRESS_STATUSES) == set(WORKING_STATUSES) - {"CREATED"}


def test_active_job_count_counts_working_rows():
    from app.shorts import runner
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": 1}, {"id": 2}, {"id": 3}]
    with patch("app.shorts.runner.supabase", return_value=sb):
        assert runner.active_job_count() == 3
    # counted by the full in-flight status set (includes CREATED)
    sb.table.return_value.select.return_value.in_.assert_called_once_with(
        "status", list(runner.WORKING_STATUSES))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/shorts/test_runner_queue.py -k "in_progress or active_job_count" -v`
Expected: FAIL (`IN_PROGRESS_STATUSES` / `active_job_count` not defined).

- [ ] **Step 3: Add the constant and function**

In `app/shorts/runner.py`, just below the existing `WORKING_STATUSES = (...)` line:

```python
# The subset of WORKING_STATUSES a worker has actually started (excludes the
# queued CREATED state). Only these are reaped on restart; CREATED jobs survive
# to be re-dispatched.
IN_PROGRESS_STATUSES = tuple(s for s in WORKING_STATUSES if s != "CREATED")
```

Add this function (e.g. just after `has_active_job`):

```python
def active_job_count() -> int:
    """Number of shorts jobs in flight (queued CREATED + actively running)."""
    rows = (supabase().table("shorts_jobs").select("id")
            .in_("status", list(WORKING_STATUSES)).execute().data) or []
    return len(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/shorts/test_runner_queue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/runner.py tests/shorts/test_runner_queue.py
git commit -m "feat(shorts): add IN_PROGRESS_STATUSES and active_job_count()

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `runner.py` — orphan-killing reaper

**Files:**
- Modify: `app/shorts/runner.py` (imports; add `_kill_pid_if_alive`; rewrite `reap_stuck_jobs`)
- Test: `tests/shorts/test_runner_queue.py` (extend)

**Interfaces:**
- Produces: `_kill_pid_if_alive(pid: int | None) -> None`. `reap_stuck_jobs() -> int` now scans `IN_PROGRESS_STATUSES`, kills each job's live `worker_pid`, marks it `FAILED`, and leaves `CREATED` untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/shorts/test_runner_queue.py`:

```python
def test_reap_kills_orphans_and_fails_them():
    from app.shorts import runner
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": 10, "worker_pid": 4242}, {"id": 11, "worker_pid": None}]
    updates = []
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    with patch("app.shorts.runner.supabase", return_value=sb), \
         patch("app.shorts.runner._kill_pid_if_alive") as kill:
        n = runner.reap_stuck_jobs()
    assert n == 2
    # only in-progress statuses are scanned, never CREATED
    sb.table.return_value.select.return_value.in_.assert_called_once_with(
        "status", list(runner.IN_PROGRESS_STATUSES))
    kill.assert_any_call(4242)
    kill.assert_any_call(None)


def test_kill_pid_if_alive_noop_on_falsy():
    from app.shorts import runner
    # Must not raise for None/0.
    runner._kill_pid_if_alive(None)
    runner._kill_pid_if_alive(0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/shorts/test_runner_queue.py -k "reap or kill_pid" -v`
Expected: FAIL (`_kill_pid_if_alive` missing; reap still scans `WORKING_STATUSES`).

- [ ] **Step 3: Update imports and implement**

At the top of `app/shorts/runner.py`, ensure these imports exist (add `os`, `signal`, `sys`; `subprocess` is already imported):

```python
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
```

Add the helper (near the bottom, next to `_notify_macos`):

```python
def _kill_pid_if_alive(pid: int | None) -> None:
    """Best-effort terminate a possibly-orphaned worker process. Cross-platform."""
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass  # already gone / not ours — nothing to do
```

Replace `reap_stuck_jobs` with:

```python
def reap_stuck_jobs() -> int:
    """Fail jobs a worker had started but a server restart abandoned.

    Scans IN_PROGRESS_STATUSES (never CREATED — those stay queued and get
    re-dispatched). Any still-alive worker process for a stuck job is killed
    first so it can't keep writing to the row or hog ffmpeg/GPU.
    """
    sb = supabase()
    stuck = (sb.table("shorts_jobs").select("id,worker_pid")
             .in_("status", list(IN_PROGRESS_STATUSES)).execute().data) or []
    for row in stuck:
        _kill_pid_if_alive(row.get("worker_pid"))
        sb.table("shorts_jobs").update({
            "status": "FAILED", "error_message": "server restarted mid-job",
        }).eq("id", row["id"]).execute()
    if stuck:
        log.warning("Reaped %d stuck shorts job(s) on startup", len(stuck))
    return len(stuck)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/shorts/test_runner_queue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/runner.py tests/shorts/test_runner_queue.py
git commit -m "feat(shorts): reaper kills orphaned workers, spares CREATED jobs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Worker subprocess entrypoint

**Files:**
- Create: `app/shorts/worker.py`
- Test: `tests/shorts/test_worker.py` (new)

**Interfaces:**
- Produces: `app.shorts.worker.main(argv: list[str] | None = None) -> int`. Runnable as `python -m app.shorts.worker <job_id>`. Sets `worker_pid`/`started_at` on the row, then calls `run_shorts_job(job_id)`.

- [ ] **Step 1: Write the failing test**

Create `tests/shorts/test_worker.py`:

```python
import os
from unittest.mock import MagicMock, patch


def test_worker_main_marks_pid_and_runs_job():
    from app.shorts import worker
    sb = MagicMock()
    with patch("app.shorts.worker.supabase", return_value=sb), \
         patch("app.shorts.worker.run_shorts_job") as run:
        rc = worker.main(["5"])
    assert rc == 0
    run.assert_called_once_with(5)
    # worker recorded its own PID on the job row
    upd = sb.table.return_value.update
    fields = upd.call_args[0][0]
    assert fields["worker_pid"] == os.getpid()
    assert "started_at" in fields
    upd.return_value.eq.assert_called_once_with("id", 5)


def test_worker_main_usage_error_without_arg():
    from app.shorts import worker
    assert worker.main([]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/shorts/test_worker.py -v`
Expected: FAIL (`No module named app.shorts.worker`).

- [ ] **Step 3: Implement the worker**

Create `app/shorts/worker.py`:

```python
"""Isolated shorts-cutter worker. Launched by the dispatcher as a subprocess:

    python -m app.shorts.worker <job_id>

Running in its own process gives this worker its own YOLO/Whisper model
instances and its own CUDA context, so multiple jobs can run in parallel
without sharing the (non-thread-safe) global model singletons. All state is
written to the shorts_jobs/shorts_clips tables — no IPC beyond the DB.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from app.db import supabase
from app.shorts.runner import run_shorts_job

log = logging.getLogger("midas.shorts.worker")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m app.shorts.worker <job_id>", file=sys.stderr)
        return 2
    job_id = int(argv[0])
    # Record this process so the startup reaper can kill us if we're orphaned.
    supabase().table("shorts_jobs").update({
        "worker_pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()
    run_shorts_job(job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/shorts/test_worker.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/worker.py tests/shorts/test_worker.py
git commit -m "feat(shorts): isolated worker subprocess entrypoint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Dispatcher

**Files:**
- Create: `app/shorts/dispatcher.py`
- Test: `tests/shorts/test_dispatcher.py` (new)

**Interfaces:**
- Consumes: `settings.SHORTS_MAX_CONCURRENT_JOBS`, `supabase()`.
- Produces: `dispatch_tick() -> None`; module-global `_running: dict[int, subprocess.Popen]`; `_spawn(job_id: int) -> subprocess.Popen`.

- [ ] **Step 1: Write the failing test**

Create `tests/shorts/test_dispatcher.py`:

```python
from unittest.mock import MagicMock, patch


def _created_query(sb, created_ids):
    """Wire sb so the 'fetch next CREATED not in running' query returns rows."""
    q = sb.table.return_value.select.return_value.eq.return_value.order.return_value
    # both branches (with and without .not_.in_) resolve to the same limited fetch
    q.limit.return_value.execute.return_value.data = [{"id": i} for i in created_ids]
    q.not_.in_.return_value.limit.return_value.execute.return_value.data = [
        {"id": i} for i in created_ids]


def _reset():
    from app.shorts import dispatcher
    dispatcher._running.clear()
    return dispatcher


def test_fills_up_to_cap():
    d = _reset()
    sb = MagicMock()
    _created_query(sb, [1, 2, 3])
    procs = [MagicMock(), MagicMock()]
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn", side_effect=procs) as spawn:
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    assert spawn.call_count == 2                      # only cap launched
    assert set(d._running.keys()) == {1, 2}


def test_does_not_relaunch_running_job():
    d = _reset()
    d._running[1] = MagicMock(poll=lambda: None)     # job 1 already running
    sb = MagicMock()
    _created_query(sb, [1, 2])                        # 1 still CREATED, 2 new
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn", return_value=MagicMock()) as spawn:
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    spawn.assert_called_once_with(2)                  # never re-spawns 1


def test_reap_frees_slot_and_fails_nonterminal():
    d = _reset()
    dead = MagicMock(poll=lambda: 1, returncode=1)    # exited, non-zero
    d._running[7] = dead
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "RENDERING"}
    _created_query(sb, [])                            # no new CREATED work
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn"):
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    assert 7 not in d._running                        # slot freed
    upd = sb.table.return_value.update.call_args[0][0]
    assert upd["status"] == "FAILED"


def test_reap_leaves_done_job_alone():
    d = _reset()
    done = MagicMock(poll=lambda: 0, returncode=0)
    d._running[8] = done
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "DONE"}
    _created_query(sb, [])
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn"):
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    assert 8 not in d._running
    sb.table.return_value.update.assert_not_called()  # DONE is terminal, untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/shorts/test_dispatcher.py -v`
Expected: FAIL (`No module named app.shorts.dispatcher`).

- [ ] **Step 3: Implement the dispatcher**

Create `app/shorts/dispatcher.py`:

```python
"""Single owner of shorts-job launching. Registered as an APScheduler interval
job (max_instances=1) in app/main.py. Each tick reaps finished worker
subprocesses and launches queued (CREATED) jobs up to the concurrency cap.

Because there is exactly one dispatcher, `_running` (in-memory) is the source
of truth for what has been launched — no DB-level atomic claim is needed.
"""
from __future__ import annotations

import logging
import subprocess
import sys

from app.config import settings
from app.db import supabase

log = logging.getLogger("midas.shorts.dispatcher")

_TERMINAL = ("DONE", "FAILED")
# job_id -> Popen for workers this dispatcher launched
_running: dict[int, subprocess.Popen] = {}


def _spawn(job_id: int) -> subprocess.Popen:
    """Launch an isolated worker. cwd/env inherited from the server process
    (started at repo root), so `-m app.shorts.worker` resolves."""
    return subprocess.Popen([sys.executable, "-m", "app.shorts.worker", str(job_id)])


def _next_created_id(sb) -> int | None:
    """Oldest CREATED job not already launched by this dispatcher, or None."""
    running_ids = list(_running.keys())
    q = (sb.table("shorts_jobs").select("id")
         .eq("status", "CREATED").order("id", desc=False))
    if running_ids:
        q = q.not_.in_("id", running_ids)
    rows = (q.limit(1).execute().data) or []
    return rows[0]["id"] if rows else None


def dispatch_tick() -> None:
    sb = supabase()

    # 1. Reap finished workers.
    for job_id, proc in list(_running.items()):
        if proc.poll() is None:
            continue  # still running
        _running.pop(job_id, None)
        job = (sb.table("shorts_jobs").select("status")
               .eq("id", job_id).single().execute().data) or {}
        if job.get("status") not in _TERMINAL:
            sb.table("shorts_jobs").update({
                "status": "FAILED",
                "error_message": f"worker exited unexpectedly (rc={proc.returncode})",
            }).eq("id", job_id).execute()
            log.warning("shorts job %s: worker exited rc=%s (status=%s) -> FAILED",
                        job_id, proc.returncode, job.get("status"))

    # 2. Fill free slots with queued work.
    cap = settings.SHORTS_MAX_CONCURRENT_JOBS
    while len(_running) < cap:
        next_id = _next_created_id(sb)
        if next_id is None:
            break
        _running[next_id] = _spawn(next_id)
        log.info("shorts dispatch: launched worker for job %s (%d/%d slots)",
                 next_id, len(_running), cap)
```

Note for the test wiring: `_next_created_id` calls `.eq(...).order(...)` then either `.not_.in_(...).limit(1)` or `.limit(1)`; the test's `_created_query` stubs both shapes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/shorts/test_dispatcher.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/dispatcher.py tests/shorts/test_dispatcher.py
git commit -m "feat(shorts): dispatcher drains queue into worker subprocesses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Remove the single-job gate from routes

**Files:**
- Modify: `app/shorts/routes.py` (imports; `create_job`; `make_short`)
- Modify: `tests/shorts/test_routes.py`
- Modify: `tests/shorts/test_video_short_routes.py`

**Interfaces:**
- Modifies: `POST /shorts/jobs` and `POST /videos/{id}/short` now insert `status=CREATED` and return `{job_id}` with no 409 gate and no thread start.

- [ ] **Step 1: Update the tests first (they encode the old behavior)**

In `tests/shorts/test_routes.py`: replace `test_create_job_starts_thread` and delete `test_create_job_conflicts_when_job_running`:

```python
def test_create_job_enqueues():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel()):
        r = _client().post("/shorts/jobs", json={**BODY, "cut_mode": "coverage"})
    assert r.status_code == 200 and r.json() == {"job_id": 42}
```

In `tests/shorts/test_video_short_routes.py`: replace `test_make_short_creates_job`, delete `test_make_short_conflicts_when_busy`, and drop the `has_active_job`/`start_job_thread` patches from `test_make_short_blocks_unlisted`, `test_make_short_blocks_private`, `test_make_short_blocks_unknown_privacy`:

```python
def test_make_short_creates_job():
    with patch("app.shorts.routes.supabase", return_value=_sb_video()):
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 200 and r.json() == {"job_id": 42}


def test_make_short_blocks_unlisted():
    with patch("app.shorts.routes.supabase", return_value=_sb_video(privacy="unlisted")):
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409


def test_make_short_blocks_private():
    with patch("app.shorts.routes.supabase", return_value=_sb_video(privacy="private")):
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409


def test_make_short_blocks_unknown_privacy():
    # privacy_status not yet synced (NULL) -> refuse; only confirmed-public videos are cut.
    with patch("app.shorts.routes.supabase", return_value=_sb_video(privacy=None)):
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409
```

(The privacy-block tests keep their 409 — that gate is unrelated to the job queue.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/shorts/test_routes.py tests/shorts/test_video_short_routes.py -v`
Expected: FAIL — routes still import/reference `has_active_job` / `start_job_thread`, and the deleted-patch tests now error or the code still returns 409.

- [ ] **Step 3: Update `app/shorts/routes.py`**

Change the import line (remove the gate helpers):

```python
from app.shorts.youtube_upload import upload_short
```

(Delete `from app.shorts.runner import has_active_job, start_job_thread`.)

In `create_job`, delete the gate and the thread start so the tail reads:

```python
    if not is_youtube_url(body.source_url):
        raise HTTPException(400, "source_url must be a YouTube video link")

    inserted = sb.table("shorts_jobs").insert({
        "channel_id":    body.channel_id,
        "source_url":    body.source_url,
        "cut_mode":      body.cut_mode,
        "camera_motion": body.camera_motion,
        "status":        "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]
    log.info("Shorts job %d queued for %s", job_id, body.source_url)
    return {"job_id": job_id}
```

In `make_short`, delete the `if has_active_job(): ...` block and the `start_job_thread(job_id)` call so the tail reads:

```python
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
    log.info("Shorts job %d queued for video %s", job_id, video_id)
    return {"job_id": job_id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/shorts/test_routes.py tests/shorts/test_video_short_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/shorts/routes.py tests/shorts/test_routes.py tests/shorts/test_video_short_routes.py
git commit -m "feat(shorts): routes enqueue CREATED jobs, drop single-job 409

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Autopilot count-based gate

**Files:**
- Modify: `app/autopilot.py` (import line 16; `_run_shorts_action`)
- Modify: `tests/test_autopilot_shorts.py`

**Interfaces:**
- Modifies: `_run_shorts_action(ch)` skips when `active_job_count() >= settings.SHORTS_MAX_CONCURRENT_JOBS`; inserts `CREATED` with no thread start.

- [ ] **Step 1: Update the tests first**

In `tests/test_autopilot_shorts.py`, rewrite the four `_run_shorts_action` tests to patch `active_job_count` and drop `start_job_thread`:

```python
def test_run_shorts_action_enqueues_when_eligible():
    import app.autopilot as ap
    rec = []
    long_videos = [{"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = {"by_source": [], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, rec)), \
         patch("app.autopilot.active_job_count", return_value=0):
        ap._run_shorts_action(CH)
    assert len(rec) == 1
    job = rec[0]
    assert job["source_video_id"] == "vGood"
    assert job["autopilot_generated"] is True
    assert job["upload_cap"] == 2
    assert job["cut_mode"] == "highlights" and job["camera_motion"] == "calm"
    assert job["status"] == "CREATED"


def test_run_shorts_action_noop_when_at_capacity():
    import app.autopilot as ap
    rec = []
    with patch("app.autopilot.supabase", return_value=_sb([], {"by_source": [], "today": []}, rec)), \
         patch("app.autopilot.active_job_count", return_value=2), \
         patch("app.autopilot.settings") as st:
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        ap._run_shorts_action(CH)
    assert rec == []


def test_run_shorts_action_noop_over_daily_cap():
    import app.autopilot as ap
    rec = []
    long_videos = [{"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = {"by_source": [], "today": [{"id": 1}]}   # already 1 today, cap is 1
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, rec)), \
         patch("app.autopilot.active_job_count", return_value=0):
        ap._run_shorts_action(CH)
    assert rec == []


def test_run_shorts_action_noop_when_no_eligible_video():
    import app.autopilot as ap
    rec = []
    sj = {"by_source": [], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb([], sj, rec)), \
         patch("app.autopilot.active_job_count", return_value=0):
        ap._run_shorts_action(CH)
    assert rec == []
```

(`test_run_shorts_action_noop_when_at_capacity` patches `app.autopilot.settings` so the gate compares against a known cap even if the default changes; the enqueue test uses the real `settings` with `active_job_count=0`, well under the cap.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_autopilot_shorts.py -v`
Expected: FAIL — `active_job_count` not imported in autopilot; code still calls `has_active_job` / `start_job_thread`.

- [ ] **Step 3: Update `app/autopilot.py`**

Change the import (line 16):

```python
from app.shorts.runner import active_job_count
```

In `_run_shorts_action`, replace the gate and remove the thread start:

```python
    channel_id = ch["id"]
    if active_job_count() >= settings.SHORTS_MAX_CONCURRENT_JOBS:
        return  # queue + running already at capacity; try again next tick
    cap = ch.get("autopilot_shorts_daily_cap") or 1
    if _shorts_made_today(channel_id) >= cap:
        return
    video = _next_uncut_video_for_channel(channel_id)
    if not video:
        return
    upload_cap = ch.get("autopilot_shorts_upload_cap") or 2
    inserted = (
        supabase().table("shorts_jobs").insert({
            "channel_id":          channel_id,
            "source_video_id":     video["id"],
            "source_url":          f"https://www.youtube.com/watch?v={video['id']}",
            "cut_mode":            ch.get("shorts_cut_mode") or "highlights",
            "camera_motion":       ch.get("shorts_camera_motion") or "calm",
            "upload_cap":          upload_cap,
            "autopilot_generated": True,
            "status":              "CREATED",
        }).execute()
    ).data
    job_id = inserted[0]["id"]
    log.info("Autopilot shorts: queued job %d for video %s (channel %s)", job_id, video["id"], channel_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_autopilot_shorts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/autopilot.py tests/test_autopilot_shorts.py
git commit -m "feat(shorts): autopilot gates on active_job_count, enqueues only

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Register the dispatcher in the scheduler

**Files:**
- Modify: `app/main.py` (import; `lifespan`)

**Interfaces:**
- Consumes: `dispatch_tick`, `settings.SHORTS_DISPATCH_INTERVAL_SECONDS`.
- Produces: an APScheduler job `id="shorts_dispatch"` running every interval.

This wires a background loop; it's validated by a live smoke run plus the full suite (imports must resolve). The existing route tests don't trigger `lifespan`, so they're unaffected.

- [ ] **Step 1: Add the import**

Near the other shorts imports in `app/main.py`:

```python
from app.shorts.dispatcher import dispatch_tick
```

- [ ] **Step 2: Register the interval job in `lifespan`**

In `app/main.py`'s `lifespan`, alongside the existing `scheduler.add_job(autopilot_tick, "interval", ...)` block, add:

```python
    scheduler.add_job(
        dispatch_tick,
        "interval",
        seconds=settings.SHORTS_DISPATCH_INTERVAL_SECONDS,
        id="shorts_dispatch",
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 3: Verify the app imports and the full suite is green**

Run: `python3 -m pytest -q`
Expected: all tests PASS (should be 189 + the new ones from this plan).

- [ ] **Step 4: Live smoke test**

```bash
source venv/bin/activate
uvicorn app.main:app --port 8137 >/tmp/midas_smoke.log 2>&1 &
sleep 5
# enqueue a job via the API (replace with a real public video URL + channel id)
python3 -c "import urllib.request,json; \
  req=urllib.request.Request('http://127.0.0.1:8137/shorts/jobs', \
  data=json.dumps({'channel_id':'<CHANNEL_ID>','source_url':'<YT_URL>'}).encode(), \
  headers={'Content-Type':'application/json'}); \
  print(urllib.request.urlopen(req).read().decode())"
sleep 8
grep -E "shorts dispatch|launched worker" /tmp/midas_smoke.log
pkill -f "uvicorn app.main:app --port 8137"
```
Expected: a `shorts dispatch: launched worker for job <id>` line within ~1 interval, and the job row progresses past `CREATED`.

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat(shorts): run the dispatcher as a scheduler interval job

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Remove dead single-job helpers

**Files:**
- Modify: `app/shorts/runner.py` (delete `has_active_job`, `start_job_thread`; drop now-unused `threading` import if nothing else uses it)

**Interfaces:**
- Removes: `has_active_job()`, `start_job_thread()`. (No remaining callers after Tasks 8-9.)

- [ ] **Step 1: Confirm there are no remaining references**

Run: `grep -rn "has_active_job\|start_job_thread" app/ tests/ | grep -v __pycache__`
Expected: only the definitions in `app/shorts/runner.py` (no callers, no test patches).

- [ ] **Step 2: Delete the two functions**

In `app/shorts/runner.py`, remove the `has_active_job` and `start_job_thread` function definitions. Then check whether `threading` is still referenced:

Run: `grep -n "threading" app/shorts/runner.py`
If there are no remaining uses, delete `import threading` from the imports.

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add app/shorts/runner.py
git commit -m "refactor(shorts): drop unused has_active_job/start_job_thread

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Concurrency model / dispatcher / worker subprocess → Tasks 6, 7, 10. ✓
- CUDA (YOLO only) → Task 3. ✓
- Admission changes (routes + autopilot) → Tasks 8, 9. ✓
- `active_job_count` / `IN_PROGRESS_STATUSES` → Task 4. ✓
- Restart safety: `worker_pid`/`started_at` columns + orphan-killing reaper → Tasks 2, 5, 6. ✓
- Config settings → Task 1. ✓
- Remove `has_active_job`/`start_job_thread` → Task 11. ✓
- Tests (dispatcher, render device, admission, autopilot) → Tasks 3, 4, 5, 6, 7, 8, 9. ✓

**Type/name consistency:** `active_job_count`, `IN_PROGRESS_STATUSES`, `_kill_pid_if_alive`, `dispatch_tick`, `_running`, `_spawn`, `_next_created_id`, `run_shorts_job`, `worker_pid`/`started_at` used consistently across tasks. `SHORTS_MAX_CONCURRENT_JOBS` / `SHORTS_DISPATCH_INTERVAL_SECONDS` match the spec.

**Ordering safety:** `has_active_job`/`start_job_thread` stay defined until Tasks 8-9 remove their callers, then Task 11 deletes the definitions — no import breaks mid-sequence. Migration (Task 2) lands before the worker/reaper touch `worker_pid` at runtime; unit tests mock the DB so they don't depend on it.

**Known caveat (documented, out of scope):** two app instances → two dispatchers → double concurrency. Single local instance assumed.
