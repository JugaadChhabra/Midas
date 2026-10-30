# Phase B — findings

Evidence for Part 3 of `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` (Phase B, B1–B10).
Live figures were read on the office machine and are dated; nothing here was computed on a dev copy.
The office runbook these came from was `docs/agents/b9b-office-steps.md` (deleted 2026-10-30).

## Status

**Phase B is done: exit gate passed 2026-10-13** (checklist at the end). Part 4 (Slice 1) is ready to build.

Open follow-ups, none blocking Slice 1's build:
- #55: nginx `client_max_body_size` (batched vector upserts get 413). Needed before the sibling re-embed (S1.7 step 3).
- #57: retry dropped Reporting API downloads (`Server disconnected`).
- The traffic retention rule (below): approved 2026-10-13, not built yet.
- `metrics_poll` failed for Rajasthani `UCFO6AQ_KBQDEaQiTi-dBEWQ` on 2026-10-12; not investigated.

---

## Deploy record

**B9a (#40), 2026-10-07.** B1 + B8 deployed; `traffic_poll` registered at 05:35 UTC. First run 06:30 UTC:

- Marathi video feed: 36 data-days (2026-08-30 → 2026-10-04), 1,686,774 rows, 0 errors.
- Marathi playlist feed: 35 of 36 data-days, 4,303 rows. Data-day 2026-10-02 failed with
  `Server disconnected without sending a response.` and was retried by later runs (landed by 2026-10-13).
- Reporting jobs created for both report types on Bhojpuri, English, Gujarati and Hindi (D1).
- Status `degraded` (`playlist reports: 1/36 failed`).

**B9b (#41), 2026-10-07/08.**

- 5 migrations applied (`20261006020000` … `20261006060000`), PostgREST reloaded, app recreated.
- `default_language` set (step 7, owner's 2026-10-06 decision): Hindi, Bhojpuri, Rajasthani `hi`; Malayalam `ml`;
  Tamil `ta`; Telugu `te`. All 13 channels now have one.
- Marathi re-embed (B6) run, verified, calibrated (below).
- NAS snapshots: 2026-10-07 13:58 UTC `midas.0.sql` 910,523,271 bytes (migrations + languages);
  2026-10-08 06:24 UTC `midas.1.sql` 1,094,086,816 bytes (with the re-embed).

**Fix #56, deployed 2026-10-08.** On 2026-10-08 `video_sync` failed for 6 channels (Punjabi, Bhojpuri, Haryanvi,
Gujarati, Marathi, Tamil) with `HttpError 401 Invalid Credentials`; `reporting_poll` and `traffic_poll` hit
the same 401 on report downloads, worst on Gujarati, Bhojpuri and Tamil. Every channel's stored `token_expiry`
except Hindi's (re-consented 2026-10-06) was in **July**: the credentials were built without `expiry`, so
google-auth never refreshed a stored token up front and never saved one, and every call relied on the API
client's 401-retry. #56 passes the stored expiry (`youtube_client.channel_credentials`). The library versions
in the new image (google-auth-httplib2 0.4.4, httplib2 0.32.0) were diffed and don't touch the refresh path, so
what made the retry start failing is unconfirmed. On 2026-10-13 every job was `success`.

---

## B1 — traffic sources: size and retention

**Aggregated rows per data-day, Marathi** (`video_traffic_source_daily`, from the first run's log):
41,537–44,551 for 2026-09-09 → 10-04; 45,039–64,538 for 2026-08-30 → 09-08. `playlist_traffic_daily`:
70–175 rows a day.

**Size, 2026-10-13** (`pg_stat_user_tables`, 5 channels ingesting: Marathi 43 data-days, siblings 35–36):

| Table | Size | Rows (approx.) |
|---|---|---|
| `video_traffic_source_daily` | 4,766 MB | 14,969,306 |
| `playlist_traffic_daily` | 12 MB | 30,460 |

About 27 MB per channel-day, so ≈4 GB a month at 5 channels, carried into every nightly snapshot. Office disk on
2026-10-13: C 94.3 GB free, D 59.2 GB free.

**One data-day, by source type** (Marathi, 2026-10-10, 43,206 rows; "ours" = `source_detail` is a video in
`videos`, any channel):

| Type | Rows | Rows from our videos | Views |
|---|---|---|---|
| 14 Playlists | 21,699 | 0 (detail is a playlist id) | 121,343 |
| 7 Suggested | 19,021 | 1,731 | 45,572 |
| 24 Shorts feed | 664 | 0 | 71,515 |
| 3 Browse | 378 | 0 | 16,218 |
| 8 Other | 360 | 0 | 12,625 |
| 4 Channels | 355 | 0 | 2,700 |
| 5 Search | 269 | 0 | 3,668 |
| 9 External | 161 | 0 | 484 |
| 0 Direct | 107 | 0 | 2,563 |
| 18 Playlist pages | 79 | 0 | 151 |
| 20 End screens | 47 | 2 | 161 |
| 26 Hashtags | 14 | 0 | 27 |
| 27 Sound | 14 | 0 | 39 |
| 32 Related video | 12 | 12 | 24 |
| 17 Notifications | 6 | 0 | 7 |

**Retention decision (owner, 2026-10-13): collapse, don't delete.** Keep `source_detail` where something reads
it: type 7 from one of our videos, type 14 for one of our playlists or a Mix seeded from one of our videos, and
every row of every other type. Fold the rest into one row per (video, day, type) with `source_detail = ''`, so
per-type totals stay exact. Expected ≈5–6k rows per channel-day instead of ≈43k (≈0.6 GB for the current data).
Built at ingestion plus a one-off collapse of the existing rows (owner runs it). Known edge: a video not yet in
`videos` when its report lands is treated as not ours; sync runs ~2 days ahead of the report lag.

---

## B4 — warm pool

`warm_pool('UCr5-YUqBiW7PUmeAtxUWuRg', 500, 28, 21)` on 2026-10-13: **531** videos, floor 500 impressions,
top 7,303,586. A7's calendar-day query gave 566 on 2026-10-06; the filter counts ingested reach days and drops
episodes, so it was expected to differ.

## B6 — re-embed and calibration

**Estimate** (`scripts/reembed.py --estimate`, $0.20 per 1M input tokens, OpenRouter's listed price for
`google/gemini-embedding-2-preview`, 2026-10-07; tokens are UTF-8 bytes ÷ 3):

| Channel | Videos | Tokens | Cost |
|---|---|---|---|
| Marathi | 5,804 | 3,812,278 | $0.7625 |
| Hindi | 6,564 | 5,094,670 | $1.0189 |
| English | 5,905 | 3,810,602 | $0.7621 |
| Bhojpuri | 5,574 | 3,533,178 | $0.7066 |
| Gujarati | 6,468 | 3,849,983 | $0.7700 |

**Real run, Marathi, 2026-10-07 → 08.** Every batch of 50 failed on the database write with nginx's
`413 Request Entity Too Large` (≈3 MB of JSON against the 1 MB default) and fell back to one video at a time
(#55). The run took hours instead of minutes, and each batch's embeddings were paid for twice. Two reruns
cleared the stragglers (2 videos failed on a dropped connection). Final: 5,813 videos, `missing = 0` against
the warm pool, `exit=0`.

**Thresholds** (`channels.playlist_thresholds`, computed 2026-10-08 06:21:58 UTC):
`join_high 0.9014`, `join_low 0.8454`, `leave 0.8703`, from 5,176 member similarities over 82 playlists.
Ordered as expected, but the band is narrow: the house-format descriptions share hashtag and keyword blocks,
so every vector sits close to every other. These numbers describe members only; check the non-member
distribution before anything reads them (S1.1 reads `join_low`).

## B3 — human-edit ledger

`interventions` with `origin = 'human'`: 19 on 2026-10-08, **110 on 2026-10-13, all `lever = 'playlist'`**,
none `backlinks` yet.

**Hand check (owner, 2026-10-13):** the newest Marathi row, `QMmM8LeVak8` (S2 Ep 10), detected 2026-10-13
02:00 UTC as added to playlist `PLSj3WmpoNmuc…` ("Season 2 गोकुळधाम धमाल | Gokuldham Adventures | 4K |
Season 2"), is in that playlist in Studio. The spec's gate says "against the video's description"; with no
backlinks row yet, the check was made against playlist membership instead.

## B2 / B5

`assign_arm` and `decide()` have no production caller in Phase B (spec Part 3, "Not doing"), so
`decision_log` is empty and the gate's "`decide()` logs shadow decisions" is met by `tests/test_decide.py` only
(STATE.md §7.4).

## Job health after deploy

- 2026-10-11: `traffic_poll` degraded (Bhojpuri `video reports: 1/2 failed`, English `playlist reports: 1/5
  failed`); both days landed on later runs. `metrics_poll` degraded (Marathi `videos: 1/569 failed`).
- 2026-10-12: `metrics_poll` failed for Rajasthani (not investigated).
- 2026-10-13: every registered job `success`.

**Traffic frontier 2026-10-13** (`reporting_reports_ingested`, video / playlist feed, data-days):
Marathi 10-11 / 10-11 (43 / 43, no gaps from 2026-08-30); Hindi 10-11 / 10-10 (36 / 35); Bhojpuri
10-11 / 10-11 (36 / 36); English 10-10 / 10-10 (35 / 35); Gujarati 10-10 / 10-11 (35 / 36).

---

## Exit gate (spec Part 3), passed 2026-10-13

- [x] ≥7 consecutive Marathi data-days in `video_traffic_source_daily` from `traffic_poll`, and `success`:
  43 data-days 2026-08-30 → 10-11, no gaps; `success` 2026-10-13.
- [x] ≥1 human intervention checked by hand: `QMmM8LeVak8` → `PLSj3WmpoNmuc…`, owner, 2026-10-13.
- [x] B1–B8 merged and deployed; migrations applied; PostgREST reloaded; NAS snapshot refreshed (2026-10-08).
- [x] `assign_arm` stable and `decide()` logs shadow decisions: by tests (above).
- [x] Warm pool (531) and B1 storage (4,766 MB) recorded, with the retention decision.
