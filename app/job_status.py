"""In-process record of every scheduled job's last run, served at /health/jobs.

Per-channel jobs isolate each channel's exception so one bad channel can't stop
the rest. Before this module that isolation also hid the failure: APScheduler
logged the run as "executed successfully" and `playlist_health_score` raised
`NameError` daily for seven weeks unnoticed. Now `_run_per_channel` raises
`JobRunFailed` once every channel has run, APScheduler fires `EVENT_JOB_ERROR`,
and the listener here records it. The jobs that loop on their own
(`poll_metrics`, `poll_reporting`, `main._daily_measurement_eval`) raise the
same exception after their pass.

In-memory only: a restart clears it. Persisting it is Phase B work.
"""
import logging
import threading

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

log = logging.getLogger("midas.job_status")

NEVER_RUN = "never_run"
SUCCESS = "success"
FAILED = "failed"


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


def _blank() -> dict:
    return {"status": NEVER_RUN, "last_run_at": None, "error": None, "failed_channels": {}}


class JobStatusRegistry:
    """Last status per job id. Thread-safe: listeners run on executor threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def register(self, job_id: str) -> None:
        """Show a job before its first run, so a missing job is distinguishable
        from one that simply hasn't fired yet."""
        with self._lock:
            self._jobs.setdefault(job_id, _blank())

    def watch(self, scheduler) -> None:
        """Register every job already added to ``scheduler`` and listen for runs."""
        for job in scheduler.get_jobs():
            self.register(job.id)
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
            entry["status"] = SUCCESS
        with self._lock:
            self._jobs[event.job_id] = entry

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {
                job_id: {**entry, "failed_channels": dict(entry["failed_channels"])}
                for job_id, entry in self._jobs.items()
            }


registry = JobStatusRegistry()
