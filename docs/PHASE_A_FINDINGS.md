# Phase A — findings

Record of the human-run Phase A tasks in Part 1 of
`docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`: A0, A1–A3, A5,
A7 and A9. The code tasks (A4, A6, A8, A10, A11) are recorded in their PRs and in
`STATE.md`. Fill every blank from the run; paste raw evidence, don't paraphrase it.
If a probe fails, paste the exact error and list the variants tried (spec Part 1,
"Probe discipline").

**Where each command runs.** The office machine is not a git checkout. It holds
`.env`, `docker-compose.yml` and the `.bat` files, nothing else.

- **[office]**: run on the office machine, from the folder holding
  `docker-compose.yml`. That covers `docker compose`, `psql` (through
  `docker compose exec db psql -U midas midas`), and `curl` to the app on
  `http://localhost:8000`.
- **[dev]**: run on a dev machine with a repo checkout, `venv`, `client_secret.json`
  and a `.env` whose `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` reach the database
  holding the channel's OAuth tokens. These are the probes and
  `scripts/create_reporting_job.py`. Every probe reads the channel's stored token,
  and the only DB write any of them can make is the token refresh inside
  `youtube_for_channel` / `reporting_for_channel` (`app/youtube_client.py:22-49`,
  `app/analytics_client.py:71-111`). The office PostgREST is bound to loopback
  (`docker-compose.yml`: `127.0.0.1:8001:80`), so if the dev machine can't reach
  it, the same scripts ship in the image (`Dockerfile`: `COPY scripts ./scripts`)
  and run on the office machine as
  `docker compose exec midas python -m scripts.probes.<name> <args>` once the
  image carrying them is pulled. Write any output file under `/app/logs/` there,
  so it lands in the host's `logs/`.

---

## Pre-restart checklist

Do these on the office machine before `start.bat`.

| Field | Value |
|---|---|
| Date | |
| Channel | n/a (fleet config) |
| Command / SQL | the checklist items below |
| Raw evidence | |
| Outcome | |

- [ ] **Image.** The prep chain is merged to `main` and the "Build and Push Docker
      Image" workflow has pushed `ghcr.io/jugaadchhabra/midas:latest`
      (`.github/workflows/docker-publish.yml` builds on push to `main`). The
      `midas` service has `pull_policy: always`, so `start.bat`'s
      `docker compose up -d` pulls it. A merge is not a deploy.
- [ ] **`.env`: rename `STRATEGY_VERSION` to `STRATEGY_LABEL`.** The app reads only
      `STRATEGY_LABEL` (`app/config.py:237`,
      `STRATEGY_LABEL = os.getenv("STRATEGY_LABEL") or "2026.07-baseline"`); nothing
      in `app/` reads `STRATEGY_VERSION` any more. The label is only the prefix: the
      stamp is `<STRATEGY_LABEL>-<12 hex>` (`app/audits.py` `strategy_version`). If
      the old value was `2026.07-baseline-v1`, either drop the line (the default
      applies) or set `STRATEGY_LABEL=2026.07-baseline`.
- [ ] **`.env`: the four A4 freeze flags stay unset or `false`.** Each defaults to
      `false` (`app/config.py:34,115-117`):

      | Flag | What `false` freezes |
      |---|---|
      | `PLAYLIST_DISCOVERY_ENABLED` | `playlist_discovery` (Sun 03:00) is not registered: no playlists created on YouTube |
      | `PLAYLIST_RECONCILE_WRITES_ENABLED` | `playlist_reconcile` (02:00) still runs `sync_playlists` but skips `reconcile_channel`: no `playlistItems.insert/delete`, no new proposals. `POST /channels/{id}/playlists/reconcile` returns 409 |
      | `PLAYLIST_TUNING_ENABLED` | `playlist_tuning` (Mon 03:30) is not registered: `PLAYLIST_JOIN_HIGH` is not mutated |
      | `REFLECTION_ENABLED` | `reflection` (Mon 04:00) is not registered: no prompt rewrites, `search.list` or Perplexity calls. `POST .../reflection/trigger` and `POST .../prompt-versions/{vid}/promote` return 409 |

      After boot, confirm the startup log has one line per frozen job
      (`"<job_id> not registered: <FLAG>=false"`, and for reconcile
      `"playlist_reconcile registered for sync only: add/remove skipped
      (PLAYLIST_RECONCILE_WRITES_ENABLED=false)"`).
- [ ] **No compose change is needed.** `git diff 41131ee..HEAD -- docker-compose.yml`
      is empty (checked 2026-09-29 at `21d09aa`), and the `midas` service loads the
      whole `.env` through `env_file: - .env`, so the new settings need only `.env`
      lines. Keep the office `docker-compose.yml` as it is.

---

## A0 — Pause Midas title autopilot

| Field | Value |
|---|---|
| Date (pause timestamp, UTC) | |
| Channel | |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**Shorts independence (spec A0 step 1).**

From the code at `21d09aa`: the tick picks from `eligibility.channels_for(Job.AUTOPILOT)`
(`app/autopilot.py:379`), which admits a channel when either path is open
(`has_work` = `can_audit or can_cut_shorts`, `app/eligibility.py:96-98`).
`can_cut_shorts` reads only `autopilot_shorts_enabled` (`app/eligibility.py:85-93`).
In `tick`, the Shorts action runs before the audit gate
(`app/autopilot.py:538-541`), and `can_audit` (which needs `autopilot_enabled`)
only stops the audit path after it (`app/autopilot.py:547-550`). So with
`autopilot_enabled = false` and `autopilot_shorts_enabled = true`, the Shorts
action should keep running. Confirm on the running app:

| Field | Value |
|---|---|
| Does the Shorts action still run with `autopilot_enabled=false`, `autopilot_shorts_enabled=true`? (yes/no) | |
| Evidence (`shorts_jobs` rows created after the pause, or the tick log) | |
| If no: owner's decision on pausing Shorts too | |

**The safe order, verbatim.** Autopilot is an APScheduler `interval` job of
`seconds=settings.AUTOPILOT_TICK_SECONDS` (`app/main.py:270-277`, in
`_register_jobs`), and an interval trigger with no `next_run_time` first fires one
interval after `scheduler.start()`. `AUTOPILOT_TICK_SECONDS` defaults to 120
(`app/config.py:56`; the office `.env` may override it). So the channel must be off
before the app boots.

1. **[office]** Start only the database:

   ```
   docker compose up -d db
   ```

2. **[office]** Find the channel with autopilot on, then turn it off:

   ```
   docker compose exec db psql -U midas midas
   ```

   ```sql
   select id, name, autopilot_enabled, autopilot_shorts_enabled, measurement_enabled
   from channels where autopilot_enabled order by name;

   update channels set autopilot_enabled = false
   where id = '<channel_id>'
   returning id, name, autopilot_enabled, autopilot_shorts_enabled, measurement_enabled;
   ```

   The UPDATE must report `UPDATE 1`. Leave `measurement_enabled` on (spec A0 step 3).
   Don't use `autopilot_paused_reason`: that pause has a cooldown
   (`AUTOPILOT_PAUSE_COOLDOWN_MINUTES`) and resumes on its own.
   **If it reports `UPDATE 0` because the database is empty, stop.** On boot the app
   restores the NAS snapshot into an empty database (`provision.ensure_database_populated`,
   `app/main.py`), and the restored row would carry the old `autopilot_enabled`. In
   that case start the app, and run the same UPDATE within the first
   `AUTOPILOT_TICK_SECONDS` of boot, or use
   `PATCH /auth/channels/<channel_id>` with `{"autopilot_enabled": false}`.

3. **[office]** Start the app:

   ```
   start.bat
   ```

**Videos in a measurement window at pause time.** Slice 1 excludes these until their
window closes (Part 2 §1.6). The close date is derived the way `app/measurement.py`
does it: the apply day is the date of `applied_at`, falling back to
`measurement_started_at` (`_apply_date`, `app/measurement.py:77-81`); the post
window ends `MEASUREMENT_WINDOW_DAYS + ROLLOVER_SLOP_DAYS` = 21 + 1 = 22 days after
it (`reach.window_for`, `app/reach.py:59-81`, `ROLLOVER_SLOP_DAYS = 1` at
`app/reach.py:51`); and the audit holds while `today <= post_end`
(`plan_measurement`, `app/measurement.py:199-202`). So the first `measurement_eval`
(08:00 UTC) that can judge it is the day after `window_closes`, and only once reach
coverage has reached that day. The `+ 22` assumes the office `.env` doesn't
override `MEASUREMENT_WINDOW_DAYS`.

**[office]**

```sql
select v.channel_id, a.id as audit_id, a.video_id, v.title, a.measurement_status,
       (coalesce(a.applied_at, a.measurement_started_at) at time zone 'UTC')::date as applied_day,
       (coalesce(a.applied_at, a.measurement_started_at) at time zone 'UTC')::date + 22 as window_closes
from audits a join videos v on v.id = a.video_id
where a.measurement_status in ('awaiting_window', 'measuring')
order by window_closes, v.channel_id, a.video_id;
```

Raw result (paste):

```
```

**Acceptance check (24 h after the pause). [office]**

```
curl -s http://localhost:8000/channels/<channel_id>/autopilot/log
```

| Field | Value |
|---|---|
| Checked at (UTC) | |
| New audits or applies on the channel since the pause (must be none) | |

**SEO-team handover log** (spec A0 step 5, Part 2 §11.6). Fill only if the team
takes over the channel during the pause.

| Field | Value |
|---|---|
| Handover date | |

| Video | What changed | Date | By |
|---|---|---|---|
| | | | |

---

## A1 — Traffic-source probe

Probe channel `UCr5-YUqBiW7PUmeAtxUWuRg` (spec A1 step 1). Create the job on day one:
the first report can take a day or more.

### A1.1 Reporting API: `channel_traffic_source_a2`

| Field | Value |
|---|---|
| Date (job created) | |
| Date (first report inspected) | |
| Channel | `UCr5-YUqBiW7PUmeAtxUWuRg` |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**[dev]** Create or confirm the job (idempotent: an existing job for the type is
printed, not duplicated):

```
PYTHONPATH=. venv/bin/python scripts/create_reporting_job.py UCr5-YUqBiW7PUmeAtxUWuRg \
    --report-type channel_traffic_source_a2 --job-name midas-traffic-source
```

**[dev]** Once a report exists, inspect the newest one:

```
PYTHONPATH=. venv/bin/python scripts/probes/probe_traffic_source_report.py \
    UCr5-YUqBiW7PUmeAtxUWuRg --save traffic_source_a2_newest.csv
```

If the type column holds numeric codes, re-run with `--sample-value <code>` for each
code that the Reporting API docs map to related video, playlist, Shorts and search.

| Record | Value |
|---|---|
| Header row (verbatim) | |
| Distinct traffic-source-type values | |
| Detail column exists? Its name | |
| Detail for RELATED_VIDEO (or its real name) | |
| Detail for PLAYLIST | |
| Detail for SHORTS | |
| Detail for YT_SEARCH | |
| Sample rows (IDs are fine) | |
| Lag: data date vs create time (min / max / median days) | |

### A1.2 On-demand Analytics

| Field | Value |
|---|---|
| Date | |
| Channel | |
| Video (warm) | |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**[dev]** Pick a warm video (≥500 impressions in the last 30 days: the A7 warm-pool
query lists the channel's). Then:

```
PYTHONPATH=. venv/bin/python scripts/probes/probe_traffic_source_analytics.py \
    <channel_id> <warm_video_id>
```

| Variant | OK / HTTP status + message |
|---|---|
| 1. `dimensions=insightTrafficSourceType`, `filters=video==<id>` | |
| 2. `dimensions=day,insightTrafficSourceType`, `filters=video==<id>` | |
| 3. `insightTrafficSourceDetail`, `insightTrafficSourceType==RELATED_VIDEO` | |
| 3. `insightTrafficSourceDetail`, `insightTrafficSourceType==PLAYLIST` | |
| 3. `insightTrafficSourceDetail`, `insightTrafficSourceType==SHORTS` | |
| 3. `insightTrafficSourceDetail`, `insightTrafficSourceType==YT_SEARCH` (A3) | |

### A1.3 Description-link attribution

| Field | Value |
|---|---|
| Date | |
| Channel | |
| Referring video (has the link in its description) | |
| Target video (linked) | |
| Link added on (≥2 weeks ago) | |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**[dev]** Run the on-demand probe on the target video and look for the referring
video's id in the detail rows, and note the source type it appears under:

```
PYTHONPATH=. venv/bin/python scripts/probes/probe_traffic_source_analytics.py \
    <channel_id> <target_video_id>
```

Do the same in the A1.1 report CSV (`grep <referring_video_id> traffic_source_a2_newest.csv`).

### A1 outcome per lever (the exit gate needs one per row)

(a) views attributable to the referring video · (b) target-level totals by source
type only · (c) nothing usable. These map onto Part 2 §1.2.

| Lever | Outcome (a/b/c) | Source type and detail it rests on | Evidence (section) |
|---|---|---|---|
| Backlinks (description links) | | | |
| Playlist | | | |
| Short → video | | | |

---

## A2 — Short → video link field

| Field | Value |
|---|---|
| Date | |
| Channel | |
| Short (with a related video set in Studio) | |
| Linked video | |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**[dev]** Read-only; 1 Data API unit. Never attempt a write (spec A2 step 4).

```
PYTHONPATH=. venv/bin/python scripts/probes/probe_short_link.py <channel_id> <short_id> \
    --linked-video-id <linked_video_id> --out short_<short_id>.json
```

Then check the current `videos.update` reference for any writable field matching it.

| Question | Answer | Evidence |
|---|---|---|
| Readable? (yes/no; the JSON path) | | |
| Writable? (yes/no; the `videos.update` field, or its absence) | | |

---

## A3 — Search terms

| Field | Value |
|---|---|
| Date | |
| Channel | |
| Video (warm) | |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**[dev]** The `YT_SEARCH` variant of the A1.2 probe is this probe. To run only it:

```
PYTHONPATH=. venv/bin/python scripts/probes/probe_traffic_source_analytics.py \
    <channel_id> <warm_video_id> --type YT_SEARCH --rows 25
```

Also record what the A1.1 report's detail column holds for its search type.

| Question | Answer |
|---|---|
| Available? (yes/no) | |
| Shape (columns, granularity: per video, per day or per window) | |
| Minimum-volume suppression seen? | |
| Via the A1 report? | |

This decides whether `get_search_terms` (Part 2 §3.2) is built.

---

## A5 — Haryanvi channel `default_language`

| Field | Value |
|---|---|
| Date | |
| Channel | `UCc4Tv_DEGDEKrKAt-vyVNmw` |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**[dev]** The i18n probe (read-only, 1u):

```
PYTHONPATH=. venv/bin/python scripts/probes/probe_i18n_languages.py UCc4Tv_DEGDEKrKAt-vyVNmw
```

| `bgc` listed? | `hi` listed? |
|---|---|
| | |

**[office]** Set the value (`bgc` stays the content language; YouTube is sent `hi`
through `_NON_ISO_639_1`, `app/youtube_metadata.py`):

```sql
update channels set default_language = 'bgc'
where id = 'UCc4Tv_DEGDEKrKAt-vyVNmw'
returning id, name, default_language;
```

Then refresh the NAS snapshot, after verifying the UPDATE landed (CLAUDE.md). The
command, verbatim from CLAUDE.md:

```bash
# on-network (NAS_MODE=smb), after verifying the change landed correctly
PYTHONPATH=. venv/bin/python -c \
  "from app.backup import snapshot_to_nas; print(snapshot_to_nas())"
```

That form needs a repo checkout. On the office machine the same call runs in the
app container: `docker compose exec midas python -c "from app.backup import snapshot_to_nas; print(snapshot_to_nas())"`.

| Snapshot result (paste) | |
|---|---|

---

## A7 — Live numbers

| Field | Value |
|---|---|
| Date | |
| Channel | all |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome (rollout channel #1 and the reason) | |

**Dormancy literal, confirmed.** A dormant verdict stores
`measurement_result->>'reason_code' = 'dormant'`: the key is
`verdicts.REASON = "reason_code"` (`app/verdicts.py:47`), the value is
`REASON_DORMANT = "dormant"` (`app/measurement.py:170`), set at
`app/measurement.py:280`. The spec's literal is right as written.

**[office]** `docker compose exec db psql -U midas midas`, then the SQL block at the
end of `STATE.md` §8, verbatim:

```sql
-- channels live
select id, name, default_language, analytics_authorized, measurement_enabled, reach_warmup,
       playlist_health_enabled, autopilot_enabled, autopilot_paused_reason, autopilot_shorts_enabled
from channels order by name;

-- outcome volume + dormancy ratio
select measurement_status, measurement_result->>'reason_code' as reason, count(*)
from audits where status in ('applied','reverted') group by 1,2 order by 1,2;

-- per-channel outcomes
select v.channel_id, a.measurement_status, count(*)
from audits a join videos v on v.id=a.video_id
where a.measurement_status <> 'not_applicable' group by 1,2 order by 1,2;

-- reach frontier per channel
select channel_id, max(data_date) frontier, count(*) days_covered
from reporting_reports_ingested group by 1;

-- daily Data API burn, last 30 days
select date_trunc('day', occurred_at) d, sum(units) units, count(*) filter (where not success) failures
from quota_log where units > 0 and occurred_at > now() - interval '30 days' group by 1 order by 1;

-- quarantine + prompt versions
select status, count(*) from audits group by 1;
select channel_id, status, count(*) from prompt_versions group by 1,2;

-- playlist health freshness (stale until the fixed scorer deploys and runs)
select channel_id, max(health_computed_at), count(*) filter (where health_recommendation is not null)
from playlists group by 1;
```

Raw results (paste each):

```
```

**[office]** The two warm-pool queries from spec Part 1 A7:

```sql
-- warm pool size per channel (28 ingested days, ≥500 impressions)
select channel_id, count(*) warm_videos
from (select channel_id, video_id, sum(impressions) imp
      from video_reach_daily where date > current_date - 30 group by 1,2) t
where imp >= 500 group by 1 order by 2 desc;

-- how many applied audits in the last 90 days landed on dormant videos
select v.channel_id, count(*) filter (where a.measurement_result->>'reason_code' = 'dormant') dormant, count(*) total
from audits a join videos v on v.id = a.video_id
where a.applied_at > now() - interval '90 days' group by 1;
```

Raw results (paste):

```
```

| Rollout channel #1 | Reason |
|---|---|
| | |

---

## A9 — Deploy and verify the health-scorer fix

| Field | Value |
|---|---|
| Date (deploy) | |
| Date (first 07:00 UTC run after deploy) | |
| Channel | every `playlist_health_enabled` channel |
| Command / SQL | pre-filled in this section, below |
| Raw evidence | |
| Outcome | |

**[office]** After the first 07:00 UTC `playlist_health_score` run following the
deploy, the freshness query from `STATE.md` §8:

```sql
-- playlist health freshness (stale until the fixed scorer deploys and runs)
select channel_id, max(health_computed_at), count(*) filter (where health_recommendation is not null)
from playlists group by 1;
```

Every `playlist_health_enabled` channel must show `max(health_computed_at)` after
the deploy.

**[office]** The job registry (in-memory, cleared by a restart; `app/main.py:506`):

```
curl -s http://localhost:8000/health/jobs
```

Every registered job must appear, and `playlist_health_score` must show
`"status": "success"` with a `last_run_at` after the deploy. The frozen jobs
(`playlist_discovery`, `playlist_tuning`, `reflection`) must be absent.

| Record | Value |
|---|---|
| `max(health_computed_at)` per channel | |
| `/health/jobs` output (paste) | |

---

## Exit gate

Phase B starts only when all of these hold (spec Part 1, "Phase A exit gate"):

- [ ] `docs/PHASE_A_FINDINGS.md` answers A1–A3 with raw evidence and records an outcome — (a), (b), or (c) — per routing lever.
- [ ] A0 is done and recorded: no Midas applies on the channel for 24 hours after the change.
- [ ] A4–A6 and A8–A10 are merged, tests green, deployed to the office machine, and the frozen jobs are confirmed absent from the running scheduler's log.
- [ ] A9 shows fresh health scores, and `GET /health/jobs` reports every job's status.
- [ ] A11's doc changes are merged.
- [ ] A7 numbers are in the findings doc, and rollout channel #1 is chosen with the reason recorded.
- [ ] If A1 returns (c) for every routing lever, stop and revisit Part 2 before Phase B.
