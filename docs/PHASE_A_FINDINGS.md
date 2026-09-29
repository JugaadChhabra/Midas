# Phase A — findings

Record of the human-run Phase A tasks in Part 1 of
`docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`: A0, A1–A3, A5,
A7 and A9. The code tasks (A4, A6, A8, A10, A11) are recorded in their PRs and in
`STATE.md`. Fill every blank from the run; paste raw evidence, don't paraphrase it.
If a probe fails, paste the exact error and list the variants tried (spec Part 1,
"Probe discipline").

## Restart day: do these steps in order

Everything below runs **on the office machine**, in PowerShell, in the Midas folder.
Where a step says "paste into psql", you're inside the database prompt from step 5.
Record what you see in the A0 section further down as you go.

### Before `start.bat`

**1. Open the Midas folder.**

```
cd "D:\My Data\Desktop\midas"
```

**2. Stop the old app if Docker restarted it by itself.** Every container is set to
`restart: unless-stopped`, so if the machine was shut down without `stop.bat`,
Docker Desktop brings the **old** Midas back at boot, and its autopilot starts
rewriting titles within 2 minutes. Check:

```
docker compose ps
```

- It says Docker isn't running: open Docker Desktop, wait until it shows "Engine
  running", then run `docker compose ps` again.
- A `midas` row shows `Up` or `running`: stop it right away:

  ```
  docker compose stop midas
  ```

- No `midas` row, or it shows `Exited`: nothing to do.

**3. Edit `.env`.**

```
notepad .env
```

- a. Find the line that starts with `STRATEGY_VERSION=`. **Delete the whole line.**
  (The app now reads `STRATEGY_LABEL`, which defaults to `2026.07-baseline`.) If
  there's no such line, skip this.
- b. Search (Ctrl+F) for each of these four names. If a line exists, **delete it.**
  If there's no line, do nothing:
  - `PLAYLIST_DISCOVERY_ENABLED`
  - `PLAYLIST_RECONCILE_WRITES_ENABLED`
  - `PLAYLIST_TUNING_ENABLED`
  - `REFLECTION_ENABLED`

  With the four missing, playlist creation, playlist add/remove, threshold tuning
  and prompt reflection all stay off. That's the intended state.
- c. Save and close Notepad.

Don't touch `docker-compose.yml`. It needs no change.

**4. Start only the database.**

```
docker compose up -d db
docker compose ps db
```

Wait until the `db` row says `healthy`. Run the second command again every few
seconds until it does.

**5. Open the database prompt.**

```
docker compose exec db psql -U midas midas
```

You should see a `midas=#` prompt. If it says `role "midas" does not exist`, use
the `POSTGRES_USER` value from `.env` in place of both `midas` words.

**6. See which channels have title autopilot on.** Paste into psql:

```sql
select count(*) as channels_total from channels;
select id, name, autopilot_enabled, autopilot_shorts_enabled, measurement_enabled
from channels where autopilot_enabled order by name;
```

- `channels_total` is **0**: the database is empty, and the app will restore it
  from the NAS on boot. Type `\q`, then **go to step 10b** instead of step 7.
- The second query shows rows: copy the ids into the A0 section. Go to step 7.
- The second query shows **no rows**: autopilot is already off. Skip step 7.

**7. Turn title autopilot off.** Paste into psql:

```sql
update channels set autopilot_enabled = false
where autopilot_enabled
returning id, name, autopilot_enabled, autopilot_shorts_enabled, measurement_enabled;
```

It must print the same channels as step 6, now with `autopilot_enabled` = `f`.
Leave `measurement_enabled` as it is.

*Optional: also pause Shorts uploads.* Shorts keep uploading unless you do this.
The spec allows either choice, because Shorts don't edit existing videos. To pause
them too, paste:

```sql
update channels set autopilot_shorts_enabled = false
where autopilot_shorts_enabled returning id, name;
```

**8. Record the videos still inside a measurement window.** This can be thousands of
rows, so don't try to read it on screen. First leave psql (type `\q`). Then run the
two commands below in PowerShell.

- a. **Summary: paste its output into the A0 section.** It's a few rows per channel:

  ```
  docker compose exec -T db psql -U midas midas -c "select v.channel_id, a.measurement_status, count(*) as videos, min((coalesce(a.applied_at, a.measurement_started_at) at time zone 'UTC')::date + 22) as first_window_closes, max((coalesce(a.applied_at, a.measurement_started_at) at time zone 'UTC')::date + 22) as last_window_closes from audits a join videos v on v.id = a.video_id where a.measurement_status in ('awaiting_window','measuring') group by 1,2 order by 1,2;"
  ```

- b. **Full list: saved to a file, not shown on screen.** Open it in Excel if you need
  to look. In the A0 section, write down only the file name:

  ```
  docker compose exec -T db psql -U midas midas --csv -c "select v.channel_id, a.id as audit_id, a.video_id, v.title, a.measurement_status, (coalesce(a.applied_at, a.measurement_started_at) at time zone 'UTC')::date + 22 as window_closes from audits a join videos v on v.id = a.video_id where a.measurement_status in ('awaiting_window','measuring') order by window_closes, v.channel_id, a.video_id;" | Set-Content -Encoding utf8 logs\a0-in-window.csv
  ```

  `-T` stops the scrolling pager. `Set-Content -Encoding utf8` keeps Indic titles
  readable: a plain `>` in Windows PowerShell writes UTF-16.

**9. You're already out of psql** (step 8 had you leave). Go on to step 10.

### Start the app

**10a. Normal case.** Run:

```
start.bat
```

Wait for `Service is healthy.` (or `Service started but may still be
initializing`). It pulls the new image by itself.

**10b. Only if step 6 found an empty database.** The app restores the NAS snapshot
on boot, and the restored channels will still have autopilot on. So give yourself
30 minutes before the first autopilot tick:

1. `notepad .env`, add the line `AUTOPILOT_TICK_SECONDS=1800` at the end, then save.
2. Run `start.bat` and wait for it to finish.
3. Run the step 7 update:

   ```
   docker compose exec db psql -U midas midas -c "update channels set autopilot_enabled = false where autopilot_enabled returning id, name;"
   ```

4. Run the two step 8 commands (8a and 8b).
5. `notepad .env`, delete the `AUTOPILOT_TICK_SECONDS=1800` line, save, then run
   `docker compose up -d midas` to restart the app with the normal tick.

### Straight after `start.bat` (5 minutes)

**11. Check the freeze took effect.**

```
docker compose logs midas | findstr /C:"not registered" /C:"registered for sync only"
```

You should see 4 lines: `playlist_discovery`, `playlist_tuning` and `reflection`
"not registered", and `playlist_reconcile` "registered for sync only". Fewer
lines means one of the four flags from step 3b is still in `.env`.

**12. Check the job health page.**

```
curl.exe -s http://localhost:8000/health/jobs
```

You should get JSON listing every job, mostly `"never_run"` at this point.

**13. Check autopilot stayed off.**

```
docker compose exec db psql -U midas midas -c "select id, name from channels where autopilot_enabled;"
```

It must print `(0 rows)`. Write the time into the A0 table as the pause timestamp.

**14. Create the A1 report job now,** because its first report takes a day or more.
This is the one YouTube write in Phase A, and it only subscribes the channel to a
daily report:

```
docker compose exec -e PYTHONPATH=/app midas python scripts/create_reporting_job.py UCr5-YUqBiW7PUmeAtxUWuRg --report-type channel_traffic_source_a2 --job-name midas-traffic-source
```

Copy the job id it prints into A1.1.

**Later.**
- **Tomorrow after 07:00 UTC:** do A9 (below).
- **24 hours after step 13:** do A0's acceptance check.
- **Once the first A1 report exists:** do A1.1's inspect step.

---

**Running the other probes.** The office machine isn't a git checkout, but the
image ships the repo's `scripts/`. The database only listens on the office machine
itself (`127.0.0.1`), so run every probe *inside the container*. Where a section
below shows `PYTHONPATH=. venv/bin/python scripts/<path> <args>`, run it there as:

```
docker compose exec -e PYTHONPATH=/app midas python scripts/<path> <args>
```

Write any output file under `/app/logs/`, which lands in the host's `logs\` folder.

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

**How to pause.** Follow steps 1–13 of "Restart day" at the top of this doc. Put the
channel ids from step 6 and the timestamp from step 13 in the table above.

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

Summary from restart-day step 8a (paste):

```
```

Full list saved to (step 8b): `logs\a0-in-window.csv` on the office machine.

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

**[office, in the container: see "Running the other probes"]** Create or confirm the job (idempotent: an existing job for the type is
printed, not duplicated):

```
PYTHONPATH=. venv/bin/python scripts/create_reporting_job.py UCr5-YUqBiW7PUmeAtxUWuRg \
    --report-type channel_traffic_source_a2 --job-name midas-traffic-source
```

**[office, in the container: see "Running the other probes"]** Once a report exists, inspect the newest one:

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

**[office, in the container: see "Running the other probes"]** Pick a warm video (≥500 impressions in the last 30 days: the A7 warm-pool
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

**[office, in the container: see "Running the other probes"]** Run the on-demand probe on the target video and look for the referring
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

**[office, in the container: see "Running the other probes"]** Read-only; 1 Data API unit. Never attempt a write (spec A2 step 4).

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

**[office, in the container: see "Running the other probes"]** The `YT_SEARCH` variant of the A1.2 probe is this probe. To run only it:

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

**[office, in the container: see "Running the other probes"]** The i18n probe (read-only, 1u):

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
