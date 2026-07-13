"""The postgrest .execute() retry wrapper must cover ALL builder classes.

Regression: only SyncQueryRequestBuilder was patched, so `.single().execute()`
and `.maybe_single().execute()` (different builder classes with their own
execute) bypassed the retry — a transient Supabase ReadTimeout then escaped
unretried and killed background job threads (run_shorts_job fetching its row).
"""
import types

import httpx
import pytest

import app.db as db
from postgrest._sync.request_builder import (
    SyncMaybeSingleRequestBuilder,
    SyncQueryRequestBuilder,
    SyncSingleRequestBuilder,
)


@pytest.mark.parametrize(
    "cls", [SyncQueryRequestBuilder, SyncSingleRequestBuilder, SyncMaybeSingleRequestBuilder]
)
def test_execute_is_wrapped_on_all_builders(cls):
    # Importing app.db monkey-patches these at import time. The wrapped function
    # is named _execute_with_retry; the postgrest original is 'execute'.
    assert cls.__dict__["execute"].__name__ == "_execute_with_retry", (
        f"{cls.__name__}.execute is not retry-wrapped"
    )


def test_wrapped_execute_retries_on_read_timeout(monkeypatch):
    calls = {"n": 0}

    def flaky(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("stale socket")
        return "OK"

    # Don't touch the real per-thread client / network during the recycle step.
    monkeypatch.setattr(db, "_reset_thread_client", lambda: None)
    monkeypatch.setattr(
        db, "supabase",
        lambda: types.SimpleNamespace(postgrest=types.SimpleNamespace(session=None)),
    )

    wrapped = db._make_execute_with_retry(flaky)
    fake_self = types.SimpleNamespace(http_method="GET", path="/shorts_jobs", session=None)
    assert wrapped(fake_self) == "OK"
    assert calls["n"] == 2          # failed once, retried, succeeded


def test_wrapped_execute_reraises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(db, "_reset_thread_client", lambda: None)
    monkeypatch.setattr(
        db, "supabase",
        lambda: types.SimpleNamespace(postgrest=types.SimpleNamespace(session=None)),
    )

    def always_timeout(self):
        raise httpx.ReadTimeout("dead")

    wrapped = db._make_execute_with_retry(always_timeout)
    fake_self = types.SimpleNamespace(http_method="GET", path="/x", session=None)
    with pytest.raises(httpx.ReadTimeout):
        wrapped(fake_self)
