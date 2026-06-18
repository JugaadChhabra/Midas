# Midas — Build Plan

Phase-wise sequencing for the two specs:

- **CIL** — `CONTINUOUS_IMPROVEMENT_LOOP.md` (Loops 0–3: the metadata-audit learning loop)
- **PO** — `PLAYLIST_OPTIMIZATION.md` (the playlist optimizer, a second action type on the same loops)

Those docs hold the detail (schema, prompts, metric names, config). **This doc is only the
sequencing layer** — what to build in what order, what gates what, and what to build while
the slow clock runs. It supersedes the original `plan.md` (the Postgres/React/Celery sketch,
now stale).

---

## The three forces that set the order

1. **Dependency spine.** Loop 0 (the sensor) gates *everything* in both docs — metadata and
   playlists alike. No measurement → no learning → no loop. It is built first and in full.
2. **Slow clock.** A metadata outcome takes ~3 weeks; a playlist outcome ~5. Outcomes can't be
   rushed, so the plan **builds no-outcome-dependency work during the waits** rather than
   sitting idle. Phases are ordered by *dependency*, not by wall-clock — later phases' build
   work overlaps earlier phases' measurement windows.
3. **Rollout discipline.** Every phase ships to **one channel first, ~1 week of watching, then
   widens.** Same cadence as the thumbnail rollout. This is a gate, not a suggestion.

---

## Preconditions (already in place — do not rebuild)

- Per-channel OAuth + stored refresh tokens; credentials loaded per channel.
- Apply path that captures a before-state snapshot + apply-time stats baseline (`*_at_apply`).
- Autopilot tick loop, quota tracker (Data API units + safety buffer), `DRY_RUN`.
- `_build_user_block()` with the load-bearing `default_language` rule.
- Embeddings store + the existing similarity playlist recommender (demoted to candidate
  generation in PO).
- Per-channel feature-flag pattern (the thumbnail flags) reused for every gate below.

---

## Phase map

| Phase | Theme | Key outputs | Gate before advancing |
|---|---|---|---|
| **0** | Sensor foundation (shared gate) | analytics scope + re-consent, `analytics_client`, `video_metrics` + `playlist_metrics`, `metrics_poll` | One channel returns real CTR + playlist metrics for ≥1 week |
| **1** | Control loops — diagnostic & safe | video Loop 1 (measure-only, auto-revert OFF), playlist inventory + health + recommend-only prune, outcome rollups | Feedback visibly flowing; no destructive/auto actions |
| **2** | Construction & interventions (built during the wait) | competitor-research pipeline, playlist construction + intervention lifecycle + self-eval | Optimizer creating + measuring playlists on one channel |
| **3** | Memory — the playbooks (Loop 2) | metadata playbook, playlist playbook, injection into prompt/construction | A channel crosses its cold-start floor and the playbook demonstrably shifts suggestions |
| **4** | Meta loops (Loop 3) | `audit_strategies`, offline eval harness, champion/challenger | A challenger reaches the promotion bar on real outcomes |

> Phases 1 and 2 **overlap in time**: Phase 2 is the build work you do *while* Phase 1's
> outcomes accrue. Phase 3 only becomes meaningful months in, when enough outcomes exist.

---

## Phase 0 — Sensor foundation (shared gate)

**Goal:** real per-video and per-playlist outcome data flowing into storage. Nothing
downstream — metadata or playlist — works without this.

**Ships:**
- Add `yt-analytics.readonly` scope to `/auth/login`; per-channel re-consent flow;
  `channels.analytics_authorized` flag; "Reconnect for analytics" UI prompt. *(CIL §0.1)*
- `app/analytics_client.py` wrapping `youtubeAnalytics.reports.query`. *(CIL §0.2)*
- **Live probe before abstracting:** confirm the video CTR metric names
  (`videoThumbnailImpressions`, `videoThumbnailImpressionsClickRate`, added 2026-01-15) **and**
  the playlist report shape (`playlistStarts`, `viewsPerPlaylistStart`, `averageTimeInPlaylist`,
  plus the `isCurated` deprecation status) with one real query each. *(CIL §0.2 / PO §Sensor)*
- `video_metrics` table + `playlist_metrics` table. *(CIL §0.3 / PO §Sensor)*
- `metrics_poll` scheduler job, daily, pulling **both** video and playlist windows; skips
  channels where `analytics_authorized = false`; respects the ~2-day freshness lag. *(CIL §0.4)*

**Why both sensors here:** the scope, re-consent, client, and poll job are shared. Building
video + playlist sensing in one pass avoids touching the same code twice.

**Depends on:** preconditions only.
**Exit:** one re-consented channel returns trustworthy CTR and playlist metrics for ≥1 week.

---

## Phase 1 — Control loops (diagnostic & safe)

**Goal:** start the feedback flowing on both action types, with zero automated or destructive
behaviour. Two parallel tracks, both consuming the Phase 0 sensor, neither needing accrued
outcomes yet.

**1A — Metadata per-video loop (minimal slice).** *(CIL §1.1–1.5, §1.8)*
- `measurement_status` + related columns on `audits`.
- Pre-change CTR baseline captured at apply (`video_metrics.is_pre_change`); dormant videos →
  `not_applicable`.
- `measurement_eval` job: after `MEASUREMENT_WINDOW_DAYS` (21) and `MIN_IMPRESSIONS` (500),
  write `win`/`neutral`/`regression`.
- `AUTO_REVERT_ON_REGRESSION = false` — regressions surface for human review only.
- Manual `revert` / `redo` / `measurement` endpoints; `/channels/{id}/outcomes` rollup.

**1B — Playlist inventory + health (recommend-only).** *(PO §Control loop, requirement 1)*
- `playlists` table; sync existing playlists; classify role where inferable.
- Score each playlist on session contribution (`averageTimeInPlaylist`, `viewsPerPlaylistStart`,
  playlist-source views to members), gated on `MIN_PLAYLIST_STARTS`.
- `POST /channels/{id}/playlists/evaluate` → revive/remove **recommendations only**. No
  `delete`, no `playlistItems` writes yet.

**Depends on:** Phase 0.
**Exit:** metadata outcomes are being written; playlist health scores + prune recommendations
render for human review. Auto-revert and auto-delete both still off.

---

## Phase 2 — Construction & interventions (built during the wait)

**Goal:** the optimizer starts *acting* on playlists and measuring itself — built while Phase 1's
metadata outcomes accrue. None of this needs accrued outcomes, so it parallelizes the wait.

**2A — Competitor research pipeline.** *(PO §Competitor research, requirement 2)*
- Autonomous, **scheduled** (`COMPETITOR_REFRESH_DAYS = 90`), cached, under its own
  `COMPETITOR_DISCOVERY_QUOTA_BUDGET`. Never rides the per-video tick.
- Stages: characterize niche → discover by who-ranks (`search.list` → `channels.list` filter) →
  LLM fit/language filter → harvest public structure → distill → `playlist_competitor_reference_json`.
- API-only, no scraping. Output is **inferred structure, not measurement** — a hypothesis
  generator, validated later by 2C.

**2B — Playlist construction + intervention lifecycle.** *(PO §Construction, §Control loop)*
- `playlist_interventions` table; every create/add/reorder/rename stamped as an intervention
  with a pre-change baseline.
- Construction pipeline: embeddings (recall) → LLM re-rank for session continuation →
  ordering/entry-point → optimized playlist title/description under the `default_language` rule.
- Behind `PLAYLIST_OPTIMIZER_ENABLED`, **one channel first**; `MAX_NEW_PLAYLISTS_PER_WINDOW`
  caps flooding. `delete` stays **recommend-only**, human-confirmed (`PLAYLIST_AUTO_DELETE = false`).

**2C — Playlist self-eval.** *(PO §Control loop, requirement 3 — the keystone)*
- A `measurement_eval` analog for `playlist_interventions`: after
  `PLAYLIST_MEASUREMENT_WINDOW_DAYS` (35) and `MIN_PLAYLIST_STARTS`, write
  `win`/`neutral`/`regression` → keep / revise / recommend-prune.
- This is what stops the dead-playlist treadmill: created playlists are judged, not just made.

**Depends on:** Phase 0 (sensor) + Phase 1B (`playlists` table). Independent of Phase 1A's outcomes.
**Exit:** on one channel, the optimizer builds playlists, stamps them, and the self-eval job is
scheduled to grade them after the window.

---

## Phase 3 — Memory: the playbooks (Loop 2)

**Goal:** the first point the system visibly *gets smarter* — suggestions and playlist
construction start regressing toward what's measurably worked on each channel. Gated on accrued
outcomes, so this lands months in, by design.

**3A — Metadata playbook.** *(CIL §2)*
- `app/playbook.py` → `channels.playbook_json`; LLM distillation of `win`/`regression` outcomes.
- Cold-start floor `MIN_OUTCOMES_FOR_PLAYBOOK` (15); lazy rebuild on `PLAYBOOK_REFRESH_DELTA`.
- Inject "WHAT WORKS ON THIS CHANNEL" + top-CTR exemplars into `_build_user_block()`.

**3B — Playlist playbook.** *(PO §Memory)*
- `channels.playlist_playbook_json` distilled from playlist outcomes; injected into the 2B
  construction pipeline. Below the floor, fall back to the competitor reference + generic logic.
- Playbook (measured) overrides competitor reference (inferred) on conflict.

**Depends on:** outcomes accrued in Phases 1A (metadata) and 2C (playlist). Metadata matures
first; playlist playbook later (slower clock).
**Exit:** a channel past its floor shows a playbook that demonstrably changes suggestions vs. the
generic prompt.

---

## Phase 4 — Meta loops (Loop 3)

**Goal:** make the audit/construction *strategy* itself testable, so a new prompt/model/logic must
prove it beats the incumbent on real outcomes before fleet-wide rollout. Last, because it needs
enough outcome volume to tell strategies apart.

**Ships:** *(CIL §3, PO §Meta loop)*
- `audit_strategies` table; stamp every audit **and** playlist intervention with `strategy_version`
  (reuse the table; `playlist:` prefix for construction strategies).
- Offline eval harness (`app/eval.py`): pairwise LLM-as-judge with a **different-family** judge +
  backtest sanity check. Gates quality only — can't see CTR.
- Online champion/challenger: **one challenger at a time**, routed by id hash; promote on
  `PROMOTION_MARGIN` with `MIN_OUTCOMES_FOR_PROMOTION` per arm. Metadata strategies first, then
  playlist construction strategies.

**Depends on:** Phases 3A/3B (and the outcome volume they imply).
**Exit:** a challenger clears the promotion bar on measured outcomes and is promoted.

---

## Cross-cutting rules (apply in every phase)

- **The three learning conditions are non-negotiable:** honest measurement (Phase 0 reads real
  CTR/session data, never vanity counts), a closed loop (outcomes feed behaviour, not just a
  dashboard), and preserved exploration (Phase 4 challengers + divergent candidates). Drop any one
  and the system degrades to automation.
- **Human gates:** auto-revert (metadata) and auto-delete (playlist) default **off**; both are
  irreversible-leaning or destructive and stay human-confirmed until explicitly trusted per channel.
- **Quota:** Analytics polling is a separate pool (free against the Data budget). Data API writes —
  `videos.update` (50), `playlistItems.insert` (50), `playlists.delete` (50), `search.list` (100) —
  all share the 10k/day budget through the existing quota gate. Competitor discovery runs under its
  own sub-budget.
- **`default_language` survives everything** — audit prompts, playbook distillation, playlist
  metadata, competitor niche queries.
- **One channel first, ~1 week, then widen** — every phase, no exceptions.

---

## Open sequencing questions

- **Phase 0 probe outcomes.** If the playlist report shape has shifted (`isCurated` deprecation) or
  metric names differ, 0 absorbs the fix before any abstraction is written.
- **Phase 1A vs 1B ordering within the phase.** They're independent; build whichever channel is
  re-consented first. 1B (recommend-only) is lower-risk and a good warm-up.
- **When to flip a human gate.** Auto-revert / auto-delete per-channel only after a phase's
  recommendations have been trustworthy for a sustained window — decide per channel, not globally.
- **Phase 4 timing.** Don't start champion/challenger until pooled outcome volume across channels
  can actually separate two strategies; premature meta-loop work just adds noise.
