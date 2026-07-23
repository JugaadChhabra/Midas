"""Single owner of the shorts job/clip status vocabulary.

These exact strings are persisted in the ``shorts_jobs.status`` and
``shorts_clips.upload_status`` DB columns and matched by string in the frontend
(``app/static/*.html``). The VALUES here are load-bearing and must never change;
this module only centralises WHERE they live so dispatcher/runner/worker/routes/
nas_source stop redefining or hardcoding them.

Plain module-level string constants (not an Enum) so every existing
``== "CREATED"`` comparison, ``in`` membership test, and DB write keeps working
byte-for-byte.
"""
from __future__ import annotations

# ── shorts_jobs.status values ──
CREATED = "CREATED"
DOWNLOADING = "DOWNLOADING"
ANALYSING = "ANALYSING"
RENDERING = "RENDERING"
UPLOADING = "UPLOADING"
DONE = "DONE"
FAILED = "FAILED"

# ── shorts_clips.upload_status values ──
# (CLIP_ prefix disambiguates from the same-named job statuses above.)
CLIP_PENDING = "PENDING"
CLIP_UPLOADING = "UPLOADING"
CLIP_UPLOADED = "UPLOADED"
CLIP_FAILED = "FAILED"
CLIP_SAVED = "SAVED"

# ── grouping sets ──
# A job a worker has queued or is actively running.
WORKING_STATUSES = (CREATED, DOWNLOADING, ANALYSING, RENDERING, UPLOADING)

# The subset of WORKING_STATUSES a worker has actually started (excludes the
# queued CREATED state). Only these are reaped on restart; CREATED jobs survive
# to be re-dispatched.
IN_PROGRESS_STATUSES = tuple(s for s in WORKING_STATUSES if s != CREATED)

# Statuses a finished worker leaves behind; anything else after exit is a crash.
TERMINAL_STATUSES = (DONE, FAILED)
