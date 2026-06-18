# Midas — Playlist Optimizer

A per-channel subsystem that **builds, prunes, and continuously improves YouTube
playlists** as a discovery lever — and learns which playlist strategies actually move
session watch time on each channel. It is **not** a new loop. It is a second
*intervention type* riding the substrate spec'd in `CONTINUOUS_IMPROVEMENT_LOOP.md`
(Loop 0 sensor → Loop 1 control → Loop 2 memory → Loop 3 meta): playlist actions are
measured, kept/revised/pruned, distilled into a playbook, and A/B-tested as strategies,
exactly like metadata audits.

> The value test for this subsystem is not "does it create playlists" — automation does
> that. It is "does it create *fewer dead playlists over time* because it remembers what
> worked." If it doesn't learn, it's not worth building.

---

## Why playlists (the mechanism that shapes every decision)

Playlists boost discovery through **session watch time**, not organization. Autoplay
chains views into longer sessions, and session watch time is one of the strongest
ranking signals; playlists are also independent discovery surfaces that rank in search.
YouTube evaluates a playlist on **playlist starts, completion rate, cross-video
retention (how well each video hands off to the next), and average time in playlist** —
*not* topical tidiness.

Consequences that drive the design:

1. **Similarity is candidate-generation, not the objective.** Cosine similarity answers
   "what's about the same thing"; the algorithm rewards "what, played next, keeps the
   viewer watching." Two near-identical videos can be redundant and *tank* completion. We
   keep embeddings for recall and re-rank for session continuation.
2. **Order and entry point are first-class.** Position 1 is the playlist's front door and
   takes disproportionate traffic. Strong opener → momentum-building handoffs.
3. **Playlists don't create demand from nothing.** Like metadata, they *extend* existing
   sessions and add surfaces; the lift is leverage on traffic the videos already get.
   Incoherent or badly-sequenced playlists *hurt* (low completion is a negative signal),
   so more playlists is not better.

---

## The three learning conditions (first-class constraints)

These are the difference between a learning subsystem and an expensive automation. Every
section below is designed to satisfy them; if a change would violate one, it's wrong.

1. **Honest measurement.** Every playlist action is judged on real session metrics from
   the Analytics API (`playlistStarts`, `averageTimeInPlaylist`, `viewsPerPlaylistStart`),
   never on vanity counts. No measurement → no learning.
2. **Closed loop.** Outcomes feed back into behaviour (the playbook), not just a
   dashboard. Data the system doesn't act on is a log, not experience.
3. **Preserved exploration.** The optimizer must keep trying materially new playlist
   angles (Loop 3 challengers, divergent candidates). If it only imitates past winners it
   converges to a local optimum and silently becomes automation. This is the condition
   most likely to be lost by accident.

---

## How the three requirements map onto the loops

| Requirement | Mechanism | Loops used |
|---|---|---|
| **1. Prune dead/non-working existing playlists** | Score each playlist on session contribution; revive or (human-confirmed) remove | Loop 0 + Loop 1 |
| **2. Learn what works for bigger channels in the space** | Autonomous competitor-research pipeline → curated reference feeding construction | Curated reference (style-profile analog) |
| **3. Self-evaluate created playlists** | Stamp optimizer-created playlists, measure after a window, learn | Loop 1 + Loop 2 |

Requirement 2 produces a **curated, inferred** reference (what competitors *appear* to
do); requirements 1 and 3 produce **measured** truth (what actually worked here). Kept
distinct, like `style_profile_json` vs `playbook_json`.

---

## Sensor extension (Loop 0, for playlists)

Reuses the analytics scope and re-consent already required by Loop 0
(`yt-analytics.readonly`). No new scope.

### Metrics

Per-playlist reports via `youtubeAnalytics.reports.query` with `dimensions=playlist`:

- `playlistStarts` — times viewers initiated the playlist
- `viewsPerPlaylistStart` — avg videos watched per start
- `averageTimeInPlaylist` — avg minutes a viewer spent in the playlist after starting
- `playlistViews`, `playlistEstimatedMinutesWatched`

Plus, on member videos, the **traffic-source = `PLAYLIST`** breakdown (how much of a
video's reach the playlist actually drives).

### Storage — `playlist_metrics` (time series, mirrors `video_metrics`)

```sql
CREATE TABLE playlist_metrics (
    id BIGSERIAL PRIMARY KEY,
    playlist_id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(id),
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    playlist_starts BIGINT,
    views_per_playlist_start FLOAT,
    avg_time_in_playlist_min FLOAT,
    playlist_views BIGINT,
    playlist_est_minutes_watched BIGINT,
    is_pre_change BOOLEAN DEFAULT FALSE,   -- baseline captured before an intervention
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (playlist_id, window_start, window_end)
);
```

### Gotchas to encode

- **Web-only.** `playlistStarts`, `viewsPerPlaylistStart`, and `averageTimeInPlaylist`
  only count playlist views **on the web** — mobile/TV are excluded, so these undercount.
  Judge on trends/relative comparison, not absolute totals.
- **`isCurated` deprecation.** Some playlist reports historically required the `isCurated`
  filter, which Google has flagged for deprecation. **Verify the current report shape with
  one live `reports.query` before building the abstraction** (same probe discipline as
  Loop 0's CTR metrics).
- **Min-data + age gate.** A young playlist has no judgeable data. Don't evaluate until it
  has accrued `>= MIN_PLAYLIST_STARTS` over a window of at least
  `PLAYLIST_MEASUREMENT_WINDOW_DAYS`.

---

## Competitor research pipeline (autonomous, scheduled)

Zero human input. A **bounded, scheduled pipeline** (not an open-ended agent loop):
deterministic, debuggable, quota-safe, and it reliably runs itself without supervision.

**Stages:**

1. **Characterize the niche** from the channel's own content (transcripts, embeddings,
   metadata) via the LLM → a niche descriptor + the defining search queries, in the
   channel's `default_language`.
2. **Discover competitors by who actually ranks.** Run the niche queries through
   `search.list`, collect the channel IDs behind top-ranking videos (the channels winning
   your queries *are* the competitive set). Batch `channels.list` to pull
   subscriber/view counts; keep those `>= COMPETITOR_MIN_SUBSCRIBER_MULTIPLE` of the
   target and recently active.
3. **Filter for genuine fit.** An LLM pass verifies each candidate is in-niche and
   language-matched before harvesting — drops reuploaders, tangential channels, wrong
   language. This QC stage keeps the reference clean.
4. **Harvest public structure.** `playlists.list` + `playlistItems.list` capture themes,
   naming conventions, role mix (series / topic / funnel), length, sequencing, and
   member view counts.
5. **Distill** into a per-niche competitor reference via `chat_json`.

### Storage

```sql
ALTER TABLE channels
  ADD COLUMN IF NOT EXISTS playlist_competitor_reference_json JSONB,
  ADD COLUMN IF NOT EXISTS playlist_competitor_built_at TIMESTAMPTZ;
```

### Operating rules

- **Quota.** `search.list` costs **100 units** against the shared 10k/day Data API budget.
  Discovery runs as a **periodic background job** (`COMPETITOR_REFRESH_DAYS`, default 90 —
  competitive sets don't shift weekly), under its own daily sub-budget
  (`COMPETITOR_DISCOVERY_QUOTA_BUDGET`), aggressively cached. It never rides the per-video
  tick and never starves audit/apply quota.
- **ToS.** Official API over public data only. **No site scraping or unofficial
  endpoints** — it risks the whole project and the API exposes all the public structure
  that exists.
- **Honest boundary.** Competitors' session metrics (`playlistStarts`, completion) are
  **owner-only** and unreadable. This reference is **structural inference from public
  signals**, not measurement. It is a *hypothesis generator*; the self-eval loop
  (below) is what validates whether an imitated pattern actually works here.

---

## Playlist construction

### Role taxonomy (determines construction logic)

| Role | Goal | Ordering logic |
|---|---|---|
| **Series / sequential** | Binge/session via narrative or curriculum order | Fixed by logic/chronology |
| **Topic cluster** | Search/browse discoverability; the playlist is its own SEO entity | Strong-first, then relevance |
| **Funnel / "start here"** | Route new viewers into the channel | Strongest, most accessible video first |

### Pipeline

1. **Candidate generation** — embeddings/similarity (existing system) for recall: the pool
   of plausibly-related videos.
2. **Re-rank by session objective** — topical fit × candidate retention strength ×
   complementarity (penalize redundancy, reward natural "next-step" relationships). LLM
   does the editorial judgment embeddings can't: *next* video vs merely *similar* video.
3. **Order + entry point** — sequence to maximize the cross-video retention chain: strong
   opener, smooth handoffs, no retention cliffs. Position 1 chosen deliberately.
4. **Playlist metadata** — generate optimized title + description (search-indexed SEO
   surfaces) under the `default_language` rule. A ranking playlist pulls traffic to every
   member.

The competitor reference and the measured playbook both condition this pipeline; the
playbook (measured) wins on conflict.

---

## Control loop (Loop 1, for playlist interventions)

Each action the optimizer takes is a measurable intervention.

### Tracked entities

```sql
CREATE TABLE playlists (
    id TEXT PRIMARY KEY,                       -- YouTube playlist id
    channel_id TEXT NOT NULL REFERENCES channels(id),
    title TEXT,
    description TEXT,
    role TEXT,                                 -- series | topic_cluster | funnel | inherited | unknown
    origin TEXT DEFAULT 'inherited',           -- inherited | optimizer_created
    strategy_version TEXT,                     -- construction strategy that built it (Loop 3)
    item_count INT,
    created_by_optimizer_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ
);

CREATE TABLE playlist_interventions (
    id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(id),
    playlist_id TEXT,                          -- null until a create succeeds
    action TEXT NOT NULL,                      -- create | add_video | reorder | rename | prune_recommend | delete
    payload JSONB,                             -- video ids, positions, new title/desc, rationale
    before_state JSONB,                        -- for reversible actions
    strategy_version TEXT,
    status TEXT DEFAULT 'pending',             -- pending | applied | awaiting_confirm | failed
    measurement_status TEXT DEFAULT 'not_applicable',
      -- not_applicable | awaiting_window | measuring | win | neutral | regression
    measurement_started_at TIMESTAMPTZ,
    measurement_result JSONB,
    outcome_decision TEXT DEFAULT 'none',      -- none | kept | revised | pruned
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Lifecycle

```
applied ─▶ awaiting_window ─▶ measuring ─┬─▶ win        ─▶ kept
                                         ├─▶ neutral    ─▶ kept (left as-is)
                                         └─▶ regression ─▶ revised  ─▶ (re-construct)
                                                          └─▶ prune_recommend ─▶ [human confirm] ─▶ delete
```

- **Baseline at apply.** Snapshot the playlist's pre-change `playlist_metrics`
  (`is_pre_change=true`) and the member videos' traffic-source mix. New playlists baseline
  from zero.
- **Window.** Longer than the 21-day video window — playlists accrue session data more
  slowly and depend on members getting impressions. Default `PLAYLIST_MEASUREMENT_WINDOW_DAYS = 35`,
  gated on `MIN_PLAYLIST_STARTS`.
- **Decision policy (critic).** Compare post-change vs pre-change session metrics
  (primary: `averageTimeInPlaylist` and `viewsPerPlaylistStart`; secondary: playlist-source
  views to members). Win → keep; neutral → keep; regression → revise (re-order / re-theme /
  swap members) or, if inert, recommend prune.
- **Prune = human-confirmed.** Deletion is **irreversible** via the API, so the optimizer
  only ever *recommends* deletion; a human confirms (`PLAYLIST_AUTO_DELETE` defaults
  **false**). Prefer revive over delete: an inert playlist is clutter, not active harm.

### Attribution caveat

A video usually belongs to several playlists, so a session lift can't be cleanly
attributed to one. v1 treats playlist membership coarsely (bundle-level, consistent with
the metadata-audit decision) and learns at the playlist level, not the per-membership
level. Flagged as an open question.

---

## Memory (Loop 2, for playlists)

```sql
ALTER TABLE channels
  ADD COLUMN IF NOT EXISTS playlist_playbook_json JSONB,
  ADD COLUMN IF NOT EXISTS playlist_playbook_built_at TIMESTAMPTZ;
```

Distilled from measured intervention outcomes (`win`/`regression`), the **playlist
playbook** records what actually drove sessions on *this* channel: which roles work,
effective length bands, opener characteristics, sequencing patterns, naming patterns tied
to playlist-start lift. Injected into the construction pipeline.

- **Distinct from the competitor reference.** Playbook = measured reality (what got
  watched); competitor reference = curated inference (what bigger channels appear to do).
  The playbook overrides on conflict.
- **Cold-start gate.** Below a floor of measured playlist outcomes, no playbook injection —
  fall back to competitor reference + generic construction. Because each outcome takes ~5
  weeks, the playbook matures over months. Expected, not a bug.
- **This requirement-3 loop is what stops the dead-playlist treadmill:** the optimizer
  won't keep repeating a construction pattern it can measure didn't work.

---

## Meta loop (Loop 3, for playlists)

Construction logic (candidate ranking + ordering + role heuristics + which reference is
weighted) is a **strategy**, versioned in `audit_strategies` (reuse the table; tag with a
`playlist:` prefix). Champion/challenger one strategy at a time, routed by playlist-id
hash, compared on measured outcomes once enough accrue.

- **This is where exploration is protected** (learning condition 3): a challenger can
  deliberately encode divergence — new roles, unfamiliar sequencing, looser playbook
  adherence — and you *measure* whether the exploration pays. Without it, Loop 2 converges
  and the subsystem ossifies.

---

## Data model summary

- **New tables:** `playlist_metrics`, `playlists`, `playlist_interventions`.
- **`channels` additions:** `playlist_competitor_reference_json`,
  `playlist_competitor_built_at`, `playlist_playbook_json`, `playlist_playbook_built_at`,
  `playlist_optimizer_enabled`.
- **Reused:** `audit_strategies` (Loop 3), the `yt-analytics.readonly` scope (Loop 0),
  the quota tracker, the embeddings store.

---

## Config / flags (`config.py`)

| Setting | Default | Notes |
|---|---|---|
| `PLAYLIST_OPTIMIZER_ENABLED` | per-channel | gate the whole subsystem (like thumbnail flags) |
| `PLAYLIST_MEASUREMENT_WINDOW_DAYS` | 35 | longer than the 21-day video window |
| `MIN_PLAYLIST_STARTS` | 50 | statistical floor before judging a playlist |
| `COMPETITOR_REFRESH_DAYS` | 90 | competitor research cadence |
| `COMPETITOR_DISCOVERY_QUOTA_BUDGET` | 2000 | daily unit cap for `search.list` discovery |
| `COMPETITOR_MIN_SUBSCRIBER_MULTIPLE` | 3 | "bigger than me" threshold |
| `MAX_NEW_PLAYLISTS_PER_WINDOW` | 3 | per channel; prevents flooding |
| `PLAYLIST_AUTO_DELETE` | **false** | deletion is human-confirmed (irreversible) |
| `PLAYLIST_CHALLENGER_PCT` | 0.20 | construction-strategy A/B traffic share |

### Quota costs (Data API, shared 10k/day pool)

| Operation | Units |
|---|---|
| `search.list` | 100 |
| `playlists.insert` / `update` / `delete` | 50 |
| `playlistItems.insert` | 50 |
| `playlists.list` / `playlistItems.list` / `channels.list` | 1 (per page / per 50 ids) |

Analytics polling is a separate quota pool (free against the above).

---

## Endpoints

- `GET /channels/{id}/playlists` — inventory + per-playlist health (session metrics).
- `POST /channels/{id}/playlists/evaluate` — run the prune evaluation; returns
  revive/remove recommendations (no destructive action).
- `POST /channels/{id}/playlists/build` — run the construction pipeline (or via autopilot).
- `GET /channels/{id}/playlist-competitor-reference` · `POST .../rebuild`.
- `GET /channels/{id}/playlist-playbook`.
- `GET /playlist-interventions/{id}/measurement`.
- `POST /playlist-interventions/{id}/confirm-delete` — the one human gate.

---

## Decisions / non-obvious items to remember

1. **Second action type, not a fifth loop.** Playlist interventions reuse the Loop 0–3
   substrate wholesale.
2. **Similarity is recall, session continuation is the objective.** The existing
   recommender is demoted to candidate generation; re-ranking and ordering carry the work.
3. **Competitor reference is inferred, not measured.** Owner-only analytics means we never
   see competitors' real session data. It generates hypotheses; the self-eval loop
   validates them. Kept distinct from the measured playbook.
4. **Delete is human-confirmed and irreversible.** Prefer revive over delete; an inert
   playlist is clutter, not harm.
5. **Judge on contribution metrics, not vanity counts.** `playlistStarts`,
   `averageTimeInPlaylist`, `viewsPerPlaylistStart` — and remember they're web-only.
6. **Discovery is autonomous but bounded.** Scheduled, cached, quota-capped; finds
   competitors by who ranks for the niche, not by a human seed list.
7. **Exploration is protected by design (Loop 3).** This is the condition that keeps the
   subsystem learning instead of ossifying into automation.
8. **Longer clock than metadata.** ~5-week windows; a channel's playlist playbook matures
   over months. Don't expect fast movement.

## Open questions (resolve before/while building)

- **Measurement window length** (35 days is a starting guess; tune against observed
  data-settling).
- **Multi-membership attribution** — coarse/bundle in v1; revisit if per-membership causal
  attribution becomes necessary.
- **Competitor discovery sourcing** — video-search-derived channel set (recommended) vs
  channel-search; quota tradeoff and noise profile differ.
- **`isCurated` deprecation** — confirm the replacement report shape with a live probe.
- **Auto-delete after N confirmed-dead windows?** — or keep the human gate permanently.
  Recommend permanent human gate for v1 (irreversibility).

---

## Build order (sequenced; rides the existing loop rollout)

1. **Sensor extension** — `playlist_metrics` + a poll step on the existing `metrics_poll`
   job. Depends only on Loop 0's analytics scope being live.
2. **Inventory + health scoring** — `playlists` table, sync existing playlists, score them,
   ship the **recommend-only** prune evaluation (requirement 1, no destructive action yet).
3. **Competitor research pipeline** — scheduled, cached, quota-bounded (requirement 2).
4. **Construction pipeline** — candidates → re-rank → order → metadata, behind the
   per-channel flag, **one channel first** (requirement 1's revive path + new builds).
5. **Control loop + self-eval** — interventions measured, kept/revised/pruned; the playlist
   playbook starts distilling (requirement 3 — the keystone).
6. **Meta loop** — champion/challenger on construction strategies, once enough outcomes
   accrue to tell strategies apart.

Roll out **one channel first, ~1 week of watching, then widen** — same cadence as every
other loop.
