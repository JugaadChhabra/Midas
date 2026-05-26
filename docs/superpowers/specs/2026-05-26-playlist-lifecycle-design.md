# Playlist Lifecycle Management — Design Spec
**Date:** 2026-05-26
**Status:** Draft — awaiting user approval

---

## Background

Midas already has a playlist engine: `playlists.py` scores videos via cosine similarity and an LLM judge, `discover_playlists.py` clusters orphan videos into new playlists weekly, and a HITL proposals queue handles human review. The gap is **lifecycle management** — playlists are created without enforced quality standards, never audited for health, and the 2-playlist-per-run cap on discovery means the catalog is underserved.

This spec adds a **playlist lifecycle layer** grounded in YouTube's documented discovery guidelines. Every playlist — existing or newly created — passes through the same evaluation rubric. Weak ones get flagged for deletion; new ones are gated before hitting YouTube's API.

---

## Goals

1. Audit all existing playlists against YouTube discovery guidelines and flag unhealthy ones for human-approved deletion
2. Gate new playlist creation so junk playlists never reach YouTube
3. Schedule a 10-day health recheck for every newly created playlist
4. Keep LLM cost minimal: one `chat_json()` call per playlist per evaluation
5. Stay consistent with existing patterns (raw httpx, supabase-py, no ORMs, DRY_RUN compliance)

---

## Non-Goals

- Changing the video-to-playlist assignment logic (`join_pass`, `reconcile_channel`)
- Adjusting embedding thresholds or discovery clustering algorithm
- Building a dedicated playlists page — all UI lives in the existing Playlists tab

---

## Architecture Overview

```
app/playlist_rubric.py      — YouTube guidelines constants + LLM prompt template
app/playlist_health.py      — evaluation engine: score, audit, gate, recheck
supabase/migrations/        — playlist_health_checks table + playlists.created_by column
app/playlists_router.py     — 4 new endpoints (audit, health list, recheck, delete support)
app/youtube_client.py       — add yt_playlists_delete()
app/discover_playlists.py   — creation_gate() call before YouTube create
app/main.py                 — 2 new scheduler jobs
app/static/channel.html     — health panel in Playlists tab
tests/test_playlist_health.py — unit tests for rubric scoring functions
```

The rubric is the **single source of truth** for what "good" means. Initial audit, creation gate, and 10-day recheck all call the same `evaluate_playlist()` function and produce the same `HealthResult` dataclass. Nothing downstream reimplements scoring logic.

---

## Section 1 — YouTube Guidelines Rubric

### Source

Research-backed: YouTube Help Center, Backlinko 1.3M-video study, SEMrush ranking study, YouTube Creator Academy, and SEO practitioner guides (Increv, SEO Sherpa, Content Guaranteed). All criteria are defensible against at least two independent sources.

### Scoring Dimensions (0–100 total)

| # | Dimension | Weight | Pass Threshold |
|---|---|---|---|
| 1 | **Title quality**: 30–70 chars, no generic words, primary keyword in first 40 chars | 15% | All 3 met = full; any failure = 0 |
| 2 | **Description quality**: ≥150 words, keyword in first 150 chars, no stuffing (same keyword >4× per 200 words) | 20% | All 3 met = full; empty = hard gate |
| 3 | **Video count**: ≥10 optimal, 5–9 half score, <5 zero | 15% | Full at 10+; <5 = hard gate |
| 4 | **Thematic coherence**: mean pairwise cosine similarity of member embeddings ≥0.65 | 15% | ≥0.65 = full; <0.50 = 0 |
| 5 | **Freshness**: last video added <90 days ago, no deleted/dead entries | 10% | Both met = full |
| 6 | **Visibility**: Public | 10% | Public = full; Unlisted or Private = 0 (hard gate) |
| 7 | **Video order**: manually set, not just "date added" | 5% | Manual confirmed = full |
| 8 | **No policy-risk signals** | 10% | Clean = full; any flag = 0 |

**Score bands:**
- 80–100 → `healthy` (keep)
- 60–79 → `needs_work` (flag with specific recommendations)
- 0–59 → `critical` (propose deletion)

### Hard Gates (fail regardless of total score)

- Empty or missing description
- Fewer than 5 member videos
- Visibility is Unlisted or Private
- Title contains only generic words (no topical keyword)

### Auto-Flagged Title Words

```python
GENERIC_TITLE_WORDS = {
    "videos", "uploads", "my videos", "misc", "miscellaneous",
    "stuff", "content", "new", "playlist", "various", "awesome",
    "random", "latest", "best", "top"
}
```

A title that consists entirely of these words (case-insensitive, after stripping the channel name) fails the title dimension entirely.

### LLM Usage

One `chat_json()` call per playlist, using `anthropic/claude-haiku-4.5`. Called only after all hard-gate and pure-Python checks pass (to avoid wasting tokens on obvious failures). The prompt evaluates:
- Whether the title is specific enough to rank for a keyword (not just technically valid)
- Whether the description communicates a clear viewer value proposition
- Whether the member video titles are thematically coherent with the playlist title

**Estimated cost:** ~$0.0002 per playlist. Auditing a 50-playlist channel costs under $0.01.

---

## Section 2 — `playlist_rubric.py`

Constants-only file. Zero business logic. Imported by `playlist_health.py` and the LLM prompt builder.

```python
# Thresholds
TITLE_MIN_CHARS = 30
TITLE_MAX_CHARS = 70
TITLE_KEYWORD_POSITION = 40   # primary keyword should appear within first N chars
DESC_MIN_WORDS = 150
DESC_KEYWORD_ABOVE_FOLD = 150  # chars
MEMBER_HARD_MIN = 5
MEMBER_OPTIMAL = 10
COHERENCE_THRESHOLD = 0.65
COHERENCE_HARD_FAIL = 0.50
FRESHNESS_STALE_DAYS = 90
SCORE_HEALTHY = 80
SCORE_NEEDS_WORK = 60

# Generic title words (lowercase)
GENERIC_TITLE_WORDS = {...}

# Dimension weights (must sum to 1.0)
WEIGHTS = {
    "title": 0.15,
    "description": 0.20,
    "members": 0.15,
    "coherence": 0.15,
    "freshness": 0.10,
    "visibility": 0.10,
    "order": 0.05,
    "policy": 0.10,
}

# LLM prompt template (str with {playlist_title}, {description}, {member_titles} slots)
HEALTH_PROMPT = """..."""
```

---

## Section 3 — `playlist_health.py`

### `HealthResult` dataclass

```python
@dataclass
class HealthResult:
    playlist_id: str
    score: float               # 0–100
    passed: bool               # score >= SCORE_NEEDS_WORK and no hard gate failures
    band: str                  # 'healthy' | 'needs_work' | 'critical'
    dimension_scores: dict     # {'title': 15.0, 'description': 0.0, ...}
    fail_reasons: list[str]    # human-readable list of specific failures
    recommendation: str        # 'keep' | 'delete' | 'needs_description' | 'needs_members'
    llm_summary: str           # one-sentence plain-English health summary
    checked_at: datetime
```

### Public functions

```python
def evaluate_playlist(playlist_id: str) -> HealthResult
    """Score a single playlist. Calls LLM only if hard gates pass."""

def audit_channel_playlists(channel_id: str) -> list[HealthResult]
    """Evaluate all playlists for a channel. Returns results sorted by score asc."""

def creation_gate(proposed: dict, cluster_video_ids: list[str]) -> tuple[bool, HealthResult]
    """Gate called from discover_playlists() before YouTube API create.
    proposed = {'title': str, 'description': str}
    Returns (passes, result). If description too short, retries LLM once with
    explicit length instruction before failing."""

def recheck_playlist(playlist_id: str) -> HealthResult
    """Same as evaluate_playlist() but also checks whether ≥1 video was added
    in the first 10 days (freshness signal specific to new playlists)."""
```

### Internal helpers

```python
def _score_title(title: str) -> tuple[float, list[str]]
def _score_description(description: str) -> tuple[float, list[str]]
def _score_members(video_ids: list[str], last_added_at: datetime | None) -> tuple[float, list[str]]
def _score_coherence(video_ids: list[str]) -> tuple[float, list[str]]
    # Reuses _cosine_sim and _parse_embedding from playlists.py — no code duplication
def _score_visibility(playlist_id: str) -> tuple[float, list[str]]
def _llm_evaluate(playlist: dict, member_titles: list[str]) -> dict
    # Returns {'title_specific': bool, 'desc_value_prop': bool, 'thematic_ok': bool, 'summary': str}
```

All internal helpers are pure functions (inputs → outputs, no side effects). `evaluate_playlist()` orchestrates them and writes the result to `playlist_health_checks`.

---

## Section 4 — Database Schema

### New migration file

`supabase/migrations/20260526000000_playlist_health.sql`

```sql
-- Health check history + recheck scheduling
CREATE TABLE IF NOT EXISTS playlist_health_checks (
    id              BIGSERIAL PRIMARY KEY,
    playlist_id     TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    score           FLOAT NOT NULL,
    passed          BOOLEAN NOT NULL,
    band            TEXT NOT NULL,        -- 'healthy' | 'needs_work' | 'critical'
    recommendation  TEXT NOT NULL,        -- 'keep' | 'delete' | 'needs_description' | 'needs_members'
    fail_reasons    JSONB DEFAULT '[]',
    llm_summary     TEXT,
    check_type      TEXT NOT NULL,        -- 'initial_audit' | 'creation_gate' | 'scheduled_recheck'
    checked_at      TIMESTAMPTZ DEFAULT NOW(),
    recheck_due_at  TIMESTAMPTZ           -- only set for discovery-created playlists; checked_at + 10d
);

CREATE INDEX ON playlist_health_checks(playlist_id);
CREATE INDEX ON playlist_health_checks(recheck_due_at)
    WHERE recheck_due_at IS NOT NULL;

-- Track creation source for scheduler (only discovery-created playlists get rechecks)
ALTER TABLE playlists
    ADD COLUMN IF NOT EXISTS created_by TEXT DEFAULT 'sync';
-- 'sync' | 'discovery'
```

### `playlist_proposals` — no schema change required

The existing table accepts any `action` string. Adding `delete` as an action reuses the table and the existing approve/reject UI with zero migration. The approve path in `playlists_router.py` just needs a `delete` branch that calls `yt_playlists_delete()`.

---

## Section 5 — Enhanced `discover_playlists.py`

### Current flow
```
cluster → _propose_playlist() → yt_playlists_insert() → record assignment
```

### New flow
```
cluster → _propose_playlist() → creation_gate()
  → FAIL:  log skip reason, increment skipped counter, continue to next cluster
  → PASS:  yt_playlists_insert() → record with created_by='discovery'
           → write health_check row with recheck_due_at = now + 10 days
```

### Description retry

If `creation_gate()` fails solely because the description is too short (≤150 words), `discover_playlists` calls `_propose_playlist()` a second time with an explicit instruction: `"Write a description of at least 200 words..."`. If the retry still fails, the cluster is skipped. Maximum one retry per cluster.

### Return value change

```python
# Before
{"clusters_found": int, "playlists_created": int}

# After
{"clusters_found": int, "playlists_created": int, "clusters_skipped_gate": int}
```

---

## Section 6 — Scheduler Jobs

Both jobs added in `main.py` alongside the existing `playlist_reconcile` and `playlist_discovery` jobs.

### Job 1 — Initial audit (fires once)

```python
scheduler.add_job(
    run_initial_playlist_audit,
    'date',
    run_date=datetime.now() + timedelta(seconds=60),
    id='playlist_initial_audit',
)
```

`run_initial_playlist_audit()` in `main.py`:
1. Checks a new `channels.playlist_audit_done` boolean column — if True for all channels, exits immediately (idempotent across restarts)
2. For each channel: calls `audit_channel_playlists(channel_id)`
3. For results with `recommendation == 'delete'`: calls `_queue_proposal(video_id=None, playlist_id, action='delete', ...)`
4. Marks `channels.playlist_audit_done = True` per channel

New column: `ALTER TABLE channels ADD COLUMN IF NOT EXISTS playlist_audit_done BOOLEAN DEFAULT FALSE;`

### Job 2 — Daily recheck

```python
scheduler.add_job(
    run_scheduled_rechecks,
    'interval',
    hours=24,
    id='playlist_recheck',
)
```

`run_scheduled_rechecks()` in `main.py`:
1. Queries `playlist_health_checks` for rows where `recheck_due_at <= NOW()` and no newer check exists for that playlist
2. For each due playlist: calls `recheck_playlist(playlist_id)`
3. If result `recommendation == 'delete'`: queues a delete proposal
4. Clears `recheck_due_at` (sets to NULL) after check completes

---

## Section 7 — API Endpoints

All added to `playlists_router.py`.

```
POST /channels/{channel_id}/playlists/audit
    → Triggers audit_channel_playlists(), queues delete proposals for critical playlists
    → Returns: {"audited": int, "healthy": int, "needs_work": int, "critical": int, "proposals_queued": int}

GET  /channels/{channel_id}/playlists/health
    → Returns latest health check per playlist, sorted by score asc
    → Returns: list of {playlist_id, title, score, band, recommendation, fail_reasons, checked_at}

POST /channels/{channel_id}/playlists/{playlist_id}/recheck
    → Triggers recheck_playlist() for a single playlist
    → Returns: HealthResult as JSON

POST /channels/{channel_id}/playlists/proposals/decide
    → Existing endpoint — gains delete execution branch:
      if action == 'delete': yt_playlists_delete(yt, playlist_id) → delete playlists row
```

### `yt_playlists_delete()` in `youtube_client.py`

```python
def yt_playlists_delete(yt, channel_id: str, playlist_id: str) -> None:
    """Delete a YouTube playlist. DRY_RUN aware."""
    if settings.DRY_RUN:
        log.info("[DRY_RUN] would delete playlist %s", playlist_id)
        return
    yt.playlists().delete(id=playlist_id).execute()
    quota.charge(channel_id, 50)  # playlists.delete costs 50 units
```

---

## Section 8 — Frontend

All changes in `app/static/channel.html` within the existing Playlists tab. No new pages.

### Health panel (below existing KPIs)

```
┌─────────────────────────────────────────────────────────────┐
│  Playlist Health                        [Run Audit]          │
│─────────────────────────────────────────────────────────────│
│  Title                    Score   Band        Last Checked   │
│  Python Tutorial Series   88      ● Healthy   2026-05-26    │
│  Random Videos             31      ● Critical  2026-05-26   [Flag for deletion]
│  Cooking Basics            67      ● Needs Work 2026-05-26  │
│─────────────────────────────────────────────────────────────│
│  Fail reasons shown inline on row expand (click to expand)  │
└─────────────────────────────────────────────────────────────┘
```

- Score badge: green (≥80), amber (60–79), red (<60)
- "Run Audit" button calls `POST /channels/{id}/playlists/audit`
- "Flag for deletion" button creates a `delete` proposal (calls existing decide endpoint)
- Existing proposals table already renders — delete proposals get a red "Delete" button instead of add/remove
- Playlist health rows are expandable (click row) to show `fail_reasons` list

---

## Section 9 — Subagent Execution Plan

### Phase 1 — Parallel (3 independent agents)

| Agent | Files touched | Dependency |
|---|---|---|
| **DB agent** | `supabase/migrations/20260526000000_playlist_health.sql` | None |
| **Core engine agent** | `app/playlist_rubric.py`, `app/playlist_health.py`, `tests/test_playlist_health.py` | None |
| **YouTube client agent** | `app/youtube_client.py` (add `yt_playlists_delete`) | None |

### Phase 2 — Sequential (depends on Phase 1)

| Step | Agent | Files touched |
|---|---|---|
| 4 | **Integration agent** | `app/playlist_discovery.py` (creation gate), `app/main.py` (schedulers + runner fns), `app/playlists_router.py` (4 new endpoints) |
| 5 | **Frontend agent** | `app/static/channel.html` (health panel) |

### Phase 3 — Quality gates

| Step | Agent | Action |
|---|---|---|
| 6 | **Code review agent** | Reviews all changed files for: DRY_RUN compliance, token efficiency, existing pattern consistency, error handling, no new dependencies |
| 7 | **Test runner agent** | Runs `pytest tests/` and reports failures |

### Quality checklist applied at review

- [ ] Every YouTube write wrapped in `if settings.DRY_RUN: log...; return`
- [ ] No new pip dependencies introduced
- [ ] All `supabase()` calls follow existing `.table().select().execute()` pattern
- [ ] LLM called at most once per playlist per evaluation
- [ ] `creation_gate()` called before every `yt_playlists_insert` in `discover_playlists`
- [ ] All new scheduler jobs have unique `id=` strings
- [ ] `yt_playlists_delete()` charges 50 quota units
- [ ] New DB columns have `IF NOT EXISTS` guards
- [ ] No inline comments that describe what the code does (only non-obvious why)

---

## Section 10 — Testing Strategy

### Unit tests (`tests/test_playlist_health.py`)

- `test_score_title_generic_words()` — title "Videos" scores 0 on title dimension
- `test_score_title_valid()` — well-formed title scores full 15 points
- `test_score_description_empty()` — empty description is hard gate failure
- `test_score_description_short()` — 50-word description fails threshold
- `test_score_members_below_minimum()` — 3 members → hard gate
- `test_score_members_optimal()` — 10+ members → full score
- `test_creation_gate_rejects_bad_proposal()` — proposed playlist with generic title fails gate
- `test_creation_gate_passes_good_proposal()` — valid proposal passes with mocked LLM response
- `test_health_result_band()` — score 85 → 'healthy', 65 → 'needs_work', 45 → 'critical'

All LLM calls mocked via `unittest.mock.patch('app.playlist_health.chat_json')`.

### Integration smoke test (manual, post-deploy)

1. Connect a test channel with known playlists
2. Call `POST /channels/{id}/playlists/audit`
3. Verify `playlist_health_checks` rows created for every playlist
4. Verify at least one delete proposal queued for any playlist scoring <60
5. Approve a delete proposal with `DRY_RUN=true` — verify log line, no YouTube API call
6. Flip `DRY_RUN=false`, re-approve — verify YouTube playlist deletion succeeds

---

## Open Questions

1. **Unlisted playlists from sync**: Currently `playlists_sync.py` does not fetch visibility status from YouTube. The `playlists()` response includes `status.privacyStatus` — do we want to backfill this in the sync, or treat unlisted as unknown (skip visibility dimension) for existing playlists?

2. **Video order detection**: YouTube doesn't expose playlist ordering mode via the API cleanly. Proxy: if `playlist_assignments.decided_at` timestamps are all within a narrow window (all added at once via sync), order is likely "date added." Manually curated playlists will have staggered timestamps. Is this heuristic acceptable, or skip the order dimension entirely?

3. **Delete proposal execution**: When a delete proposal is approved, we delete the playlist row from Supabase. Any `playlist_assignments` rows cascade-delete per the FK constraint. This is correct behavior — confirm?

4. **Initial audit frequency**: The audit fires once on startup (idempotent via `playlist_audit_done` flag). Should there be a way to re-run it (e.g., after a bulk sync of new playlists), or is the manual `POST /channels/{id}/playlists/audit` endpoint sufficient?
