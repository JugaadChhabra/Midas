# Per-Channel NAS Auto-Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the NAS pick → cut → save flow per channel — a folder-mapped, toggle-driven auto-cut plus an on-demand "Cut now", controlled from each channel's Autopilot tab.

**Architecture:** Purely additive/re-pointing. The autopilot's `_run_shorts_action` is re-pointed at the existing `enqueue_language_jobs()` NAS helper; the existing APScheduler tick (120s) tops up the queue and the shorts dispatcher (5s) drains it at the concurrency cap. The channel API gains a `nas_folder` field; the UI gains one "Shorts (NAS)" card. No migration (columns already exist).

**Tech Stack:** Python, FastAPI, Supabase (`app.db.supabase()`), APScheduler, pytest, vanilla-JS static pages.

## Global Constraints

- **Delete nothing.** The YouTube fetch/cut/upload code and the legacy `_next_uncut_video_for_channel` / `_shorts_made_today` helpers stay (kept, just unused by the new action). Only the autopilot's *automatic enqueue* switches to NAS.
- **No YouTube upload** in this flow. NAS in → NAS out.
- **No migration** — `channels.nas_folder` and `channels.autopilot_shorts_enabled` already exist.
- Settings via `from app.config import settings`; DB via `from app.db import supabase`.
- The 11 NAS folders (uppercase): `BANGLA BHOJPURI ENGLISH GUJARATI HARYANVI HINDI MALAYALAM MARATHI PUNJABI RAJASTHANI TAMIL`.
- Run pytest via `venv/bin/pytest`.

---

## File Structure

- **Modify** `app/auth.py` — `list_channels` select, `ChannelSettings`, `update_channel` (accept/validate `nas_folder`).
- **Modify** `app/autopilot.py` — rewrite `_run_shorts_action` to enqueue from the channel's NAS folder.
- **Create** `scripts/backfill_nas_folder.py` — one-off auto-derive of `nas_folder` from channel names (with a pure, testable `derive_folder` helper).
- **Modify** `app/static/channel.html` — add the "Shorts (NAS)" card to the Autopilot tab + its JS.
- **Modify** `tests/test_channel_settings_shorts.py` — add a `nas_folder` PATCH test.
- **Modify** `tests/test_autopilot_shorts.py` — replace the 4 `_run_shorts_action` tests with NAS-behavior tests (keep the 5 `_next_uncut_video_for_channel` tests).
- **Create** `tests/test_backfill_nas_folder.py` — unit-test `derive_folder`.

## Execution Waves (dependencies)

- **Wave A (parallel — disjoint files):** Task 1 (auth), Task 2 (autopilot), Task 3 (backfill).
- **Wave B:** Task 4 (UI) — needs Task 1's `nas_folder` on the channel API.

---

### Task 1: Channel API — expose and accept `nas_folder`

**Files:**
- Modify: `app/auth.py:109` (select), `app/auth.py:119-129` (`ChannelSettings`), `app/auth.py:132-161` (`update_channel`)
- Test: `tests/test_channel_settings_shorts.py`

**Interfaces:**
- Consumes: `list_source_languages()` from `app.shorts.nas_source`.
- Produces: `GET /auth/channels` rows include `nas_folder`; `PATCH /auth/channels/{id}` accepts `nas_folder` (uppercased, validated ∈ folders, empty → NULL).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_channel_settings_shorts.py`:

```python
def test_patch_sets_valid_nas_folder():
    rec = []
    with patch("app.auth.supabase", return_value=_sb(rec)), \
         patch("app.auth.list_source_languages", return_value=["HINDI", "TAMIL"]):
        r = _client().patch("/auth/channels/UC1", json={"nas_folder": "hindi"})
    assert r.status_code == 200
    assert rec[0]["nas_folder"] == "HINDI"          # uppercased


def test_patch_rejects_unknown_nas_folder():
    rec = []
    with patch("app.auth.supabase", return_value=_sb(rec)), \
         patch("app.auth.list_source_languages", return_value=["HINDI"]):
        r = _client().patch("/auth/channels/UC1", json={"nas_folder": "KLINGON"})
    assert r.status_code == 400


def test_patch_clears_nas_folder_on_empty():
    rec = []
    with patch("app.auth.supabase", return_value=_sb(rec)), \
         patch("app.auth.list_source_languages", return_value=["HINDI"]):
        r = _client().patch("/auth/channels/UC1", json={"nas_folder": ""})
    assert r.status_code == 200
    assert rec[0]["nas_folder"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_channel_settings_shorts.py -k nas_folder -v`
Expected: FAIL — `nas_folder` not persisted / `AttributeError: app.auth has no attribute list_source_languages`.

- [ ] **Step 3: Add the import** — near the top of `app/auth.py`, with the other imports:

```python
from app.shorts.nas_source import list_source_languages
```

- [ ] **Step 4: Add `nas_folder` to the select** — in `list_channels`, extend the select string (line ~114) so it ends with `nas_folder`:

```python
        "autopilot_shorts_enabled,autopilot_shorts_daily_cap,autopilot_shorts_upload_cap,"
        "shorts_cut_mode,shorts_camera_motion,nas_folder"
```

- [ ] **Step 5: Add the field to `ChannelSettings`** — add one line to the model:

```python
    nas_folder: str | None = None
```

- [ ] **Step 6: Handle it in `update_channel`** — add before the `if not patch:` line:

```python
    if body.nas_folder is not None:
        folder = body.nas_folder.strip().upper()
        if folder and folder not in list_source_languages():
            raise HTTPException(400, f"Unknown NAS folder: {folder}")
        patch["nas_folder"] = folder or None
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_channel_settings_shorts.py -v`
Expected: PASS (all — the 2 existing + 3 new).

- [ ] **Step 8: Commit**

```bash
git add app/auth.py tests/test_channel_settings_shorts.py
git commit -m "feat(nas): channel API accepts and exposes nas_folder"
```

---

### Task 2: Autopilot — re-point `_run_shorts_action` to NAS

**Files:**
- Modify: `app/autopilot.py:242-271` (replace `_run_shorts_action` body)
- Test: `tests/test_autopilot_shorts.py` (replace the 4 `_run_shorts_action` tests)

**Interfaces:**
- Consumes: `enqueue_language_jobs(language, *, channel_id, autopilot, cut_mode, camera_motion)` from `app.shorts.nas_source`; `active_job_count()` (already imported); `settings.SHORTS_MAX_CONCURRENT_JOBS`.
- Produces: `_run_shorts_action(ch)` enqueues NAS jobs for `ch["nas_folder"]`; no-op without a folder or when the queue is at the cap.

- [ ] **Step 1: Replace the 4 old tests** — in `tests/test_autopilot_shorts.py`, delete the four functions `test_run_shorts_action_enqueues_when_eligible`, `test_run_shorts_action_noop_when_at_capacity`, `test_run_shorts_action_noop_over_daily_cap`, `test_run_shorts_action_noop_when_no_eligible_video` (lines ~112-160) and add:

```python
def test_run_shorts_action_enqueues_from_nas_folder():
    import app.autopilot as ap
    ch = {"id": "UC1", "nas_folder": "HINDI", "shorts_cut_mode": "highlights",
          "shorts_camera_motion": "calm"}
    with patch.object(ap, "active_job_count", return_value=0), \
         patch("app.shorts.nas_source.enqueue_language_jobs", return_value=3) as enq:
        ap._run_shorts_action(ch)
    enq.assert_called_once_with("HINDI", channel_id="UC1", autopilot=True,
                                cut_mode="highlights", camera_motion="calm")


def test_run_shorts_action_noop_without_folder():
    import app.autopilot as ap
    with patch("app.shorts.nas_source.enqueue_language_jobs") as enq:
        ap._run_shorts_action({"id": "UC1", "nas_folder": None})
    enq.assert_not_called()


def test_run_shorts_action_noop_when_at_capacity():
    import app.autopilot as ap
    ch = {"id": "UC1", "nas_folder": "HINDI"}
    with patch.object(ap, "active_job_count", return_value=99), \
         patch("app.shorts.nas_source.enqueue_language_jobs") as enq:
        ap._run_shorts_action(ch)
    enq.assert_not_called()


def test_run_shorts_action_swallows_unknown_folder():
    import app.autopilot as ap
    ch = {"id": "UC1", "nas_folder": "KLINGON"}
    with patch.object(ap, "active_job_count", return_value=0), \
         patch("app.shorts.nas_source.enqueue_language_jobs", side_effect=ValueError("nope")):
        ap._run_shorts_action(ch)   # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_autopilot_shorts.py -k run_shorts_action -v`
Expected: FAIL — old behavior still enqueues via the videos table / signatures don't match.

- [ ] **Step 3: Rewrite `_run_shorts_action`** — replace the whole function (lines ~242-271) with:

```python
def _run_shorts_action(ch: dict) -> None:
    """Enqueue NAS shorts cuts for this channel's language folder.

    No-op unless the channel has a nas_folder set. The shorts dispatcher
    (throttled by SHORTS_MAX_CONCURRENT_JOBS) drains the queue; enqueue's own
    in-flight dedup makes re-ticks idempotent, so we enqueue every uncut file
    and let the cap pace the actual cutting.
    """
    folder = ch.get("nas_folder")
    if not folder:
        return
    if active_job_count() >= settings.SHORTS_MAX_CONCURRENT_JOBS:
        return  # queue already full; a later tick tops it up
    # Lazy import: keeps the NAS/cutter dependency out of module import time.
    from app.shorts.nas_source import enqueue_language_jobs
    try:
        n = enqueue_language_jobs(
            folder, channel_id=ch["id"], autopilot=True,
            cut_mode=ch.get("shorts_cut_mode") or "highlights",
            camera_motion=ch.get("shorts_camera_motion") or "calm",
        )
    except ValueError:
        log.warning("Autopilot shorts: channel %s has unknown nas_folder %r",
                    ch["id"], folder)
        return
    if n:
        log.info("Autopilot shorts: enqueued %d NAS job(s) for %s (folder %s)",
                 n, ch["id"], folder)
```

Note: the test patches `app.shorts.nas_source.enqueue_language_jobs` (the lazy import resolves it there), so patching works.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_autopilot_shorts.py -v`
Expected: PASS (the 5 `_next_uncut` tests still pass; the 4 new NAS tests pass).

- [ ] **Step 5: Confirm the tick tests still pass (they mock `_run_shorts_action`)**

Run: `venv/bin/pytest tests/test_autopilot_shorts_tick.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/autopilot.py tests/test_autopilot_shorts.py
git commit -m "feat(nas): autopilot shorts action enqueues from channel nas_folder"
```

---

### Task 3: Auto-derive backfill script

**Files:**
- Create: `scripts/backfill_nas_folder.py`
- Test: `tests/test_backfill_nas_folder.py`

**Interfaces:**
- Produces: `derive_folder(name: str, folders: list[str]) -> str | None` — the single folder whose uppercase name appears in `name`, else `None` (0 or >1 matches).
- `main() -> int` — sets `nas_folder` on channels where it's NULL and `derive_folder` is unambiguous.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backfill_nas_folder.py
from scripts.backfill_nas_folder import derive_folder

FOLDERS = ["BANGLA", "HINDI", "MARATHI", "ENGLISH"]


def test_derive_unique_match():
    assert derive_folder("TMKOC Hindi Rhymes", FOLDERS) == "HINDI"


def test_derive_no_match_returns_none():
    assert derive_folder("Some Punjabi Channel", FOLDERS) is None


def test_derive_ambiguous_returns_none():
    # both HINDI and ENGLISH appear -> ambiguous
    assert derive_folder("Hindi + English Kids", FOLDERS) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_backfill_nas_folder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_nas_folder'`.

- [ ] **Step 3: Write the script**

```python
# scripts/backfill_nas_folder.py
"""One-off: set channels.nas_folder from the language word in each channel name.

Idempotent — only fills channels where nas_folder is NULL and exactly one
folder name appears in the channel name. Ambiguous / no-match channels are
printed for manual assignment via the UI dropdown.

Usage: python -m scripts.backfill_nas_folder
"""
from app.db import supabase
from app.shorts.nas_source import list_source_languages


def derive_folder(name: str, folders: list[str]) -> str | None:
    upper = (name or "").upper()
    hits = [f for f in folders if f in upper]
    return hits[0] if len(hits) == 1 else None


def main() -> int:
    folders = list_source_languages()
    chans = supabase().table("channels").select("id,name,nas_folder").execute().data or []
    for c in chans:
        if c.get("nas_folder"):
            continue
        folder = derive_folder(c.get("name") or "", folders)
        if folder:
            supabase().table("channels").update({"nas_folder": folder}).eq("id", c["id"]).execute()
            print(f"{c.get('name')} -> {folder}")
        else:
            print(f"{c.get('name')} -> (no unique match; set it in the UI)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_backfill_nas_folder.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_nas_folder.py tests/test_backfill_nas_folder.py
git commit -m "feat(nas): backfill script to derive channel nas_folder from name"
```

---

### Task 4: UI — "Shorts (NAS)" card in the Autopilot tab

**Files:**
- Modify: `app/static/channel.html` — add the card after the metadata-autopilot block in the `data-panel="autopilot"` section, plus its JS.

**Interfaces:**
- Consumes: `GET /shorts/languages` → `[{language, uncut}]`; `GET /shorts/jobs?channel_id=` → `[{status,...}]`; `PATCH /auth/channels/{id}` with `{nas_folder}` / `{autopilot_shorts_enabled}`; `POST /shorts/cut` with `{language}`; the channel object from `/auth/channels` (now includes `nas_folder`, `autopilot_shorts_enabled`).

- [ ] **Step 1: Add the card HTML** — in `app/static/channel.html`, find the autopilot settings card. Immediately **before** the `<div style="margin-top:1.1rem; display:flex; align-items:center; gap:.6rem">` that holds the `#ap-save` button, insert:

```html
      <h4 style="margin:1.1rem 0 .25rem; padding-top:1rem; border-top:1px solid #8883">Shorts (NAS)</h4>
      <p class="muted" style="margin-top:0">Cuts every video in this channel's NAS language folder into Shorts, saved back to the NAS. No upload.</p>
      <div class="row" style="gap:.6rem; align-items:center; flex-wrap:wrap">
        <label style="display:flex; flex-direction:column; gap:.2rem">
          <span class="muted" style="font-size:.8rem">Language folder</span>
          <select id="nas-folder"><option value="">— none —</option></select>
        </label>
        <span class="muted" id="nas-status" style="font-size:.85rem; align-self:flex-end; padding-bottom:.4rem"></span>
      </div>
      <label style="display:block; margin-top:.6rem"><input type="checkbox" id="nas-autocut" /> Auto-cut this folder</label>
      <div style="margin-top:.6rem; display:flex; align-items:center; gap:.6rem">
        <button class="btn" id="nas-cut-now">Cut now</button>
        <span class="muted" id="nas-cut-msg" style="font-size:.8rem"></span>
      </div>
```

- [ ] **Step 2: Add the JS** — near the other autopilot JS (after the `#ap-save` handler block), add:

```javascript
// ── Shorts (NAS) card ─────────────────────────────────────────────────
let nasLangs = [];   // [{language, uncut}] from GET /shorts/languages
function nasPopulate(c) {
  $('nas-autocut').checked = !!c.autopilot_shorts_enabled;
  const sel = $('nas-folder');
  const cur = c.nas_folder || '';
  sel.innerHTML = '<option value="">— none —</option>' +
    nasLangs.map(l => `<option value="${escapeHtml(l.language)}"${l.language === cur ? ' selected' : ''}>${escapeHtml(l.language)}</option>`).join('');
  nasRefreshStatus();
}
async function nasLoadLanguages() {
  try { nasLangs = await fetch('/shorts/languages').then(r => r.json()); }
  catch { nasLangs = []; }
}
async function nasRefreshStatus() {
  const folder = $('nas-folder').value;
  const lang = nasLangs.find(l => l.language === folder);
  let cutting = 0;
  try {
    const jobs = await fetch(`/shorts/jobs?channel_id=${encodeURIComponent(channelId)}`).then(r => r.json());
    const WORKING = ['CREATED','DOWNLOADING','ANALYSING','RENDERING','UPLOADING'];
    cutting = jobs.filter(j => WORKING.includes(j.status)).length;
  } catch {}
  $('nas-status').textContent = folder
    ? `${lang ? lang.uncut : 0} uncut · ${cutting} cutting`
    : '';
  $('nas-cut-now').disabled = !folder;
}
$('nas-folder').onchange = async () => {
  const folder = $('nas-folder').value;
  try {
    const r = await fetch(`/auth/channels/${channelId}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ nas_folder: folder }),
    });
    if (!r.ok) throw new Error(await r.text());
    toast('Folder saved.', 'ok');
    SWR.invalidate('/auth/channels');
    nasRefreshStatus();
  } catch (e) { toast('Save failed: ' + escapeHtml(String(e)), 'err'); }
};
$('nas-autocut').onchange = async () => {
  try {
    const r = await fetch(`/auth/channels/${channelId}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ autopilot_shorts_enabled: $('nas-autocut').checked }),
    });
    if (!r.ok) throw new Error(await r.text());
    toast('Auto-cut ' + ($('nas-autocut').checked ? 'on' : 'off') + '.', 'ok');
    SWR.invalidate('/auth/channels');
  } catch (e) { toast('Save failed: ' + escapeHtml(String(e)), 'err'); $('nas-autocut').checked = !$('nas-autocut').checked; }
};
$('nas-cut-now').onclick = async () => {
  const folder = $('nas-folder').value;
  if (!folder) return;
  const btn = $('nas-cut-now'); btn.disabled = true;
  $('nas-cut-msg').textContent = 'enqueuing…';
  try {
    const r = await fetch('/shorts/cut', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ language: folder }),
    });
    const out = await r.json();
    if (!r.ok) throw new Error(out.detail || 'failed');
    $('nas-cut-msg').textContent = `queued ${out.enqueued} job(s)`;
    toast(`Queued ${out.enqueued} cut job(s) for ${folder}.`, 'ok');
    nasRefreshStatus();
  } catch (e) { $('nas-cut-msg').textContent = ''; toast('Cut failed: ' + escapeHtml(String(e)), 'err'); }
  finally { btn.disabled = false; }
};
```

- [ ] **Step 3: Wire population into channel load** — find `loadChannel()` where it fills the autopilot form (the block with `$('ap-enabled').checked = ...`). Ensure the NAS languages are loaded, then populate. Add right after that block (inside the same function, where `c` is the channel object):

```javascript
  await nasLoadLanguages();
  nasPopulate(c);
```

(If `loadChannel` is not `async`, the existing autopilot form population implies it already awaits `/auth/channels`; add `await nasLoadLanguages();` before `nasPopulate(c);` — both are safe to call there.)

- [ ] **Step 4: JS syntax check**

Run:
```bash
node -e "const fs=require('fs');const h=fs.readFileSync('app/static/channel.html','utf8');const m=[...h.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x=>x[1]).join('\n;\n');new Function(m);console.log('channel.html JS OK')"
```
Expected: `channel.html JS OK`

- [ ] **Step 5: Browser check** — start the app, open a channel, go to the **Autopilot** tab. Confirm: the "Shorts (NAS)" card renders; the folder dropdown lists the 11 folders; selecting one shows `N uncut · M cutting` and enables "Cut now"; toggling Auto-cut and picking a folder each show a success toast; no console errors.

Run: `curl -s localhost:8000/shorts/languages` first to confirm the data is there, then verify visually.

- [ ] **Step 6: Commit**

```bash
git add app/static/channel.html
git commit -m "feat(nas): per-channel Shorts (NAS) card — folder, auto-cut, cut now"
```

---

## Notes for the executor

- Tasks 1–3 touch disjoint files and can run in parallel; Task 4 needs Task 1 merged (it reads `nas_folder` off `/auth/channels`).
- `$` in `channel.html` is the page's `document.getElementById` shorthand; `escapeHtml`, `toast`, `SWR`, and `channelId` already exist in that file.
- Do not remove the legacy `_next_uncut_video_for_channel` / `_shorts_made_today` in `app/autopilot.py` — they stay (unused) per the no-delete constraint.
- After all tasks: `venv/bin/pytest -q` should be green; the autopilot loop will begin enqueuing for any channel that has both `nas_folder` set and `autopilot_shorts_enabled` true.
