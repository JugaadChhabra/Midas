"""In-process record of every scheduled job's last run, served at /health/jobs.

Per-channel jobs isolate each channel's exception so one bad channel can't stop
the rest. Before this module that isolation also hid the failure: APScheduler
logged the run as "executed successfully" and `playlist_health_score` raised
`NameError` daily for seven weeks unnoticed. Now `_run_per_channel` raises
`JobRunFailed` once every channel has run, APScheduler fires `EVENT_JOB_ERROR`,
and the listener here records it. The jobs that loop on their own
(`poll_metrics`, `poll_reporting`, `main._daily_measurement_eval`) raise the
same exception after their pass.

In memory, and, once `persist_to` names a file (main.lifespan: `job_status.json`
under LOG_DIR, bind-mounted on the host), kept across restarts: the startup
catch-up (app/catch_up.py) reads a job's last run from it to tell a missed run
from one that already happened before the restart.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

log = logging.getLogger("midas.job_status")

NEVER_RUN = "never_run"
SUCCESS = "success"
FAILED = "failed"
# Ran to completion, but some items inside a channel errored (not all of them).
# A job reports this by returning {"partial_errors": {channel_id: detail}}.
DEGRADED = "degraded"

# The shortest gap between two saves of one job's unchanged status.
SAVE_EVERY_SECONDS = 60


class JobRunFailed(Exception):
    """A job run in which at least one channel (or item on it) raised.

    Carries ``failed_channels`` ({channel_id: "<Type>: <message>"}; for
    measurement_eval the value lists the failing audits) so the
    registry gets the per-channel detail from the exception APScheduler hands
    it, rather than from a side channel.
    """

    def __init__(self, label: str, failed_channels: dict[str, str]):
        self.failed_channels = dict(failed_channels)
        super().__init__(
            f"{label} failed for {len(self.failed_channels)} channel(s): "
            + ", ".join(self.failed_channels)
        )


def describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def item_error_verdict(categories: dict[str, tuple[int, int]]) -> tuple[str | None, str | None]:
    """Judge one channel's per-item errors: ``{category: (errored, attempted)}``.

    Returns ``(failure, partial)``. A category where EVERY attempted item errored
    is a failure: that is an outage or a bug (the class of the seven-week
    ``NameError``), not noise. Some-but-not-all is partial: the polls already
    accept a trickle of per-item errors (deleted videos, transient DNS, Gap 10),
    so failing on one would page every night and teach everyone to ignore it.
    """
    failure = [f"{c}: all {n} failed" for c, (e, n) in categories.items() if n and e >= n]
    partial = [f"{c}: {e}/{n} failed" for c, (e, n) in categories.items() if 0 < e < n]
    return ("; ".join(failure) or None, "; ".join(partial) or None)


def _blank() -> dict:
    return {"status": NEVER_RUN, "last_run_at": None, "error": None,
            "failed_channels": {}, "partial_errors": {}}


class JobStatusRegistry:
    """Last status per job id. Thread-safe: listeners run on executor threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._path: Path | None = None
        self._saved_at: dict[str, float] = {}

    def persist_to(self, path) -> None:
        """Load the entries saved in `path`, and rewrite it after every run.

        A missing file starts empty; an unreadable one is logged and ignored,
        so a bad file never keeps the app from starting.
        """
        path = Path(path)
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            saved = {}
        except (OSError, ValueError) as e:
            log.warning("job status: %s unreadable; starting empty: %s", path, e)
            saved = {}
        with self._lock:
            self._path = path
            for job_id, entry in (saved.items() if isinstance(saved, dict) else ()):
                if isinstance(entry, dict):
                    self._jobs[job_id] = {**_blank(), **entry}

    def register(self, job_id: str) -> None:
        """Show a job before its first run, so a missing job is distinguishable
        from one that simply hasn't fired yet."""
        with self._lock:
            self._jobs.setdefault(job_id, _blank())

    def watch(self, scheduler) -> None:
        """Register every job already added to ``scheduler`` and listen for runs.

        Saved entries of jobs no longer registered (a flag turned one off) are
        dropped, so /health/jobs lists only what can run.
        """
        ids = [job.id for job in scheduler.get_jobs()]
        with self._lock:
            for job_id in set(self._jobs) - set(ids):
                del self._jobs[job_id]
        for job_id in ids:
            self.register(job_id)
        scheduler.add_listener(self.on_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    def on_event(self, event) -> None:
        entry = _blank()
        entry["last_run_at"] = event.scheduled_run_time.isoformat()
        if event.code == EVENT_JOB_ERROR:
            exc = event.exception
            entry["status"] = FAILED
            entry["error"] = describe(exc)
            entry["failed_channels"] = dict(getattr(exc, "failed_channels", {}))
            log.error("JOB FAILED %s at %s: %s", event.job_id, entry["last_run_at"], entry["error"])
        else:
            retval = getattr(event, "retval", None)
            partial = retval.get("partial_errors") if isinstance(retval, dict) else None
            if partial:
                entry["status"] = DEGRADED
                entry["partial_errors"] = dict(partial)
                log.warning("JOB DEGRADED %s at %s: %s", event.job_id, entry["last_run_at"], partial)
            else:
                entry["status"] = SUCCESS
        with self._lock:
            previous = self._jobs.get(event.job_id) or {}
            self._jobs[event.job_id] = entry
            # The interval ticks (autopilot every 30 s, shorts_dispatch every
            # 5 s) rewrite the file at most once a minute unless their status
            # changes; a cron job runs far less often, so every run is saved.
            now = time.monotonic()
            if (entry["status"] != previous.get("status")
                    or now - self._saved_at.get(event.job_id, float("-inf")) >= SAVE_EVERY_SECONDS):
                self._saved_at[event.job_id] = now
                self._save()

    def last_run_at(self, job_id: str) -> datetime | None:
        """When the job last ran (any outcome), or None if never."""
        with self._lock:
            at = (self._jobs.get(job_id) or {}).get("last_run_at")
        return datetime.fromisoformat(at) if at else None

    def _save(self) -> None:
        """Write the registry to the persist file; the caller holds the lock.
        A failed write is logged, never raised: it costs the record, not the run."""
        if self._path is None:
            return
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self._jobs, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.warning("job status: could not write %s: %s", self._path, e)

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {
                job_id: {**entry, "failed_channels": dict(entry["failed_channels"]),
                         "partial_errors": dict(entry["partial_errors"])}
                for job_id, entry in self._jobs.items()
            }


registry = JobStatusRegistry()
