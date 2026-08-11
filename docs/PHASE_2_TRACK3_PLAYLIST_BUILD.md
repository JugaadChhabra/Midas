# Phase 2 / Track 3 — Playlist Optimizer Phase 2 (Competitor research + Construction + Self-eval) — Implementation Checklist

**Status:** DRAFT — to be reviewed before any implementation work begins.
**Spec sources of record:** `docs/plan.md` §Phase 2 (2A/2B/2C), `docs/PLAYLIST_OPTIMIZATION.md`
(§Competitor research, §Construction, §Control loop, §Config, §Endpoints), and the shipped
Phase 1B substrate (`docs/PHASE_1B_PLAN.md`).
**Substrate already shipped (Phase 0 + 1B):** `analytics_client.py`, `metrics_poll.py`,
`playlist_metrics` + `playlists` (with `role`/`origin`/`strategy_version`/`created_by_optimizer_at`
reserved), `playlist_health.py` (recommend-only scoring), the quota tracker (`app/quota.py`),
the embeddings recall stack (`video_embeddings`, `playlist_video_sims`/`discover_orphan_clusters`
RPCs), and the Phase 1A measurement analog (`app/measurement.py`).

> This is an **executable implementation checklist**, modelled on `PHASE_1B_PLAN.md`: numbered
> IMPLEMENT → REVIEW steps grouped in tracks, every seam cited by `file:line`, spec quotes for
> grounding, and an appendix discipline checklist to carry into every PR. It proposes and
> justifies; it is not itself the migration SQL.

---

## 0. Overview

Track 3 is Phase 2 of the Playlist Optimizer — the biggest surface in the whole roadmap
(~14–18 days). It turns the recommend-only inventory shipped in 1B into a subsystem that
**acts**: it researches what bigger channels in the niche appear to do, constructs playlists
with an LLM re-rank for session continuation, and grades every construction after a window.

Three sub-phases, in dependency order:

| Sub-track | Name | Rough effort | Depends on |
|---|---|---|---|
| **2A** | Competitor research (autonomous scheduled pipeline → per-niche inferred reference) | ~4–5 days | Phase 1B (`playlists` inventory), quota tracker, `reflection.derive_niche_queries` |
| **2B** | Construction + intervention lifecycle (candidate-gen → LLM re-rank → order → metadata, stamping `playlist_interventions`) | ~7–9 days | 2A (competitor reference conditions construction), Phase 1B embeddings recall stack |
| **2C** | Playlist self-eval — the keystone (`measurement_eval` analog for `playlist_interventions`) | ~3–4 days | **2B** (needs `playlist_interventions` rows stamped on apply) |

**Hard dependency:** 2C cannot start until 2B is landing interventions with
`measurement_status='awaiting_window'` — 2C has nothing to grade otherwise. 2A and 2B can
overlap in time (2A is a scheduled background pipeline; 2B is the interactive/cron build path),
but 2B's construction pipeline reads 2A's `playlist_competitor_reference_json` as a conditioning
input, so 2A's storage column should land first.

### The three cross-cutting spec constraints (PO §"three learning conditions", lines 41–55)

Every step below is designed to satisfy these; if a change would violate one, it is wrong.

1. **Honest measurement.** Playlist actions are judged on real Analytics session metrics
   (`playlistStarts`, `averageTimeInPlaylist`, `viewsPerPlaylistStart`) — never vanity counts.
   This is 2C's whole job.
2. **Closed loop.** Outcomes feed back into behaviour (later, the playbook in Phase 3B), not
   just a dashboard. 2C writes the outcome state that Phase 3 will distil.
3. **Preserved exploration.** Construction logic is a *strategy* (Phase 4, Loop 3) —
   2B stamps `strategy_version` so a later challenger can encode divergence. 2B/2C do not
   implement champion/challenger, but must not foreclose it.

### The single most important reconciliation (read before touching 2B)

A **pre-existing similarity allocator is on live crons** (`app/playlists.py`,
`app/playlist_discovery.py`). PO §Decisions #2 (line 362) demotes it:

> **Similarity is recall, session continuation is the objective.** The existing recommender is
> demoted to candidate generation; re-ranking and ordering carry the work.

2B **demotes, does not delete** this allocator. The recall primitives are reused as the new
pipeline's candidate-generation stage; the legacy *creation* path is gated off per-channel when
the optimizer owns the channel. Details in §2B.2.

---

# PHASE 2A — Competitor research (~4–5 days)

**Goal (PO §Competitor research, lines 124–168; plan.md §2A, lines 113–119):** an autonomous,
**scheduled, bounded** pipeline that, per niche, produces an **inferred** competitor reference
from public signals — characterize niche → discover competitors by who ranks → LLM fit/language
filter → harvest public structure → distill → `channels.playlist_competitor_reference_json`.

Spec quote (PO line 126):

> Zero human input. A **bounded, scheduled pipeline** (not an open-ended agent loop):
> deterministic, debuggable, quota-safe, and it reliably runs itself without supervision.

### Non-goals for 2A

- **No measurement of competitors.** Their session metrics are owner-only and unreadable
  (PO line 166). The reference is **structural inference**, stored distinct from any measured
  playbook. It is a *hypothesis generator*, validated only by 2C.
- **No scraping / unofficial endpoints** (PO line 163). Official Data API over public data only.
- **No riding the per-video autopilot tick.** Discovery is its own scheduled job under its own
  sub-budget (PO line 160).
- Does not build or modify playlists (that's 2B).

## 2A.1 Existing-state audit

| Seam | Location | State for 2A |
|---|---|---|
| `search.list` wrapper | `yt_search_videos` — `app/youtube_client.py:279` | WIRED. `part=snippet`, `q`, `type=video`, `order=viewCount` (`:287-296`), quota **100** logged in `finally` (`:312`). **BUG for 2A:** returns only `video_id/title/description/tags` (`:301-306`) — **no `channelId`**. One-line fix needed. |
| Existing search consumer | `reflection._sample_competitors` — `app/reflection.py:233` | Loops `niche_queries[:2]` (`:246`), calls `yt_search_videos`. This is *sampling-for-prompt*, not a structured harvest — 2A mirrors the call site, not the function. |
| `channels.list` (single) | `yt_channels_list_uploads` — `app/youtube_client.py:72` | `part=contentDetails,snippet`, single `id`. **No batched stats variant** — 2A needs a new `yt_channels_list_stats` (`part=statistics,snippet`, comma-joined up-to-50 ids). |
| `playlists.list` (any channel) | `yt_playlists_list` — `app/youtube_client.py:186` | Paginated, `part=snippet,contentDetails`, keyed by `channelId` — works for any public channel. Reusable as-is for harvest. |
| `playlistItems.list` | `yt_playlist_items_page` — `app/youtube_client.py:93` | `part=contentDetails`, one page, cost 1. Reusable for harvest. |
| Quota tracker | `app/quota.py` | `units_used_today()` (`:17`) filters `.gt("units", 0)` on `occurred_at` to dodge the 1000-row cap — **replicate this filter**. `units_remaining()` (`:34`), `can_afford()` (`:38`). **No per-operation budget helper today.** |
| Niche characterization | `reflection.derive_niche_queries` (`app/reflection.py:172`) caches to `audit_configs.niche_queries`; `get_or_derive_niche_queries` (`:217`) is the cached accessor. | Half-exists — extend to emit a richer niche descriptor. |
| LLM JSON | `chat_json` — `app/openrouter.py:31` | `response_format=json_object`, default `AUDIT_MODEL`; pass `model="anthropic/claude-haiku-4.5"` for cheap classification (same idiom as `derive_niche_queries` at `reflection.py:205`). |
| Channels-column idiom | `supabase/migrations/20260618115221_phase1b_playlist_inventory.sql:42` | `alter table channels add column if not exists ...` — mirror for the two new columns. |
| Scheduler | `app/main.py` lifespan (`:176`–`:314`); per-channel fan-out `_run_per_channel` (`:75`); cache-check idiom in `get_or_derive_niche_queries` (`reflection.py:217`). | `COMPETITOR_REFRESH_DAYS=90` is **not a cron interval** — run the job daily/weekly and skip channels whose `playlist_competitor_built_at` is inside the window. |

## 2A.2 Steps

### Step 2A.1 — Add `channelId` to `yt_search_videos` (IMPLEMENT → REVIEW)

**IMPLEMENT.** In `app/youtube_client.py:301-306`, add `"channel_id": (item.get("snippet") or {}).get("channelId", "")`
to the per-result dict. This is the load-bearing one-line fix: the channels winning your niche
queries *are* the competitive set (PO line 136 — "collect the channel IDs behind top-ranking
videos"). No quota change, no signature change; `_sample_competitors` ignores the new key so it
is safe.
**REVIEW.** Existing `reflection._sample_competitors` still works unchanged. A search returns
non-empty `channel_id` values on a live probe. *Effort: ~0.25 day.*

### Step 2A.2 — Add `yt_channels_list_stats` batched helper (IMPLEMENT → REVIEW)

**IMPLEMENT.** New helper in `app/youtube_client.py` mirroring `yt_channels_list_uploads:72`
and the `videos.list` batch idiom (`yt_videos_list_stats:126`): `part="statistics,snippet"`,
`id=",".join(ids[:50])`, cost **1** per call, `_log_quota(channel_id, "channels.list", 1, success)`
in `finally`, `_guard_token` in `except`. Returns subscriber/view counts + snippet per channel
so the discovery job can filter on `COMPETITOR_MIN_SUBSCRIBER_MULTIPLE` (PO line 137).
**REVIEW.** Live probe: batch of ≤50 known channel ids returns `statistics.subscriberCount`;
`quota_log` shows one `channels.list` row per call at units=1. *Effort: ~0.5 day.*

### Step 2A.3 — Per-operation quota budget helper (IMPLEMENT → REVIEW)

**IMPLEMENT.** In `app/quota.py`, add `units_used_today_for(operation: str) -> int`: same query
as `units_used_today()` (`:17`) — **keep the `.gt("units", 0)` filter and the `occurred_at`
day-start bound** — plus `.eq("operation", operation)`. The discovery job self-limits at
`COMPETITOR_DISCOVERY_QUOTA_BUDGET` against `units_used_today_for("search.list")` **AND** gates
each `search.list` on the global `can_afford(100)` (`:38`) so it never starves audit/apply quota.
**REVIEW.** Unit-level: with a seeded `quota_log`, the helper returns the sum of `search.list`
units only, ignoring units=0 telemetry rows. *Effort: ~0.5 day.*

### Step 2A.4 — Migration: competitor-reference columns (IMPLEMENT → REVIEW)

**IMPLEMENT.** One idempotent migration mirroring `20260618115221:42`:

```sql
alter table channels add column if not exists playlist_competitor_reference_json jsonb;
alter table channels add column if not exists playlist_competitor_built_at        timestamptz;
```

(PO §Competitor research storage, lines 149–153.) Nullable, no backfill.
**REVIEW.** Applies cleanly to a prod clone; existing channel rows have both columns NULL.
*Effort: ~0.25 day.*

### Step 2A.5 — Niche descriptor extension (IMPLEMENT → REVIEW)

**IMPLEMENT.** Extend `reflection.derive_niche_queries` (`:172`) / `get_or_derive_niche_queries`
(`:217`) to also emit a richer **niche descriptor** (topic summary + defining queries) and thread
the channel's `default_language` (from `yt_channels_list_uploads:84`) through it. Cache alongside
`niche_queries` in `audit_configs` (or a sibling column). PO stage 1 (line 131): "Characterize the
niche … in the channel's `default_language`."
**REVIEW.** Descriptor is language-tagged and stable across runs (cached, not re-derived each tick).
*Effort: ~0.75 day.*

### Step 2A.6 — `app/competitor_research.py` pipeline (IMPLEMENT → REVIEW)

**IMPLEMENT.** New file with a single `build_competitor_reference(channel_id)` entry, executing the
five PO stages (lines 129–146) as a bounded, deterministic sequence:

1. **Characterize** — `get_or_derive_niche_queries` + descriptor (Step 2A.5).
2. **Discover by who-ranks** — run each niche query through `yt_search_videos` (now with
   `channel_id`), collect distinct competitor channel ids behind top-ranking videos.
   **Every `search.list` gated on `can_afford(100)` and the per-op budget (Step 2A.3).**
3. **Filter** — batch `yt_channels_list_stats` (Step 2A.2); keep channels
   `>= COMPETITOR_MIN_SUBSCRIBER_MULTIPLE` of the target and recently active.
4. **Fit/language QC** — `chat_json(..., model="anthropic/claude-haiku-4.5")` verifies each
   candidate is in-niche and language-matched; drops reuploaders/tangential/wrong-language
   (PO stage 3, line 141).
5. **Harvest** — for kept channels, `yt_playlists_list` (`:186`) + `yt_playlist_items_page`
   (`:93`) capture themes, naming, role mix, length, sequencing, member view counts (cost 1 each).
6. **Distill** — `chat_json` into the per-niche reference; write
   `playlist_competitor_reference_json` + `playlist_competitor_built_at=now`.

**Config (`config.py`), PO §Config table (lines 321–331):** `COMPETITOR_REFRESH_DAYS=90`,
`COMPETITOR_DISCOVERY_QUOTA_BUDGET=2000`, `COMPETITOR_MIN_SUBSCRIBER_MULTIPLE=3`.
**REVIEW.** Dry run on the 1B pilot channel: reference JSON is populated, distinct from any
measured data, and the run's total `search.list` units stay under the sub-budget. No scraping
anywhere in the module. *Effort: ~1.5 days.*

### Step 2A.7 — Scheduler wiring (IMPLEMENT → REVIEW)

**IMPLEMENT.** Add a cron in `app/main.py` lifespan (`:176`), running daily/weekly via
`_run_per_channel` (`:75`); **skip channels whose `playlist_competitor_built_at` is within
`COMPETITOR_REFRESH_DAYS`** (mirror the cache-check in `get_or_derive_niche_queries:217`).
`COMPETITOR_REFRESH_DAYS=90` cannot be a cron interval, so the skip-if-fresh guard is the cadence.
UTC-pinned like `metrics_poll` (`main.py:239`).
**REVIEW.** Manual trigger builds the reference; a second immediate trigger skips (within window);
per-channel exceptions isolated (fan-out pattern). *Effort: ~0.5 day.*

### Step 2A.8 — Endpoints (IMPLEMENT → REVIEW)

**IMPLEMENT.** On `app/playlists_router.py` (PO §Endpoints, lines 352):
`GET /channels/{id}/playlist-competitor-reference` (cached read of the column) and
`POST /channels/{id}/playlists/competitor-reference/rebuild` (force `build_competitor_reference`).
**REVIEW.** `curl` returns the stored reference; rebuild forces a fresh build and stamps
`playlist_competitor_built_at`. *Effort: ~0.5 day.*

---

# PHASE 2B — Construction + intervention lifecycle (~7–9 days)

**Goal (PO §Construction, lines 173–197; §Control loop, lines 200–266; plan.md §2B, lines
121–127):** a construction pipeline — candidate generation (recall) → LLM re-rank for session
continuation → ordering/entry-point → optimized metadata — where **every** create/add/reorder/
rename is stamped as a row in a new `playlist_interventions` table with a pre-change baseline,
behind a per-channel `PLAYLIST_OPTIMIZER_ENABLED` gate, one channel first.

Spec quote (PO §Construction pipeline, lines 183–194):

> 1. **Candidate generation** — embeddings/similarity (existing system) for recall …
> 2. **Re-rank by session objective** … LLM does the editorial judgment embeddings can't:
>    *next* video vs merely *similar* video.
> 3. **Order + entry point** — strong opener, smooth handoffs, no retention cliffs …
> 4. **Playlist metadata** — generate optimized title + description … under the `default_language` rule.

### Non-goals for 2B

- **No deletion.** `delete` stays recommend-only, human-confirmed; `PLAYLIST_AUTO_DELETE=false`
  (PO lines 257–259). Deletion execution is a 2C endpoint gate, not a 2B write.
- **No self-eval.** 2B stamps interventions and sets `measurement_status='awaiting_window'`;
  the grading job is 2C.
- **No champion/challenger.** 2B stamps `strategy_version` but does not route or promote (Phase 4).
- **No deletion of the legacy allocator** — it is demoted, not removed (§2B.2).

## 2B.1 Existing-state audit — the allocator to demote

| Seam | Location | State for 2B |
|---|---|---|
| `join_pass` (per-video) | `app/playlists.py:301` | DRY_RUN gate early (`:306-308`). HITL → `_queue_proposal` (`:258`) writes `playlist_proposals`; else direct YouTube writes. |
| `reconcile_channel` (daily) | `app/playlists.py:370` | DRY_RUN gate (`:379-381`). Wired into `_daily_reconcile` cron (`main.py:92`, job registered `main.py:194`, 02:00 server-local). |
| `discover_playlists` (weekly) | `app/playlist_discovery.py:156` | DRY_RUN gate (`:161-163`). Clusters orphans, **creates** playlists via `yt_playlists_insert` (`:203`). Constants `MIN_CLUSTER_SIZE=4`, `MAX_NEW_PLAYLISTS=2` (`:17-18`). Wired weekly (`main.py:123`, job `main.py:203`, Sun 03:00). |
| Recall primitives (reuse) | `app/playlists.py`: `_centroid` (`:72`), `_cosine_sim` (`:95`), `_sims_for_video` (`:138`), `_sims_matrix` (`:170`), `_parse_embedding` (`~:50`); `app/playlist_discovery.py`: `_cluster_orphans_for_channel` (`:118`) — already imports several from `playlists.py` (`:12`). | Reuse as candidate-gen **stage 1**. |
| Embeddings / recall RPCs | `video_embeddings` (`20260518000000_playlists.sql:5`, `vector(3072)`, `EMBED_MODEL=google/gemini-embedding-2-preview`). `playlist_video_sims` (`20260727120000`, called `playlists.py:130`) + `discover_orphan_clusters` (called `playlist_discovery.py:89`). Both **OFF by default** (`PLAYLIST_SIMS_USE_RPC`/`PLAYLIST_DISCOVERY_USE_RPC`, `config.py:106`/`:112`) with in-app fallback + live parity test. | Reuse; no change. |
| YouTube write helpers | `yt_playlists_insert` (`youtube_client.py:224`, cost 50), `yt_playlist_items_insert` (`:244`, 50), `yt_playlist_items_delete` (`:266`, 50). Each `_log_quota` in `finally`. | **MISSING:** `playlists.update` (rename) + `playlistItems.update` (reorder via `snippet.position`) — new helpers, cost 50 each. |
| DRY_RUN gating | Lives in **callers** (`playlists.py:306`, `:379`; `playlist_discovery.py:161`), NOT in `youtube_client`. | New pipeline needs its own `if settings.DRY_RUN: return` guard. |
| Write-time quota | No `can_afford` gate on writes today; autopilot uses soft `_yt_quota_exhausted_until` (`autopilot.py:30-31`, set at `:436` reacting to a 403 `quotaExceeded`). | New pipeline rides that soft cutoff **or** checks `can_afford(50 * n)` before a write batch. |
| Reserved columns | `playlists.role/origin/strategy_version/created_by_optimizer_at` already exist (`20260618115221:24-29`), reserved for 2B. | Optimizer path stamps `origin='optimizer_created'`, `created_by_optimizer_at=now`. |
| Two human-gate tables | Legacy `playlist_proposals` (membership add/remove) vs. new `playlist_interventions` (construction lifecycle). | **Keep distinct** — do not route builds through proposals. |

## 2B.2 The demotion (do this deliberately, PO Decision #2, line 362)

The legacy allocator stays live for channels the optimizer does not own; it is **demoted to
candidate generation** for channels it does.

- **Gate creation behind the per-channel `playlist_optimizer_enabled` flag.** In
  `discover_playlists` (`playlist_discovery.py:156`), early-return when the optimizer owns the
  channel — mirror the `playlist_health_enabled` filter idiom at `main.py:148-154`. The new
  pipeline then owns creation; the legacy weekly discovery persists for disabled channels.
- **Reuse, don't fork, the recall math.** Candidate-gen stage 1 calls the existing
  `_centroid`/`_cosine_sim`/`_sims_matrix`/`_cluster_orphans_for_channel` primitives. Cosine is
  **recall only** (PO Decision #2 / line 30); the LLM re-rank carries the session-continuation
  objective.
- **Do not touch `join_pass`/`reconcile_channel`'s membership behaviour** beyond the per-channel
  gate — those manage *membership within existing playlists*, a separate concern from
  *construction*.

## 2B.3 Steps

### Step 2B.1 — Migration: `playlist_interventions` + optimizer flag (IMPLEMENT → REVIEW)

**IMPLEMENT.** One idempotent migration. Create `playlist_interventions` (full schema
PO lines 220–235): `id bigserial pk`, `channel_id text not null references channels(id)`,
`playlist_id text` (null until a create succeeds), `action text not null`
(`create|add_video|reorder|rename|prune_recommend|delete`), `payload jsonb`, `before_state jsonb`,
`strategy_version text`, `status text default 'pending'` (`pending|applied|awaiting_confirm|failed`),
`measurement_status text default 'not_applicable'`
(`not_applicable|awaiting_window|measuring|win|neutral|regression`), `measurement_started_at
timestamptz`, `measurement_result jsonb`, `outcome_decision text default 'none'`
(`none|kept|revised|pruned`), `created_at timestamptz default now()`.

Add a **partial index on the two in-flight measurement states** — mirror
`audits_measurement_inflight_idx` (`20260702183233:50-52`):

```sql
create index if not exists playlist_interventions_measurement_inflight_idx
    on playlist_interventions(measurement_status)
    where measurement_status in ('awaiting_window', 'measuring');
```

Add the per-channel gate (mirror `playlist_health_enabled` at `20260618115221:42`):

```sql
alter table channels add column if not exists playlist_optimizer_enabled boolean default false;
```

`playlists.role/origin/strategy_version/created_by_optimizer_at` already exist — **do not
re-add** (`20260618115221:24-29`).
**REVIEW.** Applies clean to prod clone; new table empty; existing channels default
`playlist_optimizer_enabled=false`. *Effort: ~0.75 day.*

### Step 2B.2 — Rename + reorder YouTube helpers (IMPLEMENT → REVIEW)

**IMPLEMENT.** Two new helpers in `app/youtube_client.py`, mirroring `yt_playlists_insert:224`
(cost 50, `_log_quota` in `finally`, `_guard_token` in `except`):
- `yt_playlists_update(yt, channel_id, playlist_id, title, description)` → `playlists.update`,
  `part="snippet"`, cost 50, operation `"playlists.update"`.
- `yt_playlist_items_update(yt, channel_id, playlist_item_id, playlist_id, video_id, position)`
  → `playlistItems.update`, `part="snippet"` with `snippet.position`, cost 50, operation
  `"playlistItems.update"`.

(PO §Quota costs table, lines 337–340: `playlists.update`/`delete` = 50; note there is **no**
`playlistItems` reorder helper today.)
**REVIEW.** Live probe on a throwaway playlist: rename lands; reorder moves an item to
`position 0`; both `quota_log` rows at units=50. *Effort: ~0.75 day.*

### Step 2B.3 — `app/playlist_construction.py` — candidate gen + LLM re-rank (IMPLEMENT → REVIEW)

**IMPLEMENT.** New file with a `build_playlists(channel_id)` entry. **Own DRY_RUN guard first**
(`if settings.DRY_RUN: return ...` — gating lives in callers, `playlists.py:306`).
- **Stage 1 — candidate generation (recall).** Reuse `_cluster_orphans_for_channel`
  (`playlist_discovery.py:118`) and/or `_sims_matrix` (`playlists.py:170`) to produce candidate
  video pools. Cosine is recall only.
- **Stage 2 — LLM re-rank for session continuation.** `chat_json` re-ranks a pool by topical fit ×
  candidate retention strength × complementarity (penalize redundancy, reward "next-step"
  relationships) — PO lines 186–188. Condition on `playlist_competitor_reference_json` (2A) as a
  hypothesis input. Thread `default_language`.
**REVIEW.** On the pilot channel with `DRY_RUN=true`, the pipeline emits a proposed ordered pool
+ rationale and writes nothing to YouTube. *Effort: ~2 days.*

### Step 2B.4 — Ordering / entry-point + metadata (IMPLEMENT → REVIEW)

**IMPLEMENT.** In `playlist_construction.py`: choose position 1 deliberately (strong opener),
sequence for smooth handoffs (PO line 190); generate optimized title + description via `chat_json`
under the `default_language` rule (PO line 193). Lift the hardcoded cap: use
`MAX_NEW_PLAYLISTS_PER_WINDOW=3` (PO line 329) instead of `playlist_discovery.MAX_NEW_PLAYLISTS=2`
(`:18`).
**REVIEW.** Ordering is deterministic given a fixed pool; metadata is language-correct; the
per-window cap is enforced. *Effort: ~1 day.*

### Step 2B.5 — Apply path: execute + stamp interventions (IMPLEMENT → REVIEW)

**IMPLEMENT.** The write path. For each construction action, before the YouTube write, insert a
`playlist_interventions` row (`status='pending'`, `payload`, `before_state` for reversible actions,
`strategy_version`). Execute via `yt_playlists_insert`/`yt_playlist_items_insert`/
`yt_playlists_update`/`yt_playlist_items_update`. On a successful create, stamp the created playlist
`origin='optimizer_created'`, `created_by_optimizer_at=now`, `strategy_version=...`.

**Stamp on apply (mirror `audits.py:414-432`, specifically `:420-425`):** set intervention
`status='applied'`, `applied_at=now`; **and, gated on `playlist_optimizer_enabled`**, set
`measurement_status='awaiting_window'` + `measurement_started_at=now`, **and write the pre-change
`playlist_metrics` baseline** with `is_pre_change=true` (new playlists baseline from zero).

> **Net-new write path.** `is_pre_change` is never written today — `_upsert_playlist_metrics`
> (`metrics_poll.py:126`) builds a payload with no `is_pre_change` key, so it always defaults
> false (`20260610134419:61`). The baseline upsert must use
> `on_conflict="playlist_id,window_start,window_end"` (the table's unique key,
> `20260610134419:63`), mirroring `measurement._write_baseline` (`measurement.py:137-151`).

**Quota + DRY_RUN.** Guard writes with the soft `_yt_quota_exhausted_until` cutoff
(`autopilot.py:436`) or a `can_afford(50 * n)` check (`quota.py:38`). Never bypass DRY_RUN.
**Do not route through `playlist_proposals`** — that table is legacy membership HITL; construction
uses `playlist_interventions`.
**REVIEW.** With `DRY_RUN=false` on the pilot channel: a build creates a playlist, an intervention
row lands `status='applied'`/`measurement_status='awaiting_window'`, a `playlist_metrics` row with
`is_pre_change=true` exists, and the created playlist row carries `origin='optimizer_created'`.
*Effort: ~1.5 days.*

### Step 2B.6 — `POST /channels/{id}/playlists/build` endpoint (IMPLEMENT → REVIEW)

**IMPLEMENT.** On `app/playlists_router.py`, next to `POST .../reconcile` (`:280`). Gate on
`playlist_optimizer_enabled`: when off, return an empty envelope (`enabled: false`, 200 — mirror
`evaluate_playlists` at `:130-141` which returns `enabled=false` rather than 403). Config:
`PLAYLIST_OPTIMIZER_ENABLED` is the per-channel column (not env), `MAX_NEW_PLAYLISTS_PER_WINDOW=3`,
`PLAYLIST_AUTO_DELETE=false`.
**REVIEW.** `curl` on a disabled channel returns `enabled=false` and writes nothing; on the
enabled pilot channel it runs the pipeline. *Effort: ~0.75 day.*

---

# PHASE 2C — Playlist self-eval — the keystone (~3–4 days) — DEPENDS ON 2B

**Goal (PO §Control loop "Decision policy", lines 253–259; plan.md §2C, lines 129–133):** a
`measurement_eval` analog for `playlist_interventions`. After the window and the min-starts gate,
write `win`/`neutral`/`regression` → keep / revise / recommend-prune. This is what stops the
dead-playlist treadmill: created playlists are judged, not just made.

Spec quote (PO Decision policy, lines 253–256):

> Compare post-change vs pre-change session metrics (primary: `averageTimeInPlaylist` and
> `viewsPerPlaylistStart`; secondary: playlist-source views to members). Win → keep; neutral →
> keep; regression → revise … or, if inert, recommend prune.

## 2C.1 Design — mirror `app/measurement.py` part-for-part

New file `app/playlist_measurement.py`, structured to mirror `app/measurement.py`:

| `measurement.py` element | `playlist_measurement.py` analog |
|---|---|
| `_TERMINAL=("win","neutral","regression")` (`measurement.py:58`) | Same tuple. |
| `_windows` (`:70`) — `MEASUREMENT_WINDOW_DAYS`, apply day ±1 excluded from both windows | `_windows` using `settings.PLAYLIST_MEASUREMENT_WINDOW_DAYS=35` (**exists** `config.py:120`); apply-day ±1 excluded. |
| `_classify` (`:121`) — relative CTR delta vs `CTR_*_THRESHOLD` | `_classify` on the **tier-1 pair** `avg_time_in_playlist_sec × views_per_playlist_start` (the formula at `playlist_health.py:272-275`), per spec lines 253–256. **Needs new `PLAYLIST_*_WIN/REGRESSION_THRESHOLD` config.** |
| `_write_baseline` (`:137`) — upsert `video_metrics` `is_pre_change=true` | Upsert a `playlist_metrics` row `is_pre_change=true`, `on_conflict="playlist_id,window_start,window_end"` (`20260610134419:63`). Baseline is written at apply in 2B (Step 2B.5); 2C reads it. |
| `_finalize` (`:154`) — updates `audits.measurement_status/outcome_decision/measurement_result` | Updates the same three fields on `playlist_interventions`. |
| `_eval_audit` (`:162`) — per-item state machine, `MIN_IMPRESSIONS` floors | `_eval_intervention` per-item state machine, **`MIN_PLAYLIST_STARTS=50` gate** (`config.py:119`) on **summed `playlist_starts`**; regression is **human-gated** (outcome stays for review, no auto-act). |

### The biggest structural divergence (do not paper over it)

Video measurement certifies coverage from a **daily reach ledger** (`_ledger_state` via
`reporting_poll`, imported at `measurement.py:52`; used at `:308`). **Playlists have no daily
reach ledger** — there is no `_ledger_state` analog. Coverage certification for a playlist window
is instead the **presence of the relevant WEEKLY `playlist_metrics` rows** covering the window,
plus the ~2-day Analytics lag. Do not invent a reach-CSV path; certify on the weekly rows that
`metrics_poll._upsert_playlist_metrics` (`metrics_poll.py:126`) already writes.

## 2C.2 Steps

### Step 2C.1 — Config thresholds (IMPLEMENT → REVIEW)

**IMPLEMENT.** Add to `config.py` (alongside the 1B playlist block at `:119-123`):
`PLAYLIST_WIN_THRESHOLD`, `PLAYLIST_REGRESSION_THRESHOLD` (relative, mirror `CTR_WIN_THRESHOLD`/
`CTR_REGRESSION_THRESHOLD` at `config.py:129`). `PLAYLIST_MEASUREMENT_WINDOW_DAYS=35` (`:120`) and
`MIN_PLAYLIST_STARTS=50` (`:119`) already exist — reuse.
**REVIEW.** Env-overridable; sane defaults. *Effort: ~0.25 day.*

### Step 2C.2 — `app/playlist_measurement.py` core (IMPLEMENT → REVIEW)

**IMPLEMENT.** Implement `_TERMINAL`, `_windows`, `_classify`, `_write_baseline` (read/verify),
`_finalize`, `_eval_intervention` per §2C.1. `_classify` compares the tier-1 pair
(`avg_time_in_playlist_sec × views_per_playlist_start`); gate on summed `playlist_starts >=
MIN_PLAYLIST_STARTS`. Coverage = presence of the weekly `playlist_metrics` rows spanning the
window (+ ~2-day lag), not a ledger. Record `"attribution": "bundle"` in `measurement_result`
(PO §Attribution caveat, lines 261–266; a video belongs to several playlists, so attribute
bundle-level). Regression → `outcome_decision` left for human review (no auto-prune).
**REVIEW.** Unit-level with seeded `playlist_metrics`: a clear win/neutral/regression each land the
right verdict; a below-gate playlist stays in `measuring`/`awaiting_window`. *Effort: ~1.25 days.*

### Step 2C.3 — Job entry `playlist_measurement_eval` (IMPLEMENT → REVIEW)

**IMPLEMENT.** Mirror `eval_measurements` (`measurement.py:247-317`): pull
`playlist_interventions` where `measurement_status in ('awaiting_window','measuring')` **AND**
`status='applied'`, grouped by `channel_id`. **Simpler than the video path:** interventions carry
`channel_id` directly (PO schema line 221), so no video→channel join (`measurement.py:281-292`
is unnecessary). Isolate per-channel exceptions.
**REVIEW.** Manual trigger over the pilot channel returns a counts summary; in-flight-only rows are
touched (partial index from Step 2B.1 is the query's support). *Effort: ~0.5 day.*

### Step 2C.4 — Scheduler + router registration (IMPLEMENT → REVIEW)

**IMPLEMENT.** Add a `playlist_measurement_eval` cron in `app/main.py` lifespan **after**
`measurement_eval` — the measurement crons run UTC: `playlist_health_score` 07:00 (`main.py:263-266`),
`measurement_eval` 08:00 (`main.py:282-286`); place this at **~09:00 UTC**, UTC-pinned, same
`max_instances=1, coalesce=True` shape. Register the new router at `app/main.py:335` next to
`app.include_router(measurement_router)`.
**REVIEW.** Cron fires; router endpoints reachable. *Effort: ~0.25 day.*

### Step 2C.5 — Endpoints (IMPLEMENT → REVIEW)

**IMPLEMENT.** On the new router (PO §Endpoints, lines 353–355):
- `GET /playlist-interventions/{id}/measurement` — mirror `get_measurement` (`measurement.py:322`).
- `POST /playlist-interventions/{id}/confirm-delete` — **THE one human gate** (PO line 355).
  Gated `PLAYLIST_AUTO_DELETE=false`; deletion is **irreversible** via the API (PO lines 257–259),
  so this is the only path that calls a destructive playlist delete, and only after explicit human
  confirmation. Set intervention `action`/`outcome_decision='pruned'` on success.
- A playlist-outcomes rollup mirroring `channel_outcomes` (`GET /channels/{id}/outcomes`,
  `measurement.py:340`) — win/neutral/regression counts + `pending_review` (regressions with
  `outcome_decision='none'`) over `playlist_interventions`.
**REVIEW.** `confirm-delete` refuses without confirmation and when `PLAYLIST_AUTO_DELETE=false`
short-circuits any auto path; the rollup returns sane counts. *Effort: ~0.75 day.*

---

## Migration list (all idempotent — `IF NOT EXISTS` / `IF EXISTS`)

| Sub-track | Migration | Contents |
|---|---|---|
| 2A | `..._phase2a_competitor_reference.sql` | `channels.playlist_competitor_reference_json jsonb`, `channels.playlist_competitor_built_at timestamptz` (mirror `20260618115221:42`). |
| 2B | `..._phase2b_playlist_interventions.sql` | `playlist_interventions` table (PO lines 220–235); partial index on `('awaiting_window','measuring')` (mirror `20260702183233:50`); `channels.playlist_optimizer_enabled boolean default false` (mirror `20260618115221:42`). |
| 2C | *(none required)* | Reuses `playlist_metrics.is_pre_change` (`20260610134419:61`) and `playlist_interventions` (2B). Config-only. |

## Config / flag additions (`config.py`)

| Setting | Default | Sub-track | Source / note |
|---|---|---|---|
| `COMPETITOR_REFRESH_DAYS` | `90` | 2A | PO line 326. Skip-if-fresh guard, **not** a cron interval. |
| `COMPETITOR_DISCOVERY_QUOTA_BUDGET` | `2000` | 2A | PO line 327. Enforced via `units_used_today_for("search.list")`. |
| `COMPETITOR_MIN_SUBSCRIBER_MULTIPLE` | `3` | 2A | PO line 328. |
| `playlist_optimizer_enabled` | per-channel column, `false` | 2B | PO line 323. Mirror `playlist_health_enabled` (`config.py`/`main.py:148`). |
| `MAX_NEW_PLAYLISTS_PER_WINDOW` | `3` | 2B | PO line 329. Lifts hardcoded `MAX_NEW_PLAYLISTS=2` (`playlist_discovery.py:18`). |
| `PLAYLIST_AUTO_DELETE` | `false` | 2B/2C | PO line 330. Human gate stays OFF. |
| `PLAYLIST_MEASUREMENT_WINDOW_DAYS` | `35` | 2C | **Already exists** `config.py:120`. |
| `MIN_PLAYLIST_STARTS` | `50` | 2C | **Already exists** `config.py:119`. |
| `PLAYLIST_WIN_THRESHOLD` / `PLAYLIST_REGRESSION_THRESHOLD` | tune | 2C | New; mirror `CTR_WIN/REGRESSION_THRESHOLD` (`config.py:129`). |

## Endpoints added

| Method + path | Sub-track | Handler location | Notes |
|---|---|---|---|
| `GET /channels/{id}/playlist-competitor-reference` | 2A | `playlists_router.py` | Cached read of the column (PO line 352). |
| `POST /channels/{id}/playlists/competitor-reference/rebuild` | 2A | `playlists_router.py` | Force rebuild (PO line 352). |
| `POST /channels/{id}/playlists/build` | 2B | `playlists_router.py` (next to `/reconcile` `:280`) | Gate on `playlist_optimizer_enabled`; empty envelope when off (mirror `evaluate_playlists:130`). |
| `GET /playlist-interventions/{id}/measurement` | 2C | new `playlist_measurement.py` router | Mirror `measurement.py:322`. |
| `POST /playlist-interventions/{id}/confirm-delete` | 2C | new router | **The one human gate** (PO line 355); irreversible; `PLAYLIST_AUTO_DELETE=false`. |
| `GET /channels/{id}/playlist-outcomes` (rollup) | 2C | new router | Mirror `channel_outcomes` (`measurement.py:340`). |

## Review-checkpoint / effort summary

| Sub-track | Steps | Rough effort | Gate before next |
|---|---|---|---|
| 2A | 2A.1–2A.8 | ~4–5 days | Reference JSON populated (inferred, distinct from measured); sub-budget respected; no scraping. |
| 2B | 2B.1–2B.6 | ~7–9 days | On the pilot channel, the optimizer creates a playlist, stamps an intervention (`applied`/`awaiting_window`), writes an `is_pre_change=true` baseline; legacy allocator still runs on disabled channels. |
| 2C | 2C.1–2C.5 | ~3–4 days | `playlist_measurement_eval` scheduled; a stamped intervention grades to a terminal verdict after the window; delete stays human-confirmed. |

2C's exit is the plan.md §Phase 2 exit gate (line 136): *on one channel, the optimizer builds
playlists, stamps them, and the self-eval job is scheduled to grade them after the window.*

---

## Appendix — discipline checklist (carry into every PR)

**DRY_RUN**
- [ ] Every new write path (`playlist_construction.py`, the apply path, `confirm-delete`) has its
      own `if settings.DRY_RUN: return` guard — DRY_RUN gating lives in callers, not
      `youtube_client` (`playlists.py:306`, `playlist_discovery.py:161`).
- [ ] No YouTube write leaks when DRY_RUN is on.

**Quota gates**
- [ ] `units_used_today_for` keeps the `.gt("units", 0)` filter on `occurred_at` (the 1000-row-cap
      dodge, `quota.py:17`).
- [ ] Every `search.list` in 2A gated on **both** `can_afford(100)` and
      `COMPETITOR_DISCOVERY_QUOTA_BUDGET`; discovery never starves audit/apply quota.
- [ ] 2B writes ride `_yt_quota_exhausted_until` (`autopilot.py:436`) or check `can_afford(50 * n)`.

**Human gates OFF**
- [ ] `PLAYLIST_AUTO_DELETE=false`; deletion happens only via `POST .../confirm-delete` after
      explicit human confirmation (irreversible — PO lines 257–259).
- [ ] `playlist_optimizer_enabled` is per-channel, default false; one channel first.
- [ ] Regression verdicts are surfaced for review (`outcome_decision='none'`), never auto-pruned
      (mirror `measurement.py:236`).

**Reconciliation discipline**
- [ ] The legacy allocator (`playlists.py`, `playlist_discovery.py`) is **demoted, not deleted**;
      legacy creation still runs for channels without `playlist_optimizer_enabled`.
- [ ] Construction uses `playlist_interventions`, never `playlist_proposals` (keep the two
      human-gate tables distinct).
- [ ] Optimizer-created playlists stamp `origin='optimizer_created'` + `created_by_optimizer_at`
      (columns reserved at `20260618115221:24-29`).

**Migrations**
- [ ] All ops `IF NOT EXISTS` / `IF EXISTS`.
- [ ] `playlist_interventions` partial index mirrors `audits_measurement_inflight_idx`
      (`20260702183233:50`).
- [ ] No re-add of the reserved `playlists` columns.

**Web-only + inference caveats (repeat in PR descriptions)**
- [ ] 2A: the competitor reference is **inferred structure from public signals, not measurement**
      (competitors' session metrics are owner-only — PO line 166). Stored distinct from any
      measured playbook.
- [ ] 2C: session metrics (`playlistStarts`, `averageTimeInPlaylist`, `viewsPerPlaylistStart`) are
      **web-only** — judge relative/trend, never absolute cross-channel (PO lines 110–113, 370–371).
- [ ] 2C: attribution is **bundle-level** — record `"attribution": "bundle"` in
      `measurement_result` (PO lines 261–266).
- [ ] 2C: 35-day window → outcomes mature over **months**, not weeks (PO line 288/377); this is
      expected, not a bug.
- [ ] Schema drift: `avg_time_in_playlist_sec` is **integer seconds** in the DB
      (`20260610134419:58`), not the spec's `avg_time_in_playlist_min` (PO line 100). Use the
      shipped `_sec` column.
- [ ] `isCurated` deprecation: verify the live playlist report shape with one `reports.query`
      before building any new abstraction (PO lines 114–117).
