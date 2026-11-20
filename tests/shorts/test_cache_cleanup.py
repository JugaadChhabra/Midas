"""Shorts cache cleanup: never a running job, NAS jobs at once, the rest by age."""
import os
import time
from unittest.mock import patch

import pytest

from app.shorts import cache_cleanup


def _dir(root, name, age_days=0.0, size=100):
    d = root / name
    (d / "clips").mkdir(parents=True)
    f = d / "clips" / "a.mp4"
    f.write_bytes(b"x" * size)
    t = time.time() - age_days * 86400
    for p in (f, d / "clips", d):
        os.utime(p, (t, t))
    return d


JOBS = {
    1: {"id": 1, "status": "RENDERING", "source_nas_path": "HINDI/a.mp4"},
    2: {"id": 2, "status": "DONE", "source_nas_path": "HINDI/b.mp4"},
    3: {"id": 3, "status": "FAILED", "source_nas_path": "HINDI/c.mp4"},
    4: {"id": 4, "status": "DONE", "source_nas_path": None},
    5: {"id": 5, "status": "DONE", "source_nas_path": None},
    7: {"id": 7, "status": "CREATED", "source_nas_path": None},
}


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    _dir(root, "1", age_days=30)      # running: kept however old
    _dir(root, "2")                   # NAS, done: removed now
    _dir(root, "3")                   # NAS, failed: removed now
    _dir(root, "4", age_days=1)       # URL job, recent: kept
    _dir(root, "5", age_days=10)      # URL job, old: removed
    _dir(root, "6")                   # not in the DB: removed
    _dir(root, "7", age_days=30)      # queued: kept
    _dir(root, "legacy", age_days=10)  # old non-job folder: removed
    _dir(root, "fresh")                # recent non-job folder: kept
    return root


def _run(cache, **kw):
    with patch.object(cache_cleanup, "_jobs", lambda ids: {i: JOBS[i] for i in ids if i in JOBS}):
        return cache_cleanup.clean_cache(cache_dir=cache, keep_days=7, **kw)


def test_removes_what_nothing_needs(cache):
    result = _run(cache)
    assert sorted(p.name for p in cache.iterdir()) == ["1", "4", "7", "fresh"]
    assert sorted(r["name"] for r in result["removed"]) == ["2", "3", "5", "6", "legacy"]
    assert result["freed_bytes"] == 500 and result["kept"] == 4


def test_dry_run_deletes_nothing(cache):
    before = sorted(p.name for p in cache.iterdir())
    result = _run(cache, dry_run=True)
    assert sorted(p.name for p in cache.iterdir()) == before
    assert len(result["removed"]) == 5


def test_missing_cache_dir_is_fine(tmp_path):
    assert _run(tmp_path / "nope")["removed"] == []


def test_refuses_home_or_root():
    with pytest.raises(ValueError):
        cache_cleanup.clean_cache(cache_dir="/")
    with pytest.raises(ValueError):
        cache_cleanup.clean_cache(cache_dir=os.path.expanduser("~"))
