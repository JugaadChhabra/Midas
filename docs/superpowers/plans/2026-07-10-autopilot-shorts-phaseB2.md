# Autopilot Shorts Action (Phase B2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an autopilot action so Midas automatically cuts new long-form videos into shorts per channel, independent of the existing metadata-audit autopilot, with per-channel enable + daily/upload caps.

**Architecture:** A new self-contained `_run_shorts_action(ch)` helper (plus `_next_uncut_video_for_channel` and `_shorts_made_today`) does the work: pick the newest un-cut long-form public video, enqueue a `shorts_jobs` row with `autopilot_generated=True` and the channel's upload cap, and start the cutter thread — serialized by the existing `has_active_job()` 409 guard. `tick()` calls it right after sync, gated by a new `autopilot_shorts_enabled` channel flag, and the channel-selection query is widened so shorts-only channels still get ticked. Per-channel settings are exposed through the existing `PATCH /auth/channels/{id}` + the autopilot card UI.

**Tech Stack:** FastAPI, Supabase (postgrest), APScheduler (existing autopilot tick), the ported cutter runner (`app/shorts/runner.py`), vanilla JS in `channel.html`.

**Spec:** `docs/superpowers/specs/2026-07-09-shorts-entrypoints-design.md` (Phase B2; Phase A Docker deploy is a separate plan).

## Global Constraints

- Repo: `~/Documents/Github/Midas`, branch = a fresh branch off `main` (main already has the cutter + Phase B1). Python: `venv/bin/python`, tests `venv/bin/pytest` (note `venv`, not `.venv`).
- Shorts autopilot is INDEPENDENT of the metadata-audit toggle: a channel may run audit-only, shorts-only, both, or neither.
- One cut at a time: `_run_shorts_action` enqueues at most one job per tick and does nothing when `has_active_job()` is true (reject-when-busy; no queue).
- Autopilot shorts uploads only the top-N clips: the enqueued job sets `upload_cap = channel.autopilot_shorts_upload_cap` (the B1 runner already holds the rest as PENDING).
- Dedup: never auto-cut a video that already has ANY `shorts_jobs` row (re-cut is a manual action only).
- Only `is_short = False` (known long-form) public videos are eligible.
- `app/autopilot.py` importing `app.shorts.runner` is startup-safe: the runner imports the cutter lazily, so no cv2/torch is pulled at app import. Verify after Task 3: `venv/bin/python -c "import app.main, sys; print('cv2' not in sys.modules and 'torch' not in sys.modules)"` → `True`.
- Full suite (`venv/bin/pytest tests/ -q`) must stay green before every commit (currently 150 pass on main).
- Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Migration — autopilot-shorts columns on `channels`

**Files:**
- Create: `supabase/migrations/20260710120000_autopilot_shorts.sql`

**Interfaces:**
- Produces: `channels.autopilot_shorts_enabled bool`, `autopilot_shorts_daily_cap int`, `autopilot_shorts_upload_cap int`, `shorts_cut_mode text`, `shorts_camera_motion text` — consumed by Tasks 2-5.

- [ ] **Step 1: Write the migration**

```sql
-- Autopilot shorts (docs/superpowers/specs/2026-07-09-shorts-entrypoints-design.md, Phase B2).
-- Independent of the metadata-audit autopilot toggle. Daily cap = source videos
-- cut per day; upload cap = clips auto-uploaded per cut (rest held as PENDING).
alter table channels add column if not exists autopilot_shorts_enabled    boolean not null default false;
alter table channels add column if not exists autopilot_shorts_daily_cap   int not null default 1;
alter table channels add column if not exists autopilot_shorts_upload_cap  int not null default 2;
alter table channels add column if not exists shorts_cut_mode              text not null default 'highlights';
alter table channels add column if not exists shorts_camera_motion         text not null default 'calm';
```

- [ ] **Step 2: Push and verify**

```bash
cd ~/Documents/Github/Midas && supabase db push
```
Verify: `venv/bin/python -c "from app.db import supabase; print(supabase().table('channels').select('id,autopilot_shorts_enabled,autopilot_shorts_daily_cap,autopilot_shorts_upload_cap,shorts_cut_mode,shorts_camera_motion').limit(1).execute().data)"` → runs without error, defaults present.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260710120000_autopilot_shorts.sql
git commit -m "feat: channels autopilot-shorts columns (enabled, daily/upload caps, cut mode, motion)"
```

---

### Task 2: Core helpers — `_next_uncut_video_for_channel`, `_shorts_made_today`, `_run_shorts_action`

**Files:**
- Modify: `app/autopilot.py` (add imports + three helpers; do NOT touch `tick()` yet)
- Test: `tests/test_autopilot_shorts.py`

**Interfaces:**
- Consumes: `has_active_job() -> bool`, `start_job_thread(job_id: int) -> Thread` from `app.shorts.runner`; `_today_start_iso()` (existing in autopilot.py).
- Produces:
  - `_next_uncut_video_for_channel(channel_id: str) -> dict | None` — newest-published public `is_short=False` video with no existing `shorts_jobs` row.
  - `_shorts_made_today(channel_id: str) -> int` — count of `shorts_jobs` with `autopilot_generated=True` created since `_today_start_iso()`.
  - `_run_shorts_action(ch: dict) -> None` — enqueue at most one autopilot cut for channel `ch`. No-op when busy, over cap, or no eligible video. Task 3 calls this from `tick()`.

- [ ] **Step 1: Add the imports** at the top of `app/autopilot.py`, after the existing `from app.embeddings import embed_video` line (line 15):

```python
from app.shorts.runner import has_active_job, start_job_thread
```
(This is startup-safe — `app.shorts.runner` imports the cutter lazily, so no cv2/torch at import time.)

- [ ] **Step 2: Write the failing tests** — `tests/test_autopilot_shorts.py`:

```python
from unittest.mock import MagicMock, patch


def _sb(videos, shorts_jobs, recorder):
    """supabase() stand-in for the shorts helpers.
    - videos: .table('videos').select().eq().order().execute().data
    - shorts_jobs select: .table('shorts_jobs').select().eq()[.eq()][.in_()][.gte()].execute().data
    - shorts_jobs insert: recorded, returns a row with id 99
    """
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "videos":
            # query is .select('*').eq('channel_id',..).eq('is_short', False).order(..).execute()
            t.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value.data = videos
        if name == "shorts_jobs":
            # select chains used: .select(...).eq('channel_id',..).in_('source_video_id',..).execute()
            # and .select(...).eq('channel_id',..).eq('autopilot_generated',..).gte('created_at',..).execute()
            sel = t.select.return_value
            sel.eq.return_value.in_.return_value.execute.return_value.data = shorts_jobs["by_source"]
            sel.eq.return_value.eq.return_value.gte.return_value.execute.return_value.data = shorts_jobs["today"]

            def _insert(fields):
                recorder.append(fields)
                ins = MagicMock()
                ins.execute.return_value.data = [{"id": 99, **fields}]
                return ins
            t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


CH = {"id": "UC1", "autopilot_shorts_daily_cap": 1, "autopilot_shorts_upload_cap": 2,
      "shorts_cut_mode": "highlights", "shorts_camera_motion": "calm"}


def test_next_uncut_skips_shorts_nonpublic_and_already_cut():
    import app.autopilot as ap
    videos = [
        {"id": "vShort", "channel_id": "UC1", "is_short": True, "privacy_status": "public"},
        {"id": "vPriv", "channel_id": "UC1", "is_short": False, "privacy_status": "private"},
        {"id": "vCut", "channel_id": "UC1", "is_short": False, "privacy_status": "public"},
        {"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"},
    ]
    # NOTE: videos here is the already-filtered is_short=False set the query returns;
    # the query itself applies .eq('is_short', False), so vShort won't be in `videos`.
    long_videos = [v for v in videos if not v["is_short"]]
    sj = {"by_source": [{"source_video_id": "vCut"}], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, [])):
        v = ap._next_uncut_video_for_channel("UC1")
    assert v is not None and v["id"] == "vGood"


def test_run_shorts_action_enqueues_when_eligible():
    import app.autopilot as ap
    rec = []
    long_videos = [{"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = {"by_source": [], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, rec)), \
         patch("app.autopilot.has_active_job", return_value=False), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert len(rec) == 1
    job = rec[0]
    assert job["source_video_id"] == "vGood"
    assert job["autopilot_generated"] is True
    assert job["upload_cap"] == 2
    assert job["cut_mode"] == "highlights" and job["camera_motion"] == "calm"
    assert job["status"] == "CREATED"
    start.assert_called_once_with(99)


def test_run_shorts_action_noop_when_busy():
    import app.autopilot as ap
    rec = []
    with patch("app.autopilot.supabase", return_value=_sb([], {"by_source": [], "today": []}, rec)), \
         patch("app.autopilot.has_active_job", return_value=True), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert rec == [] and start.call_count == 0


def test_run_shorts_action_noop_over_daily_cap():
    import app.autopilot as ap
    rec = []
    long_videos = [{"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = {"by_source": [], "today": [{"id": 1}]}   # already 1 today, cap is 1
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, rec)), \
         patch("app.autopilot.has_active_job", return_value=False), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert rec == [] and start.call_count == 0


def test_run_shorts_action_noop_when_no_eligible_video():
    import app.autopilot as ap
    rec = []
    sj = {"by_source": [], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb([], sj, rec)), \
         patch("app.autopilot.has_active_job", return_value=False), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert rec == [] and start.call_count == 0
```

- [ ] **Step 3: Run to verify they fail**

```bash
venv/bin/pytest tests/test_autopilot_shorts.py -q
```
Expected: FAIL — `AttributeError: module 'app.autopilot' has no attribute '_next_uncut_video_for_channel'` (and the others).

- [ ] **Step 4: Add the three helpers** to `app/autopilot.py`, immediately AFTER `_next_video_for_channel` (after its `return None`, ~line 146):

```python
def _next_uncut_video_for_channel(channel_id: str) -> dict | None:
    """Newest-published public long-form video with no shorts_jobs row yet.

    Long-form only (is_short=False); shorts are never re-cut into shorts. A
    video with ANY existing shorts_jobs row (working, done, or failed) is
    skipped — re-cutting is a manual action.
    """
    candidates = (
        supabase().table("videos")
        .select("*")
        .eq("channel_id", channel_id)
        .eq("is_short", False)
        .order("published_at", desc=True)
        .execute()
    ).data or []
    if not candidates:
        return None
    candidate_ids = [v["id"] for v in candidates]
    jobs = (
        supabase().table("shorts_jobs")
        .select("source_video_id")
        .eq("channel_id", channel_id)
        .in_("source_video_id", candidate_ids)
        .execute()
    ).data or []
    cut_ids = {j["source_video_id"] for j in jobs if j.get("source_video_id")}
    for v in candidates:
        if v["id"] in cut_ids:
            continue
        privacy = v.get("privacy_status")
        if privacy is not None and privacy != "public":
            continue
        return v
    return None


def _shorts_made_today(channel_id: str) -> int:
    res = (
        supabase().table("shorts_jobs")
        .select("id")
        .eq("channel_id", channel_id)
        .eq("autopilot_generated", True)
        .gte("created_at", _today_start_iso())
        .execute()
    )
    return len(res.data or [])


def _run_shorts_action(ch: dict) -> None:
    """Enqueue at most one autopilot shorts cut for this channel.

    No-op when a cut is already running (one-at-a-time), when today's autopilot
    shorts count is at/over the channel cap, or when there is no eligible video.
    """
    channel_id = ch["id"]
    if has_active_job():
        return  # a cut is already running; try again next tick
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
    start_job_thread(job_id)
    log.info("Autopilot shorts: started job %d for video %s (channel %s)", job_id, video["id"], channel_id)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
venv/bin/pytest tests/test_autopilot_shorts.py -q && venv/bin/pytest tests/ -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/autopilot.py tests/test_autopilot_shorts.py
git commit -m "feat: autopilot shorts helpers — eligible-video selection, daily count, enqueue action"
```

---

### Task 3: Wire the shorts action into `tick()`

**Files:**
- Modify: `app/autopilot.py` (`tick()` — the channel-selection query + one inserted block)
- Test: `tests/test_autopilot_shorts_tick.py`

**Interfaces:**
- Consumes: `_run_shorts_action(ch)` from Task 2.
- Produces: `tick()` now (a) selects channels where `autopilot_enabled` OR `autopilot_shorts_enabled` (and not paused); (b) runs `_run_shorts_action(ch)` after sync when `autopilot_shorts_enabled`; (c) runs the existing audit path only when `autopilot_enabled`.

- [ ] **Step 1: Widen the channel-selection query.** In `tick()`, replace the channel query (currently `.eq("autopilot_enabled", True).is_("autopilot_paused_reason", "null")`, ~lines 183-187) with an OR over both toggles:

```python
        channels = (
            supabase().table("channels")
            .select("*")
            .or_("autopilot_enabled.eq.true,autopilot_shorts_enabled.eq.true")
            .is_("autopilot_paused_reason", "null")
            .execute()
        ).data or []
```

- [ ] **Step 2: Insert the shorts action + audit-path gate.** Immediately AFTER the sync block (after the `if needs_sync:` block ends — the line before `# 4. Daily cap check`, ~line 239) and BEFORE `# 4. Daily cap check`, insert:

```python
        # Shorts autopilot — independent of the metadata-audit path. Enqueues at
        # most one cut per tick, serialized by has_active_job (never overlaps).
        if ch.get("autopilot_shorts_enabled"):
            try:
                _run_shorts_action(ch)
            except Exception as e:
                log.exception("Shorts autopilot failed for %s: %s", channel_id, e)

        # The metadata-audit path (daily cap → pick → audit → apply) runs only for
        # channels with metadata autopilot enabled. Shorts-only channels stop here.
        if not ch.get("autopilot_enabled"):
            _touch_tick(channel_id)
            return
```
Everything from `# 4. Daily cap check` onward stays byte-identical.

- [ ] **Step 3: Write the wiring tests** — `tests/test_autopilot_shorts_tick.py`. Read `tests/test_autopilot_full_sync.py` first and mirror its `tick()` mocking style (it already stubs the supabase channel query, sync, and the audit calls). Assert the routing:

```python
from unittest.mock import MagicMock, patch


def _run_tick_with_channel(channel_row):
    """Run tick() with the channel query returning one channel, sync/audit stubbed.
    Returns (shorts_called: bool, audit_called: bool)."""
    import app.autopilot as ap

    sb = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "channels":
            t.select.return_value.or_.return_value.is_.return_value.execute.return_value.data = [channel_row]
        return t
    sb.table.side_effect = table

    with patch("app.autopilot.supabase", return_value=sb), \
         patch("app.autopilot._run_shorts_action") as shorts, \
         patch("app.autopilot._touch_tick"), \
         patch("app.autopilot._needs_full_sync", return_value=False), \
         patch("app.autopilot.sync_channel"), patch("app.autopilot.refresh_stats"), \
         patch("app.autopilot._applies_today", return_value=0), \
         patch("app.autopilot._next_video_for_channel", return_value=None) as nextvid:
        # last_synced_at recent so needs_sync is False and we skip the sync branch
        from datetime import datetime, timezone
        channel_row.setdefault("last_synced_at", datetime.now(timezone.utc).isoformat())
        ap.tick()
        # audit path "entered" == _next_video_for_channel was consulted
        return shorts.called, nextvid.called


def test_shorts_only_channel_runs_shorts_not_audit():
    shorts_called, audit_called = _run_tick_with_channel(
        {"id": "UC1", "autopilot_enabled": False, "autopilot_shorts_enabled": True})
    assert shorts_called is True
    assert audit_called is False   # audit path skipped for shorts-only channel


def test_audit_only_channel_runs_audit_not_shorts():
    shorts_called, audit_called = _run_tick_with_channel(
        {"id": "UC1", "autopilot_enabled": True, "autopilot_shorts_enabled": False})
    assert shorts_called is False
    assert audit_called is True


def test_both_enabled_runs_both():
    shorts_called, audit_called = _run_tick_with_channel(
        {"id": "UC1", "autopilot_enabled": True, "autopilot_shorts_enabled": True})
    assert shorts_called is True
    assert audit_called is True
```
Note: if `tick()`'s sync/quota branches consume supabase calls that this mock doesn't satisfy, mirror exactly how `tests/test_autopilot_full_sync.py` stubs them (that file is the source of truth for the tick mock shape). Do not weaken the assertions — the three routing outcomes above are the contract.

- [ ] **Step 4: Run tests + startup-safety check**

```bash
venv/bin/pytest tests/test_autopilot_shorts_tick.py -q && venv/bin/pytest tests/ -q
venv/bin/python -c "import app.main, sys; print('startup light:', 'cv2' not in sys.modules and 'torch' not in sys.modules)"
```
Expected: tests PASS; startup light prints `True`.

- [ ] **Step 5: Commit**

```bash
git add app/autopilot.py tests/test_autopilot_shorts_tick.py
git commit -m "feat: tick() runs autopilot shorts action independently of metadata audit"
```

---

### Task 4: Channel settings — model + PATCH handler

**Files:**
- Modify: `app/auth.py` (`ChannelSettings` model + `update_channel` handler)
- Test: `tests/test_channel_settings_shorts.py`

**Interfaces:**
- Produces: `PATCH /auth/channels/{id}` accepts `autopilot_shorts_enabled` (bool), `autopilot_shorts_daily_cap` (int, clamped 1-20), `autopilot_shorts_upload_cap` (int, clamped 1-8), `shorts_cut_mode` (`highlights`|`coverage`), `shorts_camera_motion` (`locked`|`calm`|`follow`), persisting valid values to `channels`.

- [ ] **Step 1: Write the failing test** — `tests/test_channel_settings_shorts.py`:

```python
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _sb(recorder):
    sb = MagicMock()
    def _update(patch_dict):
        recorder.append(patch_dict)
        u = MagicMock()
        u.eq.return_value.execute.return_value.data = [{}]
        return u
    sb.table.return_value.update.side_effect = _update
    return sb


def test_patch_persists_shorts_autopilot_settings():
    rec = []
    body = {"autopilot_shorts_enabled": True, "autopilot_shorts_daily_cap": 3,
            "autopilot_shorts_upload_cap": 2, "shorts_cut_mode": "coverage",
            "shorts_camera_motion": "follow"}
    with patch("app.auth.supabase", return_value=_sb(rec)):
        r = _client().patch("/auth/channels/UC1", json=body)
    assert r.status_code == 200
    p = rec[0]
    assert p["autopilot_shorts_enabled"] is True
    assert p["autopilot_shorts_daily_cap"] == 3
    assert p["autopilot_shorts_upload_cap"] == 2
    assert p["shorts_cut_mode"] == "coverage"
    assert p["shorts_camera_motion"] == "follow"


def test_patch_clamps_and_rejects_bad_enums():
    rec = []
    body = {"autopilot_shorts_daily_cap": 999, "autopilot_shorts_upload_cap": 0,
            "shorts_cut_mode": "bogus", "shorts_camera_motion": "bogus"}
    with patch("app.auth.supabase", return_value=_sb(rec)):
        r = _client().patch("/auth/channels/UC1", json=body)
    assert r.status_code == 200
    p = rec[0]
    assert p["autopilot_shorts_daily_cap"] == 20      # clamped to max
    assert p["autopilot_shorts_upload_cap"] == 1       # clamped to min
    assert "shorts_cut_mode" not in p                  # invalid enum ignored
    assert "shorts_camera_motion" not in p
```

- [ ] **Step 2: Run to verify it fails**

```bash
venv/bin/pytest tests/test_channel_settings_shorts.py -q
```
Expected: FAIL (fields not in model / not persisted).

- [ ] **Step 3: Extend `ChannelSettings`** in `app/auth.py` (after `playlist_health_enabled`, line 122):

```python
class ChannelSettings(BaseModel):
    default_language: str | None = None
    autopilot_enabled: bool | None = None
    autopilot_daily_cap: int | None = None
    sync_shorts: bool | None = None
    playlist_health_enabled: bool | None = None
    autopilot_shorts_enabled: bool | None = None
    autopilot_shorts_daily_cap: int | None = None
    autopilot_shorts_upload_cap: int | None = None
    shorts_cut_mode: str | None = None
    shorts_camera_motion: str | None = None
```

- [ ] **Step 4: Extend `update_channel`** — add these blocks before the `if not patch:` guard (after the `playlist_health_enabled` block, ~line 140):

```python
    if body.autopilot_shorts_enabled is not None:
        patch["autopilot_shorts_enabled"] = body.autopilot_shorts_enabled
    if body.autopilot_shorts_daily_cap is not None:
        patch["autopilot_shorts_daily_cap"] = max(1, min(int(body.autopilot_shorts_daily_cap), 20))
    if body.autopilot_shorts_upload_cap is not None:
        patch["autopilot_shorts_upload_cap"] = max(1, min(int(body.autopilot_shorts_upload_cap), 8))
    if body.shorts_cut_mode in ("highlights", "coverage"):
        patch["shorts_cut_mode"] = body.shorts_cut_mode
    if body.shorts_camera_motion in ("locked", "calm", "follow"):
        patch["shorts_camera_motion"] = body.shorts_camera_motion
```
(Invalid enums are silently ignored — the `in (...)` guards only add valid values, and `None` never matches, so an unset field is untouched.)

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/test_channel_settings_shorts.py -q && venv/bin/pytest tests/ -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/auth.py tests/test_channel_settings_shorts.py
git commit -m "feat: channel settings accept autopilot-shorts config (enabled, caps, mode, motion)"
```

---

### Task 5: Autopilot card UI — shorts controls

**Files:**
- Modify: `app/static/channel.html` (autopilot card HTML + the `ap-save` handler + wherever autopilot settings are loaded into the form)

**Interfaces:**
- Consumes: `PATCH /auth/channels/{id}` shorts fields (Task 4); the channel's current settings (however the page currently populates `ap-enabled`/`ap-cap`).

- [ ] **Step 1: Read the current file** to confirm the autopilot card block (`data-panel="autopilot"`, with `ap-enabled`/`ap-cap`/`ap-save`), the `ap-save` handler, and the function that loads current autopilot settings into `ap-enabled`/`ap-cap` (search for where `ap-enabled` `.checked` is set from a fetch — likely a `loadChannel`/`loadAutopilot` function). Match live anchors; do not guess line numbers.

- [ ] **Step 2: Add shorts controls to the autopilot card.** Inside the autopilot `.card`, after the existing `.row` that holds `ap-enabled`/`ap-cap`/`ap-save` (and before `ap-summary`), add a shorts sub-section:

```html
      <div class="row" style="margin-top:.6rem; padding-top:.6rem; border-top:1px solid #8883">
        <label><input type="checkbox" id="ap-shorts-enabled" /> Auto-generate shorts (long-form videos)</label>
        <label class="muted">Videos/day:
          <input id="ap-shorts-cap" type="number" min="1" max="20" value="1" style="width:4rem; margin-left:.25rem;" />
        </label>
        <label class="muted">Upload top:
          <input id="ap-shorts-upload" type="number" min="1" max="8" value="2" style="width:4rem; margin-left:.25rem;" />
        </label>
        <label class="muted">Mode:
          <select id="ap-shorts-mode" style="margin-left:.25rem;">
            <option value="highlights">Highlights</option>
            <option value="coverage">Full coverage</option>
          </select>
        </label>
        <label class="muted">Camera:
          <select id="ap-shorts-motion" style="margin-left:.25rem;">
            <option value="locked">Locked</option>
            <option value="calm" selected>Calm</option>
            <option value="follow">Follow</option>
          </select>
        </label>
      </div>
```
(The single existing `Save` button saves the whole card — no second button.)

- [ ] **Step 3: Extend the `ap-save` handler** to include the shorts fields in the PATCH body:

```javascript
$('ap-save').onclick = async () => {
  try {
    const r = await fetch(`/auth/channels/${channelId}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        autopilot_enabled: $('ap-enabled').checked,
        autopilot_daily_cap: parseInt($('ap-cap').value || '10', 10),
        autopilot_shorts_enabled: $('ap-shorts-enabled').checked,
        autopilot_shorts_daily_cap: parseInt($('ap-shorts-cap').value || '1', 10),
        autopilot_shorts_upload_cap: parseInt($('ap-shorts-upload').value || '2', 10),
        shorts_cut_mode: $('ap-shorts-mode').value,
        shorts_camera_motion: $('ap-shorts-motion').value,
      }),
    });
    if (!r.ok) throw new Error(await r.text());
    toast('Autopilot settings saved.', 'ok');
    await loadAutopilotLog();
  } catch (e) { toast('Save failed: ' + escapeHtml(String(e)), 'err'); }
};
```

- [ ] **Step 4: Populate the shorts controls on load.** Find where the page sets `ap-enabled.checked` / `ap-cap.value` from the loaded channel object (the same fetch that drives the autopilot card). Add, right beside those lines, using the same channel object (call it `c`/`ch` — match the file's variable):

```javascript
  $('ap-shorts-enabled').checked = !!c.autopilot_shorts_enabled;
  $('ap-shorts-cap').value = c.autopilot_shorts_daily_cap ?? 1;
  $('ap-shorts-upload').value = c.autopilot_shorts_upload_cap ?? 2;
  if (c.shorts_cut_mode) $('ap-shorts-mode').value = c.shorts_cut_mode;
  if (c.shorts_camera_motion) $('ap-shorts-motion').value = c.shorts_camera_motion;
```
If the loader fetches the channel from an endpoint that does not yet return these columns, confirm it selects `*` or add the columns to its select — the settings must round-trip (save then reload shows the saved values).

- [ ] **Step 5: Serve-check**

```bash
cd ~/Documents/Github/Midas
venv/bin/uvicorn app.main:app --port 8135 >/tmp/b2ui.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "%{http_code}\n" localhost:8135/channel   # expect 200
curl -s localhost:8135/channel | grep -o 'ap-shorts-enabled\|ap-shorts-cap\|ap-shorts-mode' | sort -u   # expect all three
kill %1 2>/dev/null
venv/bin/pytest tests/ -q   # unaffected
```

- [ ] **Step 6: Commit**

```bash
git add app/static/channel.html
git commit -m "feat: autopilot card shorts controls (enable, caps, mode, motion) wired to channel settings"
```

- [ ] **Step 7: Real check (manual, on the Mac)** — start the server, open the channel dashboard's Autopilot tab, enable "Auto-generate shorts", set videos/day=1, save, reload, confirm the setting persisted. Then (optionally, to see it fire without waiting for the 120s tick on a fresh channel) confirm a `shorts_jobs` row with `autopilot_generated=true` appears for the newest un-cut long-form video within a tick or two. (Full autopilot behavior over time is validated in the Phase A deployed run.)
