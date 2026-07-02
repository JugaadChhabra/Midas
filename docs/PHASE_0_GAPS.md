# Phase 0 — Gaps Ledger

Living record of every place the **shipped Phase 0** intentionally departs from
the authoritative specs (`plan.md` §Phase 0, `CONTINUOUS_IMPROVEMENT_LOOP.md`
§0.x, `PLAYLIST_OPTIMIZATION.md` §Sensor). Each gap was surfaced by the live
probe on 2026-06-10 against channel `UCr5-YUqBiW7PUmeAtxUWuRg` (re-consented
with `yt-analytics.readonly`).

**Update rule:** every change to Phase 0 that touches the analytics surface
either (a) closes a gap here, or (b) adds a new row. No silent drift.

---

## Gap 1 — No on-demand CTR/impressions (Reporting API deferred) — **CLOSING (implementation shipped 2026-07-02; exit gate pending)**

### Spec said
> CIL §0.2: "Per-video reach + retention for a date window … metrics include
> `videoThumbnailImpressions`, `videoThumbnailImpressionsClickRate` … added to
> the Analytics API on 2026-01-15."
>
> CIL §0.3: `video_metrics.impressions BIGINT`, `video_metrics.ctr FLOAT`.
>
> Phase 0 exit gate: "one re-consented channel returns trustworthy CTR and
> playlist metrics for ≥1 week."

### Live probe found
`videoThumbnailImpressions` and `videoThumbnailImpressionsClickRate` (and the
"official-doc" aliases `impressions` / `impressionsClickThroughRate`) **are
not available via `youtubeAnalytics.v2.reports.query`** — neither at
`dimensions=video`, `dimensions=day`, nor channel-level (no dimensions).
Every bisect (probe queries 1b–1f) returned `400 badRequest`. These metrics
appear only via the **YouTube Reporting API** (bulk daily CSV report jobs),
which has a completely different shape: scheduled report jobs, GCS-style
download URLs, and per-day rows instead of windowed aggregates.

### What shipped (Option B from the 2026-06-10 decision)
- `app/analytics_client.py` requests **views + retention only** for videos.
- `video_metrics.impressions` and `video_metrics.ctr` exist as **nullable**
  columns so a future Reporting-API ingestion can backfill without `ALTER`.
- `app/metrics_poll.py` leaves both columns `NULL`.
- This file records the deferral.

### What this blocks
- **CIL Loop 1 (`measurement_eval`)** — relies on CTR delta vs. a pre-change
  CTR window. **Cannot land until CTR data is present.**
- Phase 1A (metadata per-video loop) — same reason.
- The Phase 0 exit gate's "trustworthy CTR" half — gate is shipped half-met
  (retention + playlist OK, CTR pending).

### What this does NOT block
- **Phase 1B** (playlist inventory + health, recommend-only). It scores on
  `playlistStarts` / `viewsPerPlaylistStart` / `averageTimeInPlaylist` —
  all of which the on-demand API does return. Phase 1B can start the
  moment Phase 0 settles.
- Phase 0 retention/views data for trend-watching on the one re-consented
  channel during the rollout-discipline week.

### Status as of 2026-06-18
**Phase 0.5 in flight — paused for first CSV.** The
`scripts/probe_reporting.py` probe ran successfully after the user enabled
the YouTube Reporting API in Google Cloud. Findings:

- The reach/impressions/CTR report type slug is **`channel_reach_basic_a1`**
  ("Reach basic"). The `_basic_a3` family is views/watch-time only — no
  impressions. The "reach" suffix is the right convention.
- 20 system-managed report types are available. None of the `playlist_*`
  types carry CTR.
- A reporting job was created for `UC8KjoL0Z9mTHKqB6gFutkJw`:
  - Job ID: `724b9fa7-ab5c-4c21-b45a-be936112bef1`
  - Type: `channel_reach_basic_a1`
  - Name: `midas-reach`
  - Created: `2026-06-18T07:38:51Z`
- `jobs.reports.list` returns empty until 24–48h after job creation; reports
  only exist for dates AFTER the job's create-time. **First CSV available
  no earlier than 2026-06-19; realistically 2026-06-20.**

### Status as of 2026-07-02 — CSV probed, ingestion shipped

Gap 9 was resolved (OAuth app now **In production**; all three channels
re-consented with durable tokens), unblocking the paused CSV probe. The
2026-07-02 probe downloaded report `20159147398` from the Punjabi job and
verified the real shape:

- **CSV columns (exact):**
  `date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr`
  — `date` is `YYYYMMDD`; `ctr` is a **fraction** (0.1538 = 15.38%); one row
  per video with ≥1 impression that day (zero-impression videos absent);
  1,310 rows for one day on the Punjabi channel.
- **Reports arrive erratically and out of order** — a report for data-day
  2026-05-27 was generated on 2026-06-28. Never assume ordering.
- **Historical backfill is real**: YouTube generated reports for data-days
  BEFORE job creation (2026-05-27 < 2026-06-18), contrary to the earlier
  "dates after create-time only" reading. The 60-day-loss worry above was
  overly pessimistic.

**Storage decision (flips the earlier lean, documented per no-silent-drift):**
raw daily table `video_reach_daily` (UNIQUE video_id+date) is the source of
truth, with `video_metrics.impressions`/`ctr` **derived** from it — filled
only for windows whose every data-day is covered by an ingested report
(ledger table `reporting_reports_ingested`). Rationale: (a) out-of-order
report arrival makes direct window upserts un-certifiable; (b) Loop 1's
baseline capture (CIL §1.2) needs arbitrary trailing windows anchored at
apply time, which only daily grain can serve.

**What shipped (Phase 0.5 implementation):**
- Migration `20260702174235_phase05_reporting_reach.sql` —
  `video_reach_daily` + `reporting_reports_ingested`.
- `app/reporting_client.py` — auth handle (mirrors analytics_client; same
  scope/gates), `ensure_reach_job` (find-or-create; create respects
  DRY_RUN), paginated report listing, CSV download + header-asserting parse.
- `app/reporting_poll.py` — daily ingest + fully-covered-window backfill
  (weighted CTR = Σclicks/Σimpressions). Cron UTC 06:00 in `app/main.py`
  (after metrics_poll 05:00, before playlist_health 07:00).
- `scripts/create_reporting_job.py` — human-gated job creation for DRY_RUN
  environments.

**Reach jobs now exist for all three channels:**
- Punjabi `UC8KjoL0Z9mTHKqB6gFutkJw`: `724b9fa7-ab5c-4c21-b45a-be936112bef1` (2026-06-18)
- Marathi `UCr5-YUqBiW7PUmeAtxUWuRg`: `05509a11-8c06-4c55-8978-13995bd1ca1f` (2026-06-18)
- Hindi `UCR9qQMyP86aSt-1VgaMg7UA`: `fc919d9c-3fb1-4242-b388-ea41bb3976f1` (2026-07-02)

**Remaining to fully close:** apply the migration, first live `poll_reporting`
run, then the 0.5 exit gate — ≥1 week of trustworthy CTR on one channel.

### Plan to close
Tagged as **Phase 0.5 — Reporting API ingestion** (to be sequenced before
Phase 1A). Sketch only — not a built thing yet:

1. Add a separate scheduler job, `reporting_api_poll`, daily, that:
   - Creates the report job once per channel (`creator_basic_a2` or similar
     — needs another live probe to confirm the report-type slug currently
     in production).
   - Polls `youtubereporting.jobs.reports.list` for new reports for that
     job, then downloads each CSV.
   - Backfills `video_metrics.impressions` and `video_metrics.ctr` by
     joining on `(video_id, date)` into the existing weekly windows the
     `metrics_poll` job is already maintaining.
2. **No new column-name drift**: stays inside the existing
   `video_metrics.impressions` / `ctr` shape this migration already
   reserved.
3. Quota: Reporting API also has its own quota pool — same "free against
   the Data API" property as Analytics. Log with `units=0`.
4. Authorization: reuses the same `yt-analytics.readonly` scope. No new
   re-consent.
5. Exit gate for 0.5: the same one re-consented channel returns
   trustworthy CTR for ≥1 week — at which point the original Phase 0
   exit gate is fully met and Phase 1A is unblocked.

### Open questions for 0.5
- Report-type slug — `channel_basic_a2` vs `channel_basic_a1` vs whatever
  the current production name is. Probe before writing the client.
- Backfill horizon — Reporting API only retains the last 60 days. Phase 0.5
  needs to land within that window of the first re-consent date, or some
  CTR history is permanently lost.
- Should Reporting be its own table (`video_metrics_daily`) and
  `video_metrics` keep only weekly-window aggregates? Decision deferred to
  0.5 design.

---

## Gap 2 — `isCurated` filter fully deprecated — **CLOSED (informational)**

### Spec said
> PO §Sensor "Gotchas": "Some playlist reports historically required the
> `isCurated` filter, which Google has flagged for deprecation. Verify the
> current report shape with one live `reports.query` before building the
> abstraction."

### Live probe found
Probe query 3 (`filters=playlist==<id>;isCurated==1`) returned `400
badRequest`. Probe query 2 (no `isCurated` filter) succeeded. Conclusion:
deprecation is **finalized**; including the filter is now an error.

### What shipped
- `app/analytics_client.yt_analytics_playlist_report` does **not** include
  any `isCurated` filter.
- `playlist_metrics` migration does not represent `isCurated` in any form.
- Migration header comment records this explicitly.

### Owed work
None. Documented closed.

---

## Gap 3 — Unit/type drift in retention metrics — **CLOSED (absorbed in schema)**

### Spec said
> CIL §0.3: `avg_view_duration_sec FLOAT`.
>
> PO §Sensor: `avg_time_in_playlist_min FLOAT`.

### Live probe found
- `averageViewDuration` is returned as INTEGER seconds.
- `averageTimeInPlaylist` is returned as INTEGER **seconds** (not minutes
  — the spec's `_min` suffix was wrong).

### What shipped
- `video_metrics.avg_view_duration_sec INTEGER` (was FLOAT in spec).
- `playlist_metrics.avg_time_in_playlist_sec INTEGER` (renamed from spec's
  `avg_time_in_playlist_min FLOAT`).
- Migration header comment records both changes.

### Owed work
None. The CIL/PO specs themselves could be patched for posterity, but they
are not load-bearing while this gap doc exists. Reviewers reading the spec
should land here next.

---

## Gap 4 — Playlist session metrics are web-only — **NOT OWED (constraint)**

### Spec said
> PO §Sensor "Gotchas": "`playlistStarts`, `viewsPerPlaylistStart`, and
> `averageTimeInPlaylist` only count playlist views **on the web** —
> mobile/TV are excluded, so these undercount. Judge on trends/relative
> comparison, not absolute totals."

### Status
This is a platform constraint, not a deferred deliverable. Stored verbatim;
all downstream consumers (Phase 1B health scoring, Phase 2C self-eval,
Phase 3B playlist playbook distillation) MUST compare relatively / trend
over time, not against absolute thresholds.

### Where this constraint is enforced
- `migrations/20260610134419_metrics_tables.sql` header comment.
- This file.
- Should be repeated in every PR description that introduces a playlist
  threshold (e.g. Phase 1B's `MIN_PLAYLIST_STARTS = 50` is already a relative-
  comparison gate by design).

---

## Gap 5 — `playlist_metrics.playlist_id` is not FK'd — **TEMPORARY**

### Spec said
Neither CIL nor PO specifies FK shape on `playlist_metrics.playlist_id`.
Existing `playlists` table (migration `20260518000000_playlists.sql`) is
the obvious target but its schema is being extended in Phase 1B (role,
origin, strategy_version, item_count, created_by_optimizer_at,
last_synced_at).

### What shipped
- `playlist_metrics.playlist_id TEXT NOT NULL` — no FK.
- Comment in the migration explains why: avoids coupling to a schema in
  flux, and lets metrics rows accrue for playlists the inventory sync hasn't
  reached yet.

### Plan to close
Once Phase 1B settles the `playlists` table extensions, revisit whether to
add an FK with `ON DELETE CASCADE` (matches `video_metrics.video_id`'s
pattern) — or leave it FK-free if the use case (e.g. measuring a playlist
mid-sync) makes that flexibility valuable.

### Owed by
Phase 1B (playlist inventory + health). Carry forward into that phase's gap
doc.

---

---

## Gap 6 — Traffic-source = PLAYLIST breakdown — **REOPENED (2026-07-02: query unsupported on live API)**

### Reopening (2026-07-02) — first live run falsified Step B
Tier-2 collection was gated on `channels.playlist_health_enabled`, which
stayed `false` until 2026-07-02 — so the Step B code shipped reviewed but
**never live-exercised**. On the first real run, EVERY tier-2 call failed:

```
HttpError 400 ... "The query is not supported."
  dimensions=insightTrafficSourceDetail
  filters=video==<id>;insightTrafficSourceType==PLAYLIST
```

Bisected live (channel UC8KjoL0Z9mTHKqB6gFutkJw, window 2026-06-24→30):
- `insightTrafficSourceType==PLAYLIST` + detail dimension → **400**, with or
  without `maxResults=25&sort=-views`, with or without the video filter.
- Identical query with `insightTrafficSourceType==YT_SEARCH` → **200** with
  real rows (search terms). The PLAYLIST source type itself does not
  support detail breakdown on `youtubeAnalytics.v2` — not a shape issue.

**Process lesson recorded:** Step B skipped the live-probe-first discipline
because the reviewed code path "matched the probe pattern" — but the probe
that mattered (this exact dimension+filter combo) was never run. Flag-gated
code paths must be probed with the flag ON before their gap is closed.

### Current state
- `metrics_poll.TIER2_TRAFFIC_SOURCE_SUPPORTED = False` — tier-2 collection
  disabled with a per-channel warning; tier-1 unaffected. The full plumbed
  path (flag, counters, `video_traffic_source_playlist` table, scorer
  fallback) is kept intact.
- `playlist_health.score_channel` degrades exactly as designed:
  `tier_2_pending=true` in rationales, `tier_2_available=false` in the
  envelope. Recommendations remain tier-1-only.

### Plan to re-close
Probe the **Reporting API** traffic-source report types (e.g.
`channel_traffic_source_a2`) — bulk CSVs carry `traffic_source_type` /
`traffic_source_detail` per video per day and may include playlist detail
where the on-demand API refuses it. Same probe-first discipline as Gap 1;
the Phase 0.5 ingestion machinery (jobs, ledger, daily table) is reusable
nearly verbatim if the CSV checks out.

### Original close record (2026-06-18, now known to be code-only)

### Spec said
> PO §Sensor: "Plus, on member videos, the **traffic-source = `PLAYLIST`**
> breakdown (how much of a video's reach the playlist actually drives)."

### What shipped (Phase 1B Step B)
- `analytics_client.yt_analytics_video_traffic_source_playlist(...)` —
  calls `youtubeAnalytics.reports.query` with
  `filters=video==<id>;insightTrafficSourceType==PLAYLIST` and
  `dimensions=insightTrafficSourceDetail`. Returns one row per source
  playlist that drove views (empty list when none did — common case for
  videos pulled mostly via search/browse).
- New table `video_traffic_source_playlist` (migration
  `20260618133036_phase1b_step_b_traffic_source.sql`). Keyed by
  `(video_id, playlist_id, window_start, window_end)`. Indexed on
  channel, playlist+window, and video+window for `score_channel`'s reads.
- `metrics_poll._poll_channel` extended — pulls tier-2 per video gated
  by `channels.playlist_health_enabled` so disabled channels skip the
  extra API calls. Per-item exception isolation; tier-2 failures don't
  poison the tier-1 row written above.
- `playlist_health.score_channel` aggregates by playlist + reports
  `tier_2_playlist_source_views` and `tier_2_active_member_count` in the
  recommendation rationale. Flips `tier_2_pending=false` per-channel
  when any tier-2 rows exist for that channel.
- Endpoint envelope `tier_2_available` is now dynamic — POST reads it
  from `summary.tier_2_available`; GET runs a `count` query on the
  table.

### Design decision worth recording
Tier-2 is **reported, not weighted**. The score formula stays
`tier_1 = avg_time_in_playlist_sec * views_per_playlist_start`. PO's
"primary / secondary" phrasing reads as "secondary informs but does not
dominate," and keeping the percentile contract stable across the tier-1
→ tier-2 transition was preferred over redefining the score mid-pilot.
A later tuning pass can introduce a blended score once the pilot
produces a feel for how the two signals correlate.

---

## Gap 7 — Undocumented schema additions vs. spec — **CLOSED (informational)**

### Spec gap
CIL §0.3 lists `estimatedMinutesWatched` in the metrics enumeration but
**omits** the corresponding column from the `CREATE TABLE video_metrics`
block. The shipped migration adds `est_minutes_watched BIGINT` so the
metric the client fetches has a place to land — a spec-implied add, not
silent drift, but recorded here for completeness.

### Implemented additions beyond the literal spec SQL
- `video_metrics.est_minutes_watched BIGINT` — storage for the
  `estimatedMinutesWatched` metric the spec's metric list calls for.
- `is_pre_change BOOLEAN DEFAULT FALSE` on both `video_metrics` and
  `playlist_metrics` — anticipates Loop 1 (CIL §1.2) / playlist Loop 1
  (PO §Control loop) baseline-capture-at-apply tagging. Stays `false`
  for every Phase 0 write; Phase 1 will flip it explicitly on the pre-
  change row. Declared in Phase 0 so the Phase 1 ALTER is unnecessary.
- `fetched_at TIMESTAMPTZ DEFAULT NOW()` on both tables — benign
  provenance for debugging "when did this row land vs. what window does
  it describe."
- Indexes: `video_metrics_channel_idx`,
  `video_metrics_video_window_idx`, `playlist_metrics_channel_idx`,
  `playlist_metrics_playlist_window_idx`. Performance prep for Loop 1's
  "latest window per id" query — cheap, idempotent, won't change behavior.

### Owed work
None. The CIL/PO specs could be patched to enumerate these explicitly, but
the gap doc is the source of truth in the interim.

---

## Gap 8 — `quota_log` row volume from analytics polling — **OPEN (defer-or-fix)**

### Observation
`analytics_client._log_quota` writes one `quota_log` row per Analytics
call with `units=0`. The poll job calls Analytics once per public video
and once per playlist per channel per day. For a channel with 500
public videos + 30 playlists that's ~530 zero-unit rows per day, ~16k
per month, ~190k per year. Per channel.

### Impact
- `quota_log` is the source for the dashboard sparkline and the Data API
  quota math (`quota.units_used_today` does `sum(units)` — zeros don't
  pollute the math but they do bloat the table). The sparkline query in
  `dashboard.py` reads at most 1000 rows over 7 days — at ~3,700 analytics
  rows/week per channel, the sparkline can be silently truncated.
- Visibility into per-channel analytics call volume is genuinely useful
  for debugging "did the poll run today?" — so dropping the log entirely
  is a regression.

### Plan to close (three paths)
- **A. Aggregate at the end of `_poll_channel`** — one summary row per
  channel per job: `{"operation": "youtubeAnalytics.poll", "units": 0,
  "channel_id": cid}` with the per-channel counts encoded in a new
  metadata column (or stuffed into a JSONB extension of quota_log). One
  row per channel per day.
- **B. Add an explicit `success_count` / `call_count` column on
  `quota_log` and have analytics writes aggregate inline.** More
  invasive but better-typed.
- **C. ✅ APPLIED (Phase 1B Step B, 2026-06-18)** — filter
  `dashboard.py` sparkline + `quota.units_used_today()` to `units > 0`
  so the analytics zero-rows can't crowd real Data API rows out of the
  1000-row window. Cheapest win; defers the actual aggregation.

### Status
**Partially closed.** Path C shipped (`quota.units_used_today` filter
landed during Phase 0 reviewer pass; sparkline filter landed during
Phase 1B Step B because Step B's tier-2 poll doubles the zero-unit row
volume). The bloat-prevention path (A or B) stays open — `quota_log`
still grows by ~K rows/channel/day. Revisit if table size becomes a
concrete operational problem.

---

---

## Gap 9 — 7-day refresh-token expiry in "Testing" OAuth consent screen — **CLOSED (2026-07-02)**

### Resolution (2026-07-02)
The OAuth consent screen was moved to **In production** (unverified — fine at
2/100 users; the only cost is a one-time "unverified app" click-through per
consent). All three channels (Punjabi, Marathi, Hindi
`UCR9qQMyP86aSt-1VgaMg7UA`) re-consented the same day; tokens issued under
In-production status persist until manually revoked. Verified live: the
2026-07-02 Reporting probe + job creation succeeded on all touched channels.
Bit us twice before closing (Marathi 2026-06-17, Punjabi ~2026-06-25).

The medium-term defensive item below (surface token-expiry in the UI, not
just scope absence) remains a good Phase 1A hardening task — a durable token
can still be revoked manually — but is no longer load-bearing.

### Observation
The Google Cloud OAuth consent screen is currently in **Testing** mode. All
refresh tokens issued by such projects **expire after 7 days of issuance**,
not 6 months — and not "after N days of disuse." This is independent of
whether the token is actively refreshed or not.

Verified by direct probe on 2026-06-17 against the channel
`UCr5-YUqBiW7PUmeAtxUWuRg` (re-consented 2026-06-10):

```
RefreshError: invalid_grant: Token has been expired or revoked.
```

Token age at failure: ~7 days. No user-side revocation.

### Impact
- The Phase 0 `metrics_poll` daily cron will **silently start logging
  warnings for every channel exactly 7 days after each re-consent** until
  the consent screen is moved to "In production". Phase 0's "≥1 week of
  watching" exit gate is literally at the failure horizon.
- The code's behavior is correct: `analytics_client.analytics_for_channel`
  → `creds.refresh()` → `RefreshError(invalid_grant)` → `TokenExpiredError`
  → `metrics_poll` catches it and skips the channel. No crash; one warning
  log per channel per tick.
- **There is no user-facing surface** for this state. The Phase 0 UI banner
  only checks `analytics_authorized` (which stays `true` — the column
  reflects scope grant, not token freshness). A channel can become silently
  unpollable with no UI signal.

### Plan to close
- **Short-term (for Phase 0 exit gate):** Move the OAuth consent screen to
  "In production" in the Google Cloud Console. Once verified by Google,
  refresh tokens live until manually revoked. This unblocks the ≥1-week
  poll-watch requirement.
- **Medium-term (defensive code, Phase 1A):** Add a `channels.metrics_poll_paused_reason`
  column (or reuse `autopilot_paused_reason="token_expired"`'s mechanism)
  so the existing reconnect banner UI flips on token expiry, not just on
  scope absence.
- **Documentation:** Until the consent screen is promoted, the runbook for
  Phase 0 watching needs an explicit "re-consent every 7 days" instruction.

### Workaround for the current Phase 0 smoke test
Re-consent the channel once via `/auth/login`. The smoke test can then
proceed; the consent-screen promotion can land separately.

---

---

## Gap 10 — ~12.5% transient DNS failures on first poll — **OPEN (low-cost defer)**

### Observation
First real `poll_metrics()` run (2026-06-17, channel
`UC8KjoL0Z9mTHKqB6gFutkJw`, 4,373 video pulls) had this distribution:

| Outcome | Count | % |
|---|---|---|
| Written | 1,213 | 27.7 |
| No data (None — dormant) | 2,611 | 59.7 |
| Errored | 549 | 12.5 |

Every errored row logged `Unable to find the server at
youtubeanalytics.googleapis.com` — classic DNS-resolution failure. The
errors arrive in tight clusters (likely local-resolver / NAT pressure
under sustained connection volume), not as a steady rate.

### Impact
- Per-row error isolation worked: the poll did not crash. The 549 failed
  videos simply have no `video_metrics` row for this window.
- Idempotent reruns recover: tomorrow's tick will retry every video and
  the previous day's window is still queryable by the Analytics API
  (within the standard retention horizon).
- For Loop 1's CTR-window comparison this is fine — a missing weekly
  window is treated as "no observation," same as a dormant-video skip.
- For the Phase 0 exit gate ("≥1 week of trustworthy data"): if the same
  ~12.5% miss rate persists across 7 days, every video lands ≥5/7 of its
  expected windows. Trustworthy enough — but the rate should drop, not
  persist.

### Plan to close
- **Cheapest:** wrap the analytics call in a small per-item retry-with-
  backoff (2 attempts, exponential, jitter). Add directly in
  `analytics_client.yt_analytics_video_report` /
  `yt_analytics_playlist_report` — same shape as `app/db.py`'s
  retry-wrapped supabase exec.
- **Investigate first:** run a clean second poll (after a delay) and see
  whether the same video IDs fail again or whether it's random across
  the corpus. Random → transport-layer flakiness, fix with retry.
  Repeatable → something API-side specific to those IDs (e.g. videos
  pending Analytics processing), and the fix is different.
- **Don't:** silently swallow these without a per-channel error-count
  ceiling. If the rate ever crosses, say, 25% the poll should pause that
  channel and surface a visible signal.

### Owed by
Carry into Phase 1A's `measurement_eval` planning. Not a Phase 0 exit-
gate blocker if the rate stays at-or-below current levels for the
≥1-week watch window.

---

## Verification recipe for the Phase 0 exit gate (Option B form)

> **Pre-flight (Gap 9 — load-bearing):** the ≥1-week watch window is
> literally unmeetable until the OAuth consent screen is promoted to
> "In production" OR every re-consented channel is re-consented again
> within 6 days of the previous re-consent. Without this, `metrics_poll`
> will silently `TokenExpiredError`-skip every channel on day 8 and the
> "rows accruing for ≥1 week" half-gate trivially fails. Confirm Gap 9
> is closed before declaring the gate met.

The original spec wanted **CTR and playlist** for ≥1 week. Under Option B
the gate is split:

| Half-gate | How to verify | Status |
|---|---|---|
| Playlist + retention metrics flow for ≥1 week | `select count(*), max(window_end) from video_metrics where channel_id = 'UCr5-YUqBiW7PUmeAtxUWuRg'`; same for `playlist_metrics`. Expect ≥1 row per public video per week of running. | met when poll has run for 7+ days |
| CTR / impressions flow for ≥1 week | Phase 0.5 (Reporting API ingestion) — **not in scope of current Phase 0**. | DEFERRED — gap 1 |

A `null`-only `impressions`/`ctr` column on every `video_metrics` row is
**expected** until Phase 0.5 lands. Downstream phases reading these columns
must treat null as "not yet observed," not as "zero observations."
