# Self-Improving Reflection Engine — Design Spec
**Date:** 2026-05-19  
**Status:** Approved

---

## Problem

The autopilot audits YouTube videos and applies optimised metadata, but the audit prompt is static. There is no mechanism for the system to learn whether its suggestions are actually improving view velocity, nor to adjust its approach based on what is working in the channel's niche right now. One LLM optimises video metadata with no feedback loop from the real world.

---

## Goal

Build a self-improving loop that:
1. Reads real performance outcomes (velocity lift per applied audit)
2. Samples what is winning in the channel's actual niche on YouTube right now
3. Uses that combined signal to generate an improved audit prompt candidate
4. Tests the candidate in shadow mode (suggestions only, never applied) or auto mode (live with auto-revert)
5. Promotes or discards based on measured cohort comparison
6. Separately tunes playlist similarity thresholds based on add/remove churn

---

## Architecture Overview

```
Weekly trigger
  → Check trigger conditions (win rate, regression count)
  → Competitive sample: YouTube search with niche-derived queries (200 quota units)
  → Platform guidance: Perplexity/sonar via OpenRouter
  → Reflection LLM (Sonnet): perf data + competitive + platform → candidate prompt
  → Shadow mode: run candidate on 10 recent videos, store as shadow_pending, never apply
    OR
  → Auto mode: run candidate on new incoming videos, stamp prompt_version_id, measure after 21d
  → Compare cohorts → promote or revert
  → Playlist threshold tuner: runs same tick, adjusts PLAYLIST_JOIN_HIGH based on churn rate
```

---

## Components

### 1. Niche Extraction (one-time per channel)

**Trigger:** First reflection run, or manual re-derive.  
**Input:** Top 20 most-used tags + 15 recent video titles from `videos` table.  
**Model:** `anthropic/claude-haiku-4-5-20251001` (cheap, sufficient for query synthesis).  
**Output:** 2–3 YouTube search queries stored as `audit_configs.niche_queries` (jsonb).  
**Cost:** ~$0.0001. Runs once.

Example for Marathi rhymes channel:
```json
["marathi nursery rhymes for kids", "marathi bal geet", "मराठी बालगीत"]
```

### 2. Reflection Trigger Logic

Runs weekly. **Skips if:**
- Fewer than 10 applied audits have `velocity_lift_pct` data (need ≥7 days post-apply)
- Win rate > 65% AND regression_count < 2 (working fine)
- Last reflection ran < 7 days ago

**Fires if:**
- Win rate < 50%, OR
- regression_count > 3 in last 14 days, OR
- Any single lever (title/description/tags) has negative avg velocity lift across last 10 audits

### 3. Competitive Sampling

At reflection time, use stored `niche_queries` to call YouTube search API:
```python
youtube.search().list(
    q=niche_query,
    type='video',
    publishedAfter=90_days_ago,
    order='viewCount',
    maxResults=10,
    part='snippet'
)
```
**Cost:** 100 quota units × 2 queries = 200 units per reflection.  
**Output:** Top video titles, tags, description first-lines, title length patterns, language mixing ratio.

### 4. Platform Guidance

Single call to `perplexity/sonar` via existing OpenRouter integration:
> "What are current YouTube metadata best practices for [niche] channels optimising for reach and engagement in 2025?"

**Cost:** ~$0.006 per call (tokens + $5/1000 search requests fee).

### 5. Reflection Engine

**Model:** `anthropic/claude-sonnet-4-6` via OpenRouter. New config key: `REFLECTION_MODEL`.

**Input assembled (~2,500 tokens):**
- Channel performance report: win rate, median velocity lift, regression count, best/worst lever, sample regressed audits (before/after title + velocity_lift + ai_reasoning)
- Competitive top-10 snippet data
- Platform guidance from Perplexity
- Current active prompt (full text)

**Output:**
```json
{
  "reflection": "diagnosis text",
  "changes": ["specific change 1", "specific change 2"],
  "candidate_prompt": "full new prompt text"
}
```

Stored as new row in `prompt_versions` with `status=shadow`.

### 6. Shadow Mode (default)

- Candidate prompt runs `audit_video()` on 10 most recently applied videos
- Results stored with `status=shadow_pending` — never flow into `apply_audit_internal()`
- UI shows side-by-side: current prompt suggestions vs candidate suggestions per video
- Manual "Promote" button → `POST /channels/{id}/prompt-versions/{vid}/promote`
- `reflection_mode='shadow'` in `audit_configs`

### 7. Auto Mode

Enabled by setting `audit_configs.reflection_mode = 'auto'`.

- Candidate promoted immediately to `status=live`, `audit_configs.generated_prompt` updated
- New audits stamped with `prompt_version_id`
- After 21 days (or when both cohorts have ≥10 velocity_lift data points, whichever is later):
  - Compare median `velocity_lift_pct`: old prompt cohort vs new prompt cohort
  - **Auto-revert rule:** if new cohort median < old cohort median by >10 percentage points AND new cohort has ≥10 data points → revert, mark candidate `status=retired_regression`
  - Otherwise: keep, mark old `status=retired`

### 8. Playlist Threshold Tuner

Runs weekly (same tick, independent of whether prompt reflection fires).

**Signal:** `playlist_assignments` — count embedding-adds that were later removed.
```
false_positive_rate = removed_after_embedding_add / total_embedding_adds
```

**Rules:**
- FPR > 20%: `PLAYLIST_JOIN_HIGH += 0.01`
- FPR < 5% and recent add volume low: `PLAYLIST_JOIN_HIGH -= 0.01`
- Cap: ±0.03 per cycle, absolute bounds [0.65, 0.85]

History stored in `threshold_history`. Rollback = restore previous active row.

---

## Database Changes

### New tables

**`prompt_versions`**
```sql
id bigint primary key,
channel_id text not null,
prompt_text text not null,
status text not null,  -- shadow | live | retired | retired_regression
created_at timestamptz default now(),
promoted_at timestamptz,
retired_at timestamptz,
reflection_reasoning text,
performance_snapshot jsonb,
parent_version_id bigint references prompt_versions(id)
```

**`threshold_history`**
```sql
id bigint primary key,
channel_id text not null,
join_high float not null,
join_low float not null,
leave_threshold float not null,
created_at timestamptz default now(),
status text not null,  -- active | retired
reason text
```

### Modified tables

**`audit_configs`** — new columns:
- `niche_queries jsonb`
- `reflection_mode text default 'shadow'`

**`audits`** — new column:
- `prompt_version_id bigint references prompt_versions(id)`

---

## New Files

| File | Purpose |
|---|---|
| `app/reflection.py` | Niche extraction, trigger check, competitive sampling, platform guidance, reflection LLM call, shadow runner, auto-revert check, threshold tuner |
| `supabase/migrations/YYYYMMDD_prompt_versions.sql` | `prompt_versions` + `threshold_history` tables |
| `supabase/migrations/YYYYMMDD_reflection_columns.sql` | New columns on `audit_configs` + `audits` |

## Modified Files (surgical)

| File | Change |
|---|---|
| `app/main.py` | Add weekly reflection tick to background scheduler |
| `app/autopilot.py` | Skip `shadow_pending` in apply flow; stamp `prompt_version_id` on new audits |
| `app/audits.py` | Accept optional `prompt_override` + `status_override` params in `audit_video()` |
| `app/config.py` | Add `REFLECTION_MODEL` setting |
| `app/static/channel.html` | Reflection history panel + shadow comparison view + mode toggle |

---

## Explicit Scope Boundaries

- **Not building:** competitor channel-level analytics (not in YouTube public API)
- **Not building:** Shorts-specific reflection (targets main prompt only)
- **Not building:** cross-channel learning (each channel's reflection is independent)
- **Not building:** reflection on playlist thresholds via LLM (numeric arithmetic only)

---

## Phased Build Plan

**Phase 1 — DB + config foundation**  
Migrations, config key, `audit_configs` columns, `audits.prompt_version_id`. Sanity: migrations apply cleanly, existing endpoints unaffected.

**Phase 2 — `reflection.py` core (no LLM yet)**  
Trigger logic, performance data assembly, niche extraction (Haiku call), competitive sampling (YouTube API). Sanity: trigger correctly fires/skips on mock data, niche queries look right.

**Phase 3 — Reflection LLM + Perplexity**  
Assemble full context, call Sonnet, parse output, store in `prompt_versions`. Sanity: candidate prompt is syntactically valid, stored correctly.

**Phase 4 — Shadow mode**  
Shadow audit runner, `shadow_pending` status, autopilot skip logic, `prompt_version_id` stamping. Sanity: shadow audits never reach apply, regular audits unaffected.

**Phase 5 — Auto mode + revert**  
Cohort comparison logic, auto-promote, auto-revert. Sanity: revert fires correctly on simulated regression data.

**Phase 6 — Threshold tuner**  
Churn rate arithmetic, `threshold_history` writes, config update. Sanity: thresholds adjust correctly on simulated assignment data.

**Phase 7 — UI**  
Reflection history panel, shadow comparison view, mode toggle. Sanity: renders correctly with and without reflection data.

---

## Cost Summary

| Item | Cost |
|---|---|
| Niche extraction (one-time) | ~$0.0001 |
| Competitive sampling (200 YT quota units) | Budget cost only, no $ |
| Perplexity platform guidance | ~$0.006/reflection |
| Sonnet reflection call | ~$0.007/reflection |
| Shadow audits (Haiku, 10 videos) | ~$0.04/reflection |
| **Total per reflection** | **~$0.053** |
| At 4 reflections/month | **~$0.21/month** |
