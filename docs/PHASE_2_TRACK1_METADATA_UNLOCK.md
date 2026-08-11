# Phase 2 · Track 1 — Unlock + Protect the Metadata Loop — Implementation Checklist

**Status:** DRAFT — to be reviewed before any implementation work begins.
**Spec sources of record:** `docs/CONTINUOUS_IMPROVEMENT_LOOP.md` §0 (Sensor) / §1
(Per-video control loop, esp. §1.3, §1.7), `docs/PHASE_0_GAPS.md` §Gap 1 +
§"Verification recipe for the Phase 0 exit gate".
**Substrate already shipped:** Phase 0 sensor (`analytics_client.py`,
`metrics_poll.py`, `video_metrics`/`playlist_metrics`), Phase 0.5 Reporting-API
reach ingestion (`reporting_client.py`, `reporting_poll.py`, `video_reach_daily`,
`reporting_reports_ingested`), Phase 1A Loop-1 measurement lifecycle
(`measurement.py`, `audits.measurement_status`, `channels.measurement_enabled`).

> This is an **executable checklist**, not a spec. Each numbered step is one
> IMPLEMENT → REVIEW pair with the exact `file:line` seams to touch. It proposes
> and grounds every change in the specs above; where a decision is made it is
> called out. No code is written here — only the plan, the seams, and the gates.

---

## 1. Goals + non-goals

### Goals (what Track 1 ships)

Track 1 has **two pieces**, sequenced piece 1 → piece 2 (piece 2 is independent
of piece 1's certification but shares the "don't churn a video mid-measurement"
principle from CIL §1.7 and should ship in the same track).

**Piece 1 — Phase 0/0.5 CTR exit-gate certification (~0.5–1 day).**
Certify that a channel has **≥1 week of trustworthy CTR** before enabling
measurement, and expose the enable switch through the settings API — with
certification as a hard precondition on flipping it `true`.

Spec grounding — the Phase 0 exit gate (`PHASE_0_GAPS.md` §"Verification recipe"):

> | CTR / impressions flow for ≥1 week | Phase 0.5 (Reporting API ingestion) … | DEFERRED — gap 1 |

and CIL §0.5:

> **Statistical floor:** CTR on a handful of impressions is meaningless.

Piece 1 turns that deferred half-gate into a **programmatic, repeatable check**
and wires it to the enable switch.

**Piece 2 — Autopilot excludes in-measurement videos (~0.5 day).**
Autopilot must not re-audit a video whose CTR is mid-measurement — a fresh audit
would change the packaging under an in-flight experiment and confound the
verdict. Exclude any video whose latest audit has
`measurement_status in ('awaiting_window','measuring')`.

Spec grounding — CIL §1.7 ("Autopilot integration"):

> - **Exclude** videos in `awaiting_window` / `measuring` (don't churn a video
>   mid-measurement).

### Non-goals (explicit out-of-scope)

- **No new measurement metrics or lifecycle changes.** `measurement.py`'s
  window math, decision policy, and the `measurement_status` state machine are
  untouched. Track 1 gates *access* to the loop; it does not change the loop.
- **No auto-revert / auto-redo.** `AUTO_REVERT_ON_REGRESSION` stays `false`
  (CIL §1.9). Track 1 does not touch Loop 1's critic.
- **No `include redo_queued as work items`** — that is the *other* half of CIL
  §1.7 and a separate Track. Piece 2 only adds the *exclude* half.
- **No playbook (Loop 2) / strategy (Loop 3) work.**
- **No backfill of historical CTR** beyond what Phase 0.5 already ingests into
  `video_reach_daily`.
- **No fleet-wide enablement.** Certification is per-channel; roll out one
  channel first (CIL §Build order: "one channel first, ~1 week, then widen").

---

## 2. Existing-state audit

### 2.1 The reach-ingestion gate (the crux — see §3)

`app/config.py:157`:

```python
REPORTING_MEASURED_CHANNELS_ONLY = os.getenv("REPORTING_MEASURED_CHANNELS_ONLY", "true").lower() == "true"
```

`reporting_poll.poll_reporting` (`app/reporting_poll.py:327-330`) filters:

```python
q = supabase().table("channels").select("id").eq("analytics_authorized", True)
if settings.REPORTING_MEASURED_CHANNELS_ONLY:
    q = q.eq("measurement_enabled", True)
```

**Consequence:** with the default `true`, a channel accrues **zero** rows in
`video_reach_daily` (and therefore zero certifiable CTR coverage) until
`measurement_enabled` is already on. This is the chicken-and-egg §3 resolves.

### 2.2 The reach ledger (the authoritative coverage source)

`reporting_poll._ledger_state(channel_id)` (`app/reporting_poll.py:60-80`)
returns `(ingested_report_ids, covered_data_days)` from
`reporting_reports_ingested` in one paginated read. **`covered_data_days` is the
authoritative set of data-days for which a report was ingested** — exactly what
"≥7 contiguous covered days" must be computed over. Piece 1 reuses it verbatim;
no new query.

Day-list / contiguity helpers already exist and must be mirrored, not
re-invented:
- `reporting_poll._window_days(start, end)` (`app/reporting_poll.py:163-165`) —
  inclusive ISO-date list for a window.
- `measurement._days_between(start, end)` (`app/measurement.py:84-86`) —
  identical shape (the two are deliberate twins across modules).

### 2.3 The measurement enable switch — column exists, API does not expose it

- `channels.measurement_enabled boolean default false` already exists
  (`supabase/migrations/20260702183233_phase1a_loop1_measurement.sql:57`).
- It is read at apply-time (`app/audits.py:421`) and by `reporting_poll`
  (§2.1) and `measurement.py:251`.
- **But it is NOT exposed through the settings API.** `list_channels`'s SELECT
  (`app/auth.py:112-118`) omits it; `ChannelSettings` (`app/auth.py:122-131`)
  has no field for it; the PATCH handler (`app/auth.py:134-164`) has no branch
  for it. Today it can only be flipped by a raw DB write.
- The exact pattern to mirror is `playlist_health_enabled`: present in the
  SELECT (`app/auth.py:115`), in `ChannelSettings` (`app/auth.py:127`), and
  handled in PATCH (`app/auth.py:145-149`).

### 2.4 The autopilot picker — two paths, must stay in parity

- **In-app picker** `_next_video_for_channel` (`app/autopilot.py:97-158`). The
  audit SELECT (`app/autopilot.py:132-138`) pulls `video_id,status,created_at`;
  the latest-per-video map is built at `app/autopilot.py:140-143`; the skip set
  `blocked_ids` is derived from `skip_statuses` at `app/autopilot.py:146-147`.
- **RPC picker** `next_audit_candidate` (`supabase/migrations/20260727160000_next_audit_candidate_rpc.sql`).
  The `latest` CTE (lines 23-27) selects `a.video_id, a.status`; the not-in
  status guard is at lines 34-35.
- `AUTOPILOT_PICKER_USE_RPC` defaults **`false`** (`app/config.py:45`), so the
  in-app path is live today — but the parity comment (`app/config.py:39-45`)
  is explicit that both are shipped and a live parity test gates flipping the
  RPC on. **Both paths must change together or they silently diverge.**
- The status constant to reuse is
  `metrics_poll.ACTIVE_MEASUREMENT_STATUSES = ("awaiting_window","measuring")`
  (`app/metrics_poll.py:48`).

### 2.5 The lifecycle-column separation (do not conflate)

`audits.status` (`pending|applied|failed|quarantined|…`) and
`audits.measurement_status` (`not_applicable|awaiting_window|measuring|win|
neutral|regression`) are **separate columns by deliberate design** (CIL §1.1:
"Add a measurement sub-lifecycle as a **separate column** so the existing
`status` … stays untouched"). Piece 2 filters on `measurement_status` **in
addition to** the existing `status` guard — it never merges the two.

---

## 3. The chicken-and-egg sequencing (READ THIS FIRST)

> **This is the single most important part of the doc. Do not enable
> measurement on a channel until its CTR is certified — but the channel accrues
> no CTR data to certify until reach ingestion runs, which today is itself gated
> on `measurement_enabled` (§2.1). Breaking the cycle requires a warmup phase.**

The correct sequence for the pilot channel:

1. **Open reach ingestion for the pilot without enabling measurement.** Two
   ways, choose one (§4.1 Step 1.1):
   - **(a) Global escape hatch:** set `REPORTING_MEASURED_CHANNELS_ONLY=false`
     temporarily so `poll_reporting` (`app/reporting_poll.py:327-330`) ingests
     every `analytics_authorized` channel. Simplest, but re-widens reach for
     *all* channels (DB-size cost — the very cost `config.py:149-157` documents).
   - **(b) Warmup flag (recommended):** add a per-channel
     `channels.reach_warmup boolean default false` and change the
     `poll_reporting` filter to `measurement_enabled OR reach_warmup`. Flip
     `reach_warmup=true` on the pilot only. Scopes the cost to one channel and
     is the honest primitive for "ingesting reach to certify, not yet
     measuring."
2. **Wait ~1 window.** Reports arrive erratically and out of order
   (`PHASE_0_GAPS.md` §Gap 1, 2026-07-02 status) and Analytics lags ~2 days
   (CIL §0.5). Allow ≥7 calendar days plus lag slack (≈9–10 days) before
   expecting 7 contiguous covered data-days.
3. **Certify ≥7 contiguous covered data-days** using `_ledger_state`'s
   `covered_data_days` (§5, the coverage helper).
4. **Expose `measurement_enabled` through the PATCH endpoint with certification
   as a precondition** (§4.2). The handler refuses `true` unless the coverage
   check passes.
5. **Flip `measurement_enabled=true`** via the now-guarded endpoint. If using
   the warmup flag, `reach_warmup` can be cleared afterward — `measurement_enabled`
   now keeps ingestion alive on its own.

**Recommendation:** ship path (b). It makes "warming up to certify" a
first-class, per-channel state instead of a global toggle an operator must
remember to revert. If reviewers prefer (a), the certification helper and the
endpoint guard (§4.2) are identical either way — only Step 1.1 changes.

---

## 4. Piece 1 — CTR exit-gate certification

### Track 1A — reach warmup + coverage helper

**Step 1.1 — Open reach ingestion for the pilot (warmup seam). (~1h)**
Implement §3 Step 1's chosen path. For recommended path (b): new migration
adds `channels.reach_warmup boolean default false` (idempotent
`add column if not exists`); change the filter in
`reporting_poll.poll_reporting` (`app/reporting_poll.py:327-330`) from
`.eq("measurement_enabled", True)` to an OR over `measurement_enabled` /
`reach_warmup`. Because PostgREST `.eq` can't express OR cleanly, fetch
`analytics_authorized` channels and filter in Python (small list), or use
`.or_("measurement_enabled.eq.true,reach_warmup.eq.true")`.
*Review:* with the flag off, `poll_reporting` behaves exactly as today (measured-
only); with `reach_warmup=true` on the pilot, the pilot appears in the poll set
and `video_reach_daily` starts accruing rows for it. Confirm no other channel's
row volume changes.

**Step 1.2 — Coverage-check helper. (~2h)**
Add `def certify_ctr_coverage(channel_id, min_days=7) -> dict` (recommended
home: `app/reporting_poll.py`, next to `_ledger_state`, or a small new
`app/reach_coverage.py` if you prefer to keep `reporting_poll` ingestion-only).
It:
- Calls `_ledger_state(channel_id)` (`app/reporting_poll.py:60-80`) → uses the
  `covered_data_days` set (the second tuple element).
- Computes the **longest run of contiguous ISO dates** in that set. Reuse the
  date arithmetic pattern from `_window_days`/`_days_between`
  (`app/reporting_poll.py:163-165`, `app/measurement.py:84-86`) — sort the days,
  walk with `date.fromisoformat`, count consecutive `+1 day` steps.
- Returns `{certified: bool, contiguous_days: int, covered_total: int,
  latest_day: str|None, min_days: int}`. `certified = contiguous_days >= min_days`.
- **Optional but recommended:** also assert a data-quality floor — that the
  covered days actually carry impressions (a report can be ingested with sparse
  rows). Cross-check against `video_reach_daily` for the window, or at minimum
  document that "covered" means "a report was ingested for that day," not
  "impressions were non-trivial." Tie back to CIL §0.5's `MIN_IMPRESSIONS`
  floor in the helper's docstring.
*Review:* run against the pilot after Step 1.1 has ingested a week; confirm
`contiguous_days` matches a hand-count of distinct `data_date` values in
`reporting_reports_ingested`; confirm `certified=false` before 7 days and
`true` after.

**Step 1.3 — `scripts/verify_reach_coverage.py` (ops CLI). (~1h)**
Thin wrapper around `certify_ctr_coverage` for operators. Prints the coverage
dict for one channel (or all `analytics_authorized` channels), read-only, skips
gracefully without live creds (mirror the guard style in
`tests/test_playlist_sims_parity_live.py:23-30`). This is the exit-gate
verification recipe (§6) in runnable form.
*Review:* `python scripts/verify_reach_coverage.py <channel_id>` prints the
coverage report; exits non-zero if not certified (so it can gate a deploy step).

### Track 1B — expose the enable switch (gated)

**Step 1.4 — Add `measurement_enabled` to the settings API, mirroring
`playlist_health_enabled`. (~2h)**
Three edits in `app/auth.py`, each mirroring the existing
`playlist_health_enabled` treatment:
- Add `measurement_enabled` to the `list_channels` SELECT string
  (`app/auth.py:112-118`, alongside `playlist_health_enabled` at line 115).
- Add `measurement_enabled: bool | None = None` to `ChannelSettings`
  (`app/auth.py:122-131`, mirroring line 127).
- Add a PATCH branch (`app/auth.py:134-164`, mirroring the
  `playlist_health_enabled` branch at 145-149) — **but with the precondition**:

  ```
  if body.measurement_enabled is not None:
      if body.measurement_enabled:                      # enabling
          cov = certify_ctr_coverage(channel_id)        # §Step 1.2
          if not cov["certified"]:
              raise HTTPException(409, f"CTR not certified: {cov}")
      patch["measurement_enabled"] = body.measurement_enabled
  ```

  Disabling (`false`) is always allowed — no precondition. Only `true` is
  guarded. Use `409 Conflict` (state not ready), not `403`.
*Review:* PATCH `measurement_enabled=true` on an uncertified channel returns 409
with the coverage dict; on a certified channel it succeeds and the column flips;
PATCH `measurement_enabled=false` always succeeds; `GET /channels` now returns
the field. Confirm no other channel setting's behavior changed.

---

## 5. Piece 2 — Autopilot excludes in-measurement videos

Both picker paths must change in parity (§2.4). The behavioral rule for both:
**a video whose latest audit's `measurement_status` is `awaiting_window` or
`measuring` is not a valid pick**, in addition to the existing `status`-based
skip.

**Step 2.1 — In-app picker: exclude in-measurement videos. (~1.5h)**
In `_next_video_for_channel` (`app/autopilot.py:97-158`):
- Extend the audit SELECT (`app/autopilot.py:132-138`) from
  `select("video_id,status,created_at")` to also pull `measurement_status`.
- The latest-per-video map (`app/autopilot.py:140-143`) currently stores only
  `status`; change it to keep the whole row (or both fields) for the latest
  audit per video.
- Extend `blocked_ids` (`app/autopilot.py:146-147`): a video is blocked if its
  latest `status in skip_statuses` **OR** its latest `measurement_status in
  metrics_poll.ACTIVE_MEASUREMENT_STATUSES`. Import the constant from
  `app/metrics_poll.py:48` — do not re-literal the tuple.
*Review:* construct/point at a channel with a video in `measuring`; confirm the
in-app picker (flag off) skips it and returns the next eligible video; confirm a
video with `measurement_status='win'`/`'neutral'`/`not_applicable` is still
pickable (only the two active statuses block).

**Step 2.2 — RPC picker: same exclusion in SQL. (~1.5h)**
NEW `create or replace function` migration (do not edit the existing
`20260727160000_next_audit_candidate_rpc.sql` in place — add a new dated
migration that redefines the function, matching the repo's forward-migration
discipline). In the `latest` CTE (lines 23-27) add `a.measurement_status` to
the `distinct on (a.video_id)` select; extend the not-in guard (lines 34-35)
so the row is excluded when
`la.measurement_status in ('awaiting_window','measuring')`. Keep the ordering
(`published_at desc, id`) and the `service_role`-only grant identical to the
current definition (lines 36-41).
*Review:* apply the migration to a clone; call `next_audit_candidate` for a
channel with an in-measurement video; confirm the RPC omits it and returns the
same id the in-app path returned in Step 2.1.

**Step 2.3 — Parity test (the gate). (~1.5h)**
Add `tests/test_autopilot_measurement_exclusion_parity_live.py`, mirroring
`tests/test_playlist_sims_parity_live.py` and the existing
`tests/test_autopilot_picker_parity_live.py` (which already flips
`AUTOPILOT_PICKER_USE_RPC` on/off via the `pytest_flag` context manager at
`tests/test_autopilot_picker_parity_live.py:53-63`). The test:
- Marks `@pytest.mark.live`; skips without creds (`test_playlist_sims_parity_live.py:23-30`).
- Skips cleanly if the RPC isn't migrated (mirror
  `test_autopilot_picker_parity_live.py:34-38`).
- For every channel, asserts `_next_video_for_channel` with the flag **off**
  (in-app) picks the same id as with the flag **on** (RPC) — the existing
  picker-parity assertion, now exercised against data that includes
  in-measurement videos so the new exclusion is covered on both sides.
*Review:* the test passes on live data and would fail if only one path had the
exclusion (verify by temporarily reverting Step 2.2 and watching it go red).

---

## 6. Migration list

| Migration | Purpose | Idempotent op |
|---|---|---|
| `<ts>_reach_warmup_flag.sql` (Piece 1, if path (b)) | `channels.reach_warmup boolean default false` | `add column if not exists` |
| `<ts>_next_audit_candidate_exclude_measurement.sql` (Piece 2) | Redefine `next_audit_candidate` to also exclude in-measurement videos | `create or replace function` + re-issue `revoke`/`grant` |

No migration is needed for `measurement_enabled` — the column already exists
(`20260702183233_phase1a_loop1_measurement.sql:57`); Piece 1 only exposes it.

---

## 7. Config / flag changes

| Flag / setting | Location | Change |
|---|---|---|
| `REPORTING_MEASURED_CHANNELS_ONLY` | `app/config.py:157` | Path (a) only: flip to `false` during warmup, revert after. Path (b): unchanged. |
| `channels.reach_warmup` | new column (path (b)) | Per-channel warmup switch; `poll_reporting` OR's it with `measurement_enabled`. |
| `channels.measurement_enabled` | existing column | Now settable via PATCH `/channels/{id}`, guarded by certification. |
| `AUTOPILOT_PICKER_USE_RPC` | `app/config.py:45` | Unchanged (stays `false`); both paths ship updated regardless. |

No new tunable thresholds beyond `min_days=7` (the exit-gate spec value),
parameterized in `certify_ctr_coverage` for testability.

---

## 8. Exit-gate verification recipe

Run before declaring Track 1 done and before flipping `measurement_enabled` on
the pilot. Mirrors `PHASE_0_GAPS.md` §"Verification recipe for the Phase 0 exit
gate", now made programmatic.

1. **Pre-flight — token freshness (Gap 9).** Gap 9 is CLOSED (OAuth "In
   production", 2026-07-02) so tokens are durable — but confirm the pilot's
   `analytics_authorized=true` and that `reporting_poll` isn't logging
   `TokenExpiredError` for it.
2. **Reach ingestion is live for the pilot.** After §3 Step 1, confirm rows are
   landing: `select count(*), max(date) from video_reach_daily where channel_id
   = '<pilot>'` grows day over day.
3. **Coverage certified.** `python scripts/verify_reach_coverage.py <pilot>`
   (Step 1.3) reports `certified=true, contiguous_days>=7`. Equivalent SQL
   spot-check: `select count(distinct data_date) from reporting_reports_ingested
   where channel_id = '<pilot>'` and eyeball contiguity.
4. **Enable switch honors the gate.** PATCH `measurement_enabled=true` returns
   409 on a still-uncertified channel and 200 on the certified pilot.
5. **Autopilot exclusion holds on both paths.** The Step 2.3 parity test passes
   live; a video in `measuring` is confirmed absent from both picker outputs.
6. **Roll out one channel, watch ~1 week, then widen** (CIL §Build order).

---

## Appendix — discipline checklist (carry into PRs)

- [ ] All migration ops idempotent (`add column if not exists`;
      `create or replace function`).
- [ ] The chicken-and-egg sequence (§3) is followed: reach ingested → wait →
      certify → expose switch → enable. No channel gets `measurement_enabled=true`
      before `certify_ctr_coverage` passes.
- [ ] `certify_ctr_coverage` reads coverage **only** from `_ledger_state`'s
      `covered_data_days` (`app/reporting_poll.py:60-80`) — no ad-hoc re-query of
      the ledger.
- [ ] Contiguity math mirrors `_window_days` / `_days_between`
      (`app/reporting_poll.py:163-165`, `app/measurement.py:84-86`), not a new
      hand-rolled date walk with off-by-one risk.
- [ ] `measurement_enabled` PATCH branch refuses `true` unless certified
      (409, not 403); `false` always allowed. Mirrors `playlist_health_enabled`
      shape (`app/auth.py:115,127,145-149`) plus the guard.
- [ ] Piece 2 changes **both** picker paths in the same PR
      (`app/autopilot.py:132-147` **and** the new `next_audit_candidate`
      migration). Parity test added and green before merge.
- [ ] Piece 2 reuses `metrics_poll.ACTIVE_MEASUREMENT_STATUSES`
      (`app/metrics_poll.py:48`) — no re-literaled `("awaiting_window","measuring")`
      tuple in `autopilot.py`.
- [ ] `audits.status` and `audits.measurement_status` treated as separate
      columns (CIL §1.1) — the new filter is additive, never a merge of the two.
- [ ] `DRY_RUN` unaffected: coverage certification and picker exclusion are pure
      reads; no YouTube writes added.
- [ ] Warmup path (path (a) global flag or path (b) `reach_warmup`) does not
      change any non-pilot channel's `video_reach_daily` growth beyond the
      documented pilot cost.
- [ ] PR description restates the §3 chicken-and-egg rationale so the reviewer
      understands why `measurement_enabled` must not be flipped ahead of
      certification.
