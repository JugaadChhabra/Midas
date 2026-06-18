# Phase 1B — Playlist Inventory + Health (Recommend-Only) — Planning Doc

**Status:** DRAFT — to be reviewed before any implementation work begins.
**Spec sources of record:** `docs/plan.md` §Phase 1 (1B), `docs/PLAYLIST_OPTIMIZATION.md`
§Sensor / §Control loop / §Data model summary, `docs/PHASE_0_GAPS.md` (Gaps 5, 6, 9).
**Substrate already shipped:** Phase 0 sensor (`analytics_client.py`, `metrics_poll.py`,
`video_metrics` + `playlist_metrics` tables, `analytics_authorized` per-channel flag).

> This is a **planning doc, not a spec**. It proposes, justifies, and flags open
> questions. No code, no migration SQL — only enumerations and rationale.

---

## 1. Goals + non-goals

### Goals (what 1B ships)

Per plan.md §Phase 1 / 1B, verbatim:

> - `playlists` table; sync existing playlists; classify role where inferable.
> - Score each playlist on session contribution (`averageTimeInPlaylist`,
>   `viewsPerPlaylistStart`, playlist-source views to members), gated on
>   `MIN_PLAYLIST_STARTS`.
> - `POST /channels/{id}/playlists/evaluate` → revive/remove **recommendations
>   only**. No `delete`, no `playlistItems` writes yet.

Concretely:

1. Extend the existing `playlists` table to carry the role/origin/lineage columns
   PO §Control loop calls out.
2. Extend `playlists_sync.sync_playlists` to populate the new columns (role inferred
   where possible; `origin='inherited'` and `created_by_optimizer_at=NULL` for all
   existing playlists).
3. Add a daily health-scoring job (or extend `metrics_poll`) that reads the rolling
   `playlist_metrics` window and produces a per-playlist score + revive/remove
   recommendation, gated on `MIN_PLAYLIST_STARTS`.
4. Add `POST /channels/{id}/playlists/evaluate` returning the recommendations as
   data — no execution path.
5. Render scores + recommendations in `channel.html` (extend the existing Playlists
   tab; do not break playlist-allocation UI).
6. Per-channel feature flag `PLAYLIST_HEALTH_ENABLED` (default `false`); pilot on
   one channel for ~1 week before widening.

### Non-goals (explicit out-of-scope)

- **No `playlists.delete`** call against the YouTube API.
- **No `playlistItems.insert` / `delete` writes** triggered by the evaluator. (Note:
  the existing reconcile/proposal path retains its own writes — unchanged.)
- **No revive execution** — "revive" is a recommendation type (e.g. "swap opener",
  "reorder", "rename") but Phase 1B emits only the *recommendation*; revisions
  themselves are a Phase 2B intervention.
- **No competitor research** (Phase 2A).
- **No construction / building new playlists** (Phase 2B).
- **No self-eval / intervention lifecycle** (Phase 2C; `playlist_interventions`
  table is NOT created in 1B).
- **No playbook distillation** (Phase 3B).
- **No automated daily delete-recommendation execution**, even if score is awful —
  the human always confirms.
- **No tier-2 cross-check via Reporting API / CTR data** (Phase 0.5 is a separate
  blocker; CTR is not on the Phase 1B critical path).

The three human gates that stay OFF: `AUTO_REVERT_ON_REGRESSION`,
`PLAYLIST_AUTO_DELETE`, and the new `PLAYLIST_HEALTH_ENABLED` (per-channel
opt-in only).

---

## 2. Existing-state audit

### 2.1 `playlists` table (migration `20260518000000_playlists.sql`)

| Existing column | Type | PO §Control-loop spec? | Disposition |
|---|---|---|---|
| `id` | `text primary key` | Matches PO `id TEXT PRIMARY KEY` | KEEP |
| `channel_id` | `text not null references channels(id) on delete cascade` | PO `channel_id TEXT NOT NULL REFERENCES channels(id)` | KEEP (cascade is a superset of PO; fine) |
| `title` | `text not null` | PO `title TEXT` | KEEP (note: PO doesn't mandate NOT NULL; keep stricter) |
| `description` | `text default ''` | PO `description TEXT` | KEEP |
| `synced_at` | `timestamptz default now()` | PO `last_synced_at TIMESTAMPTZ` | REPURPOSE — rename concept; keep column and **add `last_synced_at` as an alias-add** (see §3). Do not drop `synced_at` (it's read by `playlists_router.playlist_status` indirectly through other code; safer to keep dual until callers move). |

| PO-spec column | In existing table? | Disposition |
|---|---|---|
| `role TEXT` (series, topic_cluster, funnel, inherited, unknown) | No | NEEDS-ADD |
| `origin TEXT DEFAULT 'inherited'` (inherited / optimizer_created) | No | NEEDS-ADD |
| `strategy_version TEXT` (Loop 3) | No | NEEDS-ADD (kept NULL in 1B — Phase 4 owner) |
| `item_count INT` | No | NEEDS-ADD (set by sync) |
| `created_by_optimizer_at TIMESTAMPTZ` | No | NEEDS-ADD (always NULL for inherited) |
| `last_synced_at TIMESTAMPTZ` | Existing `synced_at` is conceptually the same | NEEDS-ADD (per PO naming) — co-exists with `synced_at`; sync writes both for now |

### 2.2 `playlist_assignments` (`20260518000000_playlists.sql`)

Used by the existing similarity-based join/reconcile pipeline. Phase 1B does
**not** touch this table. It remains the source of truth for "what video is in
what playlist" used by `_current_members`. Note for §6: when the evaluator
recommends "revive" (e.g. reorder), it does not write here — it returns the
suggestion as data.

### 2.3 `playlist_proposals` (`20260519000000_playlist_proposals.sql`)

Human-in-the-loop queue for *membership* changes (add/remove videos to/from
playlists). Phase 1B's recommendations are a **different shape** (per-playlist
verdict, not per-membership), so they do **not** route through this table. We
return them inline from `/playlists/evaluate` and let the UI render them. Re-use
later if/when the recommendations need a "decided/dismissed" audit trail; not
needed for the recommend-only Phase 1B.

### 2.4 `playlist_metrics` (`20260610134419_metrics_tables.sql`)

Already populated daily by `metrics_poll._upsert_playlist_metrics` with weekly
trailing windows. Columns map 1:1 to what 1B's scoring job needs
(`playlist_starts`, `views_per_playlist_start`, `avg_time_in_playlist_sec`,
`playlist_views`, `playlist_est_minutes_watched`). `playlist_id` is
**FK-free** — see §3 for the Gap 5 decision.

### 2.5 Existing endpoints (`playlists_router.py`)

| Endpoint | Purpose | Phase 1B impact |
|---|---|---|
| `POST /channels/{id}/playlists/bootstrap` | Sync + embed | No change. Sync work in §4 hooks into this. |
| `GET /channels/{id}/playlists/status` | Embedding + assignment counts | No change. Health view is separate (§7). |
| `POST /channels/{id}/playlists/reconcile` | Trigger similarity reconcile | No change. |
| `GET /channels/{id}/playlists/proposals` | List membership proposals | No change. |
| `POST /channels/{id}/playlists/proposals/decide` | Approve/reject membership proposals | No change. |
| **NEW** `POST /channels/{id}/playlists/evaluate` | Health + revive/remove recs | §6 |
| **NEW** `GET /channels/{id}/playlists/health` *(proposal)* | Cached read of latest scores for UI | §6 (optional convenience read) |

---

## 3. Schema migration plan

**One new idempotent migration**, e.g. `20260619000000_playlists_phase1b.sql`. All
operations use `IF NOT EXISTS` / `IF EXISTS`, matching Phase 0 conventions.

### 3.1 `ALTER TABLE playlists` additions

| Column | Type / default | Spec justification (PO §Control loop "Tracked entities") |
|---|---|---|
| `role` | `text` (nullable) | `role TEXT — series \| topic_cluster \| funnel \| inherited \| unknown` |
| `origin` | `text not null default 'inherited'` | `origin TEXT DEFAULT 'inherited' — inherited \| optimizer_created` — all rows in 1B are inherited |
| `strategy_version` | `text` (nullable) | `strategy_version TEXT — construction strategy that built it (Loop 3)` — stays NULL until Phase 2B/4 |
| `item_count` | `integer` (nullable) | `item_count INT` |
| `created_by_optimizer_at` | `timestamptz` (nullable) | `created_by_optimizer_at TIMESTAMPTZ` — always NULL in 1B |
| `last_synced_at` | `timestamptz default now()` | `last_synced_at TIMESTAMPTZ` (the existing `synced_at` is left in place to avoid breaking unrelated readers) |

Idempotency: every line is `add column if not exists ...`.

### 3.2 Health-score storage (decision required — see §5)

If we go with "score column on `playlists`":

| Column | Type | Rationale |
|---|---|---|
| `health_score` | `float` (nullable) | Latest score; null = "not enough data yet" / below gate |
| `health_recommendation` | `text` (nullable) | `revive` / `remove` / `keep` / `insufficient_data` |
| `health_computed_at` | `timestamptz` (nullable) | Provenance |
| `health_rationale_json` | `jsonb` (nullable) | Inputs: window, `playlist_starts`, `views_per_playlist_start`, `avg_time_in_playlist_sec`, tier-2 if available, gate-pass flag |

Alternative: separate `playlist_health` table keyed by `(playlist_id, computed_at)`
so we keep history. **Recommendation:** start with denormalized columns on
`playlists` (cheap, easy UI read) AND let `playlist_metrics` history be the
audit trail. If we ever need per-day health history we can move to a separate
table without touching the score logic.

### 3.3 Gap 5 — should `playlist_metrics.playlist_id` get an FK now?

**Quoted from Phase 0 gaps doc, Gap 5:**

> Once Phase 1B settles the `playlists` table extensions, revisit whether to add
> an FK with `ON DELETE CASCADE` (matches `video_metrics.video_id`'s pattern) —
> or leave it FK-free if the use case (e.g. measuring a playlist mid-sync) makes
> that flexibility valuable.

**Recommendation: leave it FK-free for Phase 1B.** Two reasons:

1. `metrics_poll` polls every playlist returned by Analytics; a playlist could
   appear in Analytics before the next `sync_playlists` run inserts it into
   `playlists`. An FK would either drop the metrics row or require ordering
   discipline that doesn't currently exist.
2. The PO spec deliberately does not declare an FK. Adding one is a one-way door
   (cascading deletes can silently wipe history); not adding one is reversible.

If reviewers disagree, the safe alternative is FK with `ON DELETE SET NULL` (not
`CASCADE`) so metric history survives playlist removal. Flagged as an open
question in §11.

### 3.4 What this migration does NOT touch

- No `playlist_interventions` table (Phase 2B/2C).
- No additions to `channels` table (`playlist_competitor_reference_json`,
  `playlist_playbook_json` — Phase 2A/3B).
- No `audit_strategies` `playlist:` rows (Phase 4).
- No changes to `playlist_assignments` or `playlist_proposals`.

---

## 4. Sync work

### 4.1 `playlists_sync.sync_playlists` changes

Current upsert payload (lines 36–46) writes `id, channel_id, title, description,
synced_at`. Phase 1B extends it to write:

- `last_synced_at` — `now`, same value as `synced_at`.
- `origin` — `'inherited'` for every row (sync only sees existing playlists).
- `created_by_optimizer_at` — explicitly `NULL` (never set by sync).
- `item_count` — derived from the `yt_playlist_items_page` walk that already
  happens in the same function. Track a counter per playlist; upsert at the end
  of the per-playlist loop, OR do a second upsert after the membership-seeding
  walk completes.
- `role` — `'inherited'` if no inference rule fires; otherwise see §4.2.
- `strategy_version` — left untouched (NULL); only the optimizer-created path
  writes it in Phase 2B.

The membership-seeding walk should also bump `item_count` even on subsequent
runs (idempotent: count is recomputed each sync).

### 4.2 Role classification (where inferable)

Spec quote: "classify role where inferable." Keep this **conservative** — wrong
roles produce wrong recommendations later. Suggested heuristics, applied in
order; first match wins; otherwise default to `'inherited'`:

| Signal | Role |
|---|---|
| Title or description contains keywords like `episode`, `part \d+`, `ep \d+`, `season`, `chapter`, `lesson` | `series` |
| Title starts with `Start here`, `Watch first`, `Beginners`, `Intro to` | `funnel` |
| Otherwise, multiple videos that share a strong common substring/topic token in their titles, and the playlist title is a topic noun phrase | `topic_cluster` |
| None of the above | `inherited` |

The serious version of role inference is LLM-based (look at member titles + the
playlist title/description and classify). **Recommendation:** start regex-only
in 1B (deterministic, debuggable, no quota). Add LLM classifier later if the
regex misses too many. Flagged in §11.

### 4.3 Where the sync is triggered

Already wired:
- `POST /channels/{id}/playlists/bootstrap` (manual).
- `_daily_reconcile` cron at 02:00 server-local (`app/main.py` line 78–85).

No new scheduling needed for Phase 1B sync work — it piggybacks on the existing
daily reconcile. If `_daily_reconcile` does not currently call `sync_playlists`,
add that call; otherwise it's already covered.

---

## 5. Health-scoring job

### 5.1 Where it lives

**Recommendation: new file `app/playlist_health.py`** with a single `score_channel(channel_id)`
entry point. Reasons:

- `metrics_poll.py`'s job is sensor-only (write rows). Mixing in derived scores
  would violate Phase 0's discipline of "sensor writes raw, downstream consumes."
- A standalone module mirrors how `app/audits.py` consumes `performance.py`'s
  numbers — separation between raw measurement and judgement.
- Easier to test in isolation; easier to disable per-channel via flag.

Trigger: extend the daily 02:00 cron to call `score_channel` for every channel
where `PLAYLIST_HEALTH_ENABLED` is true. Runs AFTER `metrics_poll` (UTC 05:00)
would be ideal so the score reflects fresh metrics. **Recommendation:** schedule
a new cron `playlist_health_score` at UTC 06:00, after metrics_poll, daily.

### 5.2 What it computes

**Spec quote (PO §Control loop, "Decision policy (critic)"):**

> Compare post-change vs pre-change session metrics (primary:
> `averageTimeInPlaylist` and `viewsPerPlaylistStart`; secondary: playlist-source
> views to members). Win → keep; neutral → keep; regression → revise (re-order /
> re-theme / swap members) or, if inert, recommend prune.

**Spec quote (PO §Sensor, "Min-data + age gate"):**

> Don't evaluate until it has accrued `>= MIN_PLAYLIST_STARTS` over a window of
> at least `PLAYLIST_MEASUREMENT_WINDOW_DAYS`.

For Phase 1B (no interventions yet → no pre/post comparison), the score is the
**absolute health snapshot** of the latest aggregated window:

- **Tier 1 (always computed):** `score_t1 = avg_time_in_playlist_sec *
  views_per_playlist_start`, aggregated over the trailing window. This is the
  "session contribution" metric pair PO calls out.
- **Tier 2 (conditional on Gap 6):** playlist-source views to member videos.
  Requires the new analytics-client function (see §9). If unavailable, score
  carries a `tier_2_pending=true` flag and recommendations are made on tier-1
  only.

### 5.3 Window aggregation

`playlist_metrics` rows are weekly trailing windows. For the score, aggregate the
**last 4 weekly rows** (≈28 days — close to PO's `PLAYLIST_MEASUREMENT_WINDOW_DAYS=35`
default, with one week of slack). Sum `playlist_starts`, weighted-average
`views_per_playlist_start` and `avg_time_in_playlist_sec` by `playlist_starts`.

If `sum(playlist_starts) < MIN_PLAYLIST_STARTS` → `health_recommendation = 'insufficient_data'`,
score stored as NULL. **This is the gate.**

### 5.4 Recommendation classification

Once a playlist passes the gate:

- Compute **per-channel percentile** of `score_t1` across all gate-passing
  playlists on that channel (PO §Sensor "Gotchas" — these are web-only counts;
  judge **relatively**, not against absolute thresholds. Per-channel percentile
  is the natural relative comparator.)
- Bottom decile (or two configurable thresholds, e.g. `HEALTH_REMOVE_PCTL=10`,
  `HEALTH_REVIVE_PCTL=33`) → `remove` / `revive` / `keep`.
- Recommendation rationale stored verbatim in `health_rationale_json` for UI
  display: the percentile, the raw numbers, the gate status, and the
  tier_2_pending flag.

**Recommendation:** start with thresholds in config, not hardcoded. We will tune
once the pilot channel produces real numbers.

### 5.5 New config knobs (`config.py`)

| Setting | Default | Source |
|---|---|---|
| `MIN_PLAYLIST_STARTS` | `50` | PO §Config table, verbatim |
| `PLAYLIST_MEASUREMENT_WINDOW_DAYS` | `35` | PO §Config table |
| `PLAYLIST_HEALTH_AGG_WEEKS` | `4` | Implementation knob (matches §5.3 above) |
| `PLAYLIST_HEALTH_REMOVE_PCTL` | `10` | Recommendation threshold |
| `PLAYLIST_HEALTH_REVIVE_PCTL` | `33` | Recommendation threshold |
| `PLAYLIST_HEALTH_ENABLED` | per-channel column, default `false` | Rollout gate (§8) |

Note: `PLAYLIST_HEALTH_ENABLED` is **per-channel**, like `autopilot_enabled`
(`channels` table), not a global env flag. See §8.

---

## 6. `POST /channels/{id}/playlists/evaluate` endpoint

### 6.1 Behaviour

1. Look up channel; 404 if missing.
2. Check per-channel `PLAYLIST_HEALTH_ENABLED` flag; if false, return `{"enabled":
   false, "recommendations": []}` with 200 (not 403 — it's a UI affordance, not a
   security gate).
3. Re-run `score_channel(channel_id)` synchronously so the response is fresh.
4. Read back the `playlists` rows with their health columns.
5. Return the structured list.

**Recommend-only:** the endpoint never calls `playlistItems.insert/delete` or
`playlists.delete`. It writes only to the `playlists.health_*` columns.

### 6.2 Response shape (proposal)

```json
{
  "enabled": true,
  "channel_id": "UC...",
  "computed_at": "2026-06-19T06:00:00Z",
  "window": {"weeks": 4, "min_starts_gate": 50},
  "tier_2_available": false,
  "recommendations": [
    {
      "playlist_id": "PL...",
      "title": "...",
      "role": "topic_cluster",
      "origin": "inherited",
      "item_count": 23,
      "current_score": 184.2,
      "percentile": 7,
      "action": "remove",
      "rationale": {
        "gate": "pass",
        "playlist_starts_28d": 64,
        "views_per_playlist_start": 1.3,
        "avg_time_in_playlist_sec": 142,
        "tier_2_pending": true,
        "comparison": "bottom 10% of this channel's gated playlists"
      }
    },
    {
      "playlist_id": "PL...",
      "action": "insufficient_data",
      "rationale": {"gate": "fail", "playlist_starts_28d": 7}
    }
  ]
}
```

Recommendation `action` is one of: `keep`, `revive`, `remove`, `insufficient_data`.
The UI is responsible for visually distinguishing them; the API is dumb.

### 6.3 Optional `GET /channels/{id}/playlists/health`

A cached read (returns the `playlists.health_*` columns as stored, without
re-running scoring). Useful so the UI can render fast without forcing a recompute
on every page-load. **Recommendation:** ship both — POST forces a recompute,
GET reads the cached snapshot.

---

## 7. UI rendering

### 7.1 Where it goes

The existing Playlists tab (`channel.html` line 83, panel at line 160–163) is
the "Playlist allocation" view — bootstrap button, allocation status, proposals
queue. Phase 1B adds a **new subview** below the existing allocation card:

```
[Playlists tab]
├── (existing) Playlist allocation card — bootstrap, status, proposals
└── (new)      Playlist health card — score table + recommendation badges
```

This avoids a new top-level tab while keeping the two functions visually
distinct.

### 7.2 What the health card renders

- Header: "Playlist health" + "Last computed: <timestamp>" + "Recompute" button
  (POSTs `/playlists/evaluate`).
- If `PLAYLIST_HEALTH_ENABLED=false` for this channel: a single-line empty state
  with an "Enable playlist health" affordance (or just a muted note; enabling is
  a one-off ops action, not a UI toggle in 1B).
- Table: one row per playlist, columns `Title`, `Role`, `Items`, `Starts (28d)`,
  `Score`, `Recommendation` (badge), `Rationale` (expandable cell with the JSON
  rationale rendered as readable bullets).
- Sort: by `score` ascending by default so "worst first" is the natural UX for a
  prune review.

### 7.3 Compatibility

The Playlist-allocation card (`loadPlaylistStatus`, `loadProposals` in the
existing JS) is untouched. New JS function `loadPlaylistHealth()` added to the
panel's load chain (line 1034's `Promise.all`).

No CSS framework changes; reuse the existing `.kpi-val`, `.muted`, table styles.

---

## 8. Per-channel rollout flag

### 8.1 Flag mechanics

Following the `autopilot_enabled` pattern (`channels` table, `boolean default
false`):

- Add column `channels.playlist_health_enabled boolean default false` in the
  same Phase 1B migration.
- `config.py` exposes a helper `def playlist_health_enabled(channel_id) -> bool`
  that reads the column.
- The scoring job and `/playlists/evaluate` both gate on this.

Spec basis: PO §Config table lists `PLAYLIST_OPTIMIZER_ENABLED` as "per-channel,
gate the whole subsystem (like thumbnail flags)." `PLAYLIST_HEALTH_ENABLED` is
the narrower 1B flag — we are NOT enabling the full optimizer yet, only the
health-read half. Naming distinction matters: when Phase 2B lands, it will
introduce `PLAYLIST_OPTIMIZER_ENABLED` (write path) separately.

### 8.2 Pilot channel

Per plan.md cross-cutting rule: "One channel first, ~1 week, then widen."

**Recommended pilot:** `UC8KjoL0Z9mTHKqB6gFutkJw` — this is the channel already
running Phase 0 metrics_poll (per PHASE_0_GAPS.md Gap 1 §Status, Gap 10 §Observation:
first real `poll_metrics()` run on 2026-06-17 was against this channel). It has
the most accrued `playlist_metrics` rows by the time 1B ships, so the scoring
job has real data on day one.

The alternative channel `UCr5-YUqBiW7PUmeAtxUWuRg` mentioned in PHASE_0_GAPS
was used for the live probe but has fewer accumulated metrics. Flagged for
confirmation in §11.

---

## 9. Tier-2 scoring resolution

### 9.1 The dependency

PO §Control loop: "secondary: playlist-source views to members." Phase 0 Gap 6
documents this as deferred:

> Add an `insightTrafficSource=PLAYLIST`-filtered video report function to
> `analytics_client.py` ... Land it inside Phase 1B's "score each playlist on
> session contribution" step, not as a Phase 0 amendment.

### 9.2 Recommendation

**Ship Phase 1B with tier-1 scoring only and a clearly-flagged "tier-2 pending"
marker on every recommendation.** Land the tier-2 analytics function as a
separate work item *inside* Phase 1B but **gated behind a feature flag** so the
recommend-only UI can ship and bake on the pilot channel even if tier-2 lands
late.

Concretely:
- **Step A (must ship in 1B):** schema, sync, tier-1 scoring, endpoint, UI.
  Recommendation badges marked `tier_2_pending=true`.
- **Step B (should ship in 1B):** add
  `yt_analytics_video_traffic_source_playlist(analytics, video_id, start, end)`
  to `analytics_client.py`. Add a daily aggregator (extend `metrics_poll` or new
  `traffic_source_poll`) that writes per-video playlist-source view counts to a
  new table (e.g. `video_traffic_source_playlist`). Update scoring to consume
  this; flip `tier_2_pending=false` on the recommendation rationale.

Why split: tier-2 introduces a new poll surface, a new table, and a fan-out
question (per video per playlist per day → row count). Doing the data model
under the same review gate as the recommend-only UI bloats the review. Splitting
lets Step A ship and bake while Step B is sized properly.

If reviewers want a single step, that's fine — but be explicit that Step B will
roughly double Phase 1B's surface area.

### 9.3 New table for tier-2 (sketch only)

If Step B ships:

| Table | Columns (sketch) | Notes |
|---|---|---|
| `video_traffic_source_playlist` | `video_id, playlist_id, channel_id, window_start, window_end, views, fetched_at` | One row per (video, playlist) pair per window. UNIQUE on `(video_id, playlist_id, window_start, window_end)`. |

Cardinality risk: if a channel has 500 videos × 30 playlists × weekly rows,
that's ~15k rows/week. Manageable, but the poll itself is 500 Analytics calls
per window per channel (one per video, broken down by source playlist). At
current ~12.5% DNS-failure rate (Gap 10) this needs the same per-item error
isolation as the existing poll.

---

## 10. Dependencies on still-open gaps

| Gap | Status | Phase 1B impact |
|---|---|---|
| **Gap 1** (Reporting API / CTR) | OPEN, Phase 0.5 in flight | **No impact on Phase 1B.** Health scoring uses session metrics, not CTR. Confirmed in Gap 1 §"What this does NOT block". |
| **Gap 5** (`playlist_metrics.playlist_id` FK) | TEMPORARY, owed by 1B | **Resolved in §3.3** — recommend leaving FK-free. |
| **Gap 6** (traffic-source PLAYLIST breakdown) | OPEN, owed by 1B | **§9** — recommend ship tier-1 first, tier-2 in same phase under separate review. |
| **Gap 8** (`quota_log` row volume) | OPEN, defer-or-fix | If Step B ships, this gets worse (more analytics calls = more zero-unit rows). Recommend applying the cheap fix (sparkline filter `units > 0`) inside 1B, deferring proper aggregation. |
| **Gap 9** (7-day refresh-token expiry, OAuth Testing mode) | OPEN, operational | **LOAD-BEARING for the rollout-watch week.** Quote: "the ≥1-week watch window is literally unmeetable until the OAuth consent screen is promoted to 'In production'." Phase 1B's exit gate ("health scores + prune recommendations render for human review") still requires ≥1 week of trustworthy `playlist_metrics` data on the pilot channel. **If Gap 9 isn't closed by the time 1B ships, the rollout-watch week is invalid.** Flagged below. |
| **Gap 10** (~12.5% transient DNS failures) | OPEN | Not a blocker — health scoring tolerates missing weeks (aggregates over 4 weeks). If Step B ships, the retry-with-backoff cheapest-fix from Gap 10 §Plan should land in the same migration. |

### 10.1 Exit-gate prerequisites (must be true before declaring 1B done)

- Gap 9 closed (OAuth promoted to "In production") OR a documented runbook to
  re-consent the pilot channel every 6 days during the rollout-watch week.
- Pilot channel has ≥4 weekly `playlist_metrics` rows for ≥1 playlist (otherwise
  scoring trivially returns `insufficient_data` for everything and the UI has
  nothing to render). Today, Phase 0 has been running on `UC8KjoL0Z9mTHKqB6gFutkJw`
  since 2026-06-17 — by the time 1B ships, this should be met for an active
  channel.

---

## 11. Open questions (to resolve before implementation)

1. **FK on `playlist_metrics.playlist_id`** — §3.3 recommends FK-free. Approve?
2. **Role classification — regex-only vs. LLM in Phase 1B?** §4.2 recommends
   regex-only. LLM-based role inference is more accurate but costs tokens and
   adds a Phase 1B failure mode. Approve regex-only for 1B?
3. **Health-score storage — denormalized columns on `playlists` vs. separate
   `playlist_health` history table?** §3.2 recommends denormalized + rely on
   `playlist_metrics` for history. Approve, or do we want score history from
   day one?
4. **Tier-2 scoring scope — split (Step A then Step B in same phase) or single
   ship?** §9.2 recommends split. Approve?
5. **Pilot channel — `UC8KjoL0Z9mTHKqB6gFutkJw` (recommended) vs.
   `UCr5-YUqBiW7PUmeAtxUWuRg` (Phase 0 probe channel)?** §8.2 recommends the
   former. Confirm?
6. **`PLAYLIST_HEALTH_ENABLED` naming** — should it be the broader
   `PLAYLIST_OPTIMIZER_ENABLED` from the PO config table (and stay narrow in
   meaning for 1B), or a distinct narrower flag (recommended in §8.1)?
7. **Recommendation thresholds (`HEALTH_REMOVE_PCTL=10`, `HEALTH_REVIVE_PCTL=33`)
   — defaults?** Pulled out of thin air; need at least one calibration pass on
   real pilot data. Should the first ship use stricter defaults (e.g. remove =
   bottom 5%) to limit false-positive prune recommendations?
8. **`GET /playlists/health` cached read — ship it or only ship the POST?**
   Recommended both in §6.3.
9. **`_daily_reconcile` → does it currently call `sync_playlists`?** If not, add
   the call in Phase 1B (otherwise the new sync columns never get backfilled
   automatically).
10. **Should the recommendation rationale include a link to the playlist on
    YouTube Studio?** Trivial to add; useful for the human-confirm flow. Not in
    PO spec but obvious UX.

---

## 12. Step-by-step implementation order

Each step is one IMPLEMENT → REVIEW pair, modelled on the Phase 0 working
method. Steps within a "track" are sequential; tracks are independent only
where noted.

### Track 1 — Schema + sync (must ship first)

**Step 1.1 — Migration.** Author the idempotent ALTER set from §3.1, §3.2, and
§8 (the new `channels.playlist_health_enabled` column). No data backfill — every
new column either has a default or is nullable.
*Review:* migration applies cleanly to a clone of prod; `playlists` rows pre-existing
the migration have `origin='inherited'`, all health columns NULL.

**Step 1.2 — Sync extensions.** Update `playlists_sync.sync_playlists` per §4.1
+ §4.2 (regex-based role inference). Verify `_daily_reconcile` calls it (Q9);
add the call if not.
*Review:* run sync on pilot channel; spot-check a handful of playlists for sane
role assignments; confirm `item_count` matches YouTube Studio counts.

### Track 2 — Health scoring (depends on Track 1)

**Step 2.1 — `app/playlist_health.py` skeleton + tier-1 scoring.** Implement
`score_channel(channel_id)` per §5.2–§5.4, tier-1 only. Write to the new
`health_*` columns. Add the config knobs from §5.5.
*Review:* run against pilot channel; eyeball the scores + recommendations; confirm
the gate behaviour (insufficient_data for low-starts playlists).

**Step 2.2 — Scheduler wiring.** Add daily UTC 06:00 cron entry in
`app/main.py`, gated per-channel on `playlist_health_enabled`.
*Review:* manually trigger; confirm log line + DB updates; confirm channels
without the flag are skipped silently.

### Track 3 — Endpoint + UI (depends on Track 2)

**Step 3.1 — `POST /channels/{id}/playlists/evaluate` + (optional) GET.**
Implement per §6. Recommend-only — no writes outside `playlists.health_*`.
*Review:* curl the endpoint on pilot channel; confirm response shape matches §6.2;
confirm no playlistItems / playlists.delete calls leak out.

**Step 3.2 — `channel.html` health card.** Implement per §7. Existing playlist
allocation UI untouched.
*Review:* visual review against the pilot channel; confirm sort order, badges,
rationale expansion; confirm allocation/proposals UI unchanged.

### Track 4 — Tier-2 (if approved per §9.2)

**Step 4.1 — `yt_analytics_video_traffic_source_playlist` in
`analytics_client.py`.** Single new function, mirror existing two.
*Review:* live probe on a known-good (video, playlist) pair; confirm response
shape and units before any storage decisions.

**Step 4.2 — Storage + poll integration.** Add the `video_traffic_source_playlist`
table per §9.3. Extend `metrics_poll` (or new `traffic_source_poll`) to populate
it. Apply Gap 10's cheapest-fix retry-with-backoff inline.
*Review:* one-day poll on pilot channel; confirm row counts within expectations;
confirm error-rate doesn't explode.

**Step 4.3 — Tier-2 in scoring.** Update `playlist_health.score_channel` to
read tier-2 and flip `tier_2_pending=false`. Update §6.2 response shape.
*Review:* re-run evaluate; confirm tier-2 numbers present and rationale updated.

### Track 5 — Rollout watch (the gate)

**Step 5.1 — Enable on pilot channel + observe for ~1 week.** Set
`playlist_health_enabled=true` on `UC8KjoL0Z9mTHKqB6gFutkJw` (or confirmed
pilot). Watch daily for 7 days: are recommendations stable, do scores move
sensibly, are there false-positive "remove" badges?
*Review:* declare exit gate met → widen to other channels. Or surface
calibration issues → tune thresholds (Q7) → re-watch.

### Estimated review checkpoints

- Tracks 1–3 form the minimum viable Phase 1B (recommend-only, tier-1 only). 5
  review gates.
- Track 4 adds 3 more if approved.
- Track 5 is the time-gated rollout, not a review gate per se — it's the spec's
  "one channel first, ~1 week" rule applied.

---

## Appendix — discipline checklist (carry into PRs)

- [ ] All migration ops `IF NOT EXISTS` / `IF EXISTS`.
- [ ] `DRY_RUN` not bypassed; scoring is a read of `playlist_metrics`, not a YouTube write.
- [ ] No `playlists.delete` / `playlistItems.insert` / `playlistItems.delete` calls
      anywhere in `playlist_health.py` or the evaluator endpoint.
- [ ] `PLAYLIST_HEALTH_ENABLED` gate honoured in both the scoring job and the
      endpoint.
- [ ] Gap 5 decision recorded in the migration header comment (matches Phase 0
      pattern in `20260610134419_metrics_tables.sql`).
- [ ] Tier-2 status (`tier_2_pending` flag) surfaced in every recommendation
      rationale.
- [ ] PR description repeats the PO §Sensor "web-only counts" caveat for every
      threshold introduced (per Gap 4 §"Where this constraint is enforced").
- [ ] Phase 1B exit-gate check: Gap 9 closed OR runbook in place for the
      rollout-watch week.
