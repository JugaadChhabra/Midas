# Midas — Continuous Improvement Loop

Turning the audit from a stateless, open-loop function (system prompt → suggestion)
into a closed loop that **senses** real outcomes, **remembers** what worked, and
**changes its behaviour** as a result.

Four layers, all spec'd below: **Loop 0 (sensor)**, **Loop 1 (per-video control
loop)**, **Loop 2 (per-channel memory)**, and **Loop 3 (process / meta loop)**.

| Loop | Role | What it is | State |
|---|---|---|---|
| 0 | Sensor | Per-video CTR / impressions / retention via Analytics API | **Spec below** |
| 1 | Per-video control loop | apply → measure → keep / revert / redo | **Spec below** |
| 2 | Per-channel memory | distill outcomes → channel "playbook" → fold into prompt | **Spec below** |
| 3 | Process / meta loop | version + eval + champion-challenger on the audit itself | **Spec below** |

> **Hard dependency:** Loops 1–3 are impossible without Loop 0. A continuous
> improvement loop with no measurable outcome is just a more elaborate guesser.
> Build 0 first.

---

## Why this exists (the constraints that shape every decision)

Two realities from YouTube's own guidance govern the design:

1. **Editing metadata on a video does not re-trigger distribution.** The algorithm
   responds to how the audience reacts to the new packaging, not to the act of
   editing. If a video has no live impressions, a better title converts nothing —
   *metadata cannot create demand that doesn't exist.* So the loop only operates on
   videos that are **currently getting impressions**; dormant videos are explicitly
   excluded from measurement and redo.
2. **The signal is slow, noisy, and confounded.** CTR effects take ~1–3 weeks to
   show, only exist on warm videos, and if title + description + tags change at once
   the result is attributable only to "the change as a whole." Design for a slow,
   deliberate experiment log — not a fast control loop.

---

## Loop 0 — Sensor (outcome instrumentation)

**Goal:** capture real per-video performance (impressions, CTR, retention) so any
change can be evaluated against ground truth. Today `performance.py` diffs cumulative
`viewCount` from the Data API — a monotonic number that can't isolate the effect of a
change and never exposes CTR at all. Loop 0 replaces that signal.

### 0.1 New OAuth scope + re-consent

- Current scope: `https://www.googleapis.com/auth/youtube`
- Add: `https://www.googleapis.com/auth/yt-analytics.readonly`

Existing per-channel refresh tokens were granted **without** the analytics scope, so
they will not authorize Analytics calls. Each channel must re-consent once.

- Request both scopes in `/auth/login`; keep `include_granted_scopes=true` for
  incremental auth.
- Track grant state per channel so we know who's ready:

```sql
ALTER TABLE channels
  ADD COLUMN IF NOT EXISTS analytics_authorized BOOLEAN DEFAULT FALSE;
```

- UI surfaces a "Reconnect for analytics" prompt on channels where this is false.
- **Graceful degradation:** until a channel is re-consented, Loop 0 (and therefore
  Loop 1) is simply skipped for it — consistent with the existing skip-on-missing
  pattern.

### 0.2 Analytics client — `app/analytics_client.py`

Thin wrapper, mirroring `youtube_client.py`:

```python
from googleapiclient.discovery import build

def _client(creds):
    return build("youtubeAnalytics", "v2", credentials=creds)

def video_reach(creds, video_id: str, start: str, end: str) -> dict | None:
    """Per-video reach + retention for a date window (YYYY-MM-DD)."""
    resp = _client(creds).reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics=",".join([
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "videoThumbnailImpressions",
            "videoThumbnailImpressionsClickRate",
        ]),
        dimensions="video",
        filters=f"video=={video_id}",
    ).execute()
    # parse columnHeaders + rows → dict; return None if no row
```

- `videoThumbnailImpressionsClickRate` is the impressions CTR. These two
  impression/CTR metrics were **added to the Analytics API on 2026-01-15** (per
  Google's Analytics API reference). **Before writing the abstraction, verify the
  exact metric names and that your channels return data with one live
  `reports.query` call** — same discipline the thumbnail plan applied to
  `chat_image_gen` (D.2). The metric set or naming is new enough to warrant a probe.
- **Quota:** the Analytics API has its own quota pool, **separate** from the Data API
  10k-unit/day budget. Loop 0 polling does **not** compete with audit/apply quota.

### 0.3 Storage — `video_metrics` (time series, not a snapshot)

We need trailing windows for baselines and to watch the measurement window evolve,
so store periodic windowed pulls rather than a single value.

```sql
CREATE TABLE video_metrics (
    id BIGSERIAL PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    channel_id TEXT NOT NULL REFERENCES channels(id),
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    impressions BIGINT,
    ctr FLOAT,                       -- videoThumbnailImpressionsClickRate
    views BIGINT,
    avg_view_duration_sec FLOAT,
    avg_view_pct FLOAT,
    is_pre_change BOOLEAN DEFAULT FALSE,   -- tagged baseline captured at apply
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (video_id, window_start, window_end)
);
```

- v1 cadence: **weekly windows** (trailing 7-day aggregate). Daily is finer but more
  rows/quota for a signal that already takes weeks; weekly is enough.

### 0.4 Scheduler job — `metrics_poll`

Register alongside the autopilot tick in the APScheduler lifespan.

- Runs daily; for each video currently **under measurement** (see Loop 1), pull its
  latest trailing window and upsert into `video_metrics`.
- Skips channels where `analytics_authorized = false`.
- Respects Analytics data lag (below).

### 0.5 Gotchas to encode

- **Data freshness lag:** Analytics data typically lags ~2 days. Never read CTR for
  the most recent 48h; offset window ends accordingly.
- **No CTR history before 2026-01-15:** pre-existing applied audits cannot be
  retro-evaluated on CTR. Loop 1 only applies going forward.
- **Statistical floor:** CTR on a handful of impressions is meaningless. Define
  `MIN_IMPRESSIONS` (start 500) below which a CTR delta is treated as "can't tell."

---

## Loop 1 — Per-video control loop (review / redo)

**Goal:** after an audit is applied, measure whether it helped, then keep wins,
revert regressions, and redo with a different angle.

### 1.1 State machine

Add a measurement sub-lifecycle as a **separate column** so the existing
`status` (`pending|applied|failed|quarantined`) and autopilot logic stay untouched.

```sql
ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS measurement_status TEXT DEFAULT 'not_applicable',
    -- not_applicable | awaiting_window | measuring | win | neutral | regression
  ADD COLUMN IF NOT EXISTS measurement_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS measurement_result JSONB,   -- deltas, sample sizes, rationale
  ADD COLUMN IF NOT EXISTS outcome_decision TEXT DEFAULT 'none',
    -- none | kept | reverted | redo_queued
  ADD COLUMN IF NOT EXISTS redo_of_audit_id BIGINT REFERENCES audits(id);
```

```
applied ─▶ awaiting_window ─▶ measuring ─┬─▶ win        ─▶ kept
                                         ├─▶ neutral    ─▶ kept (left as-is)
                                         └─▶ regression ─▶ reverted ─▶ redo_queued ─▶ (new audit)
```

`redo_of_audit_id` chains a redo back to the attempt it replaces, preserving the
failure→retry trajectory (fuel for Loop 2).

### 1.2 Baseline capture at apply

In addition to the existing `*_at_apply` stats baseline, capture a **pre-change
trailing CTR window** — the video's CTR/impressions over the N days *before* the
edit — and write it to `video_metrics` with `is_pre_change = true`. You can't A/B a
single video, so its own recent past is the control.

- If the video had ~no impressions pre-change → `measurement_status = 'not_applicable'`.
  Nothing to compare, nothing will move. This is where the "don't bother with dormant
  videos" rule is enforced in code.

### 1.3 Measurement window

- On apply (for eligible warm videos): `measurement_status = 'awaiting_window'`,
  `measurement_started_at = now()`.
- A scheduled **`measurement_eval`** job promotes audits whose window has elapsed
  (`MEASUREMENT_WINDOW_DAYS`, default **21**) and that accrued
  `>= MIN_IMPRESSIONS` post-change.
- Insufficient impressions even after the window → `neutral` (can't tell; don't
  penalize).

### 1.4 Decision policy (the critic)

Compare the post-change CTR window against the pre-change baseline window.

- v1: **relative-delta thresholds.** `CTR_WIN_THRESHOLD` (e.g. +10%),
  `CTR_REGRESSION_THRESHOLD` (e.g. -10%), with the `MIN_IMPRESSIONS` gate.
- v2 upgrade noted: a **two-proportion z-test** on (clicks, impressions) for real
  significance instead of a flat percentage.

| Outcome | Condition | `measurement_status` | `outcome_decision` |
|---|---|---|---|
| Win | CTR up ≥ threshold | `win` | `kept` (save as positive example) |
| Neutral | within noise band | `neutral` | `kept` (not worse — leave it) |
| Regression | CTR down ≤ -threshold | `regression` | `reverted` → queue redo |

**Confounding caveat:** if title + description + tags changed together, the result is
attributable only to the bundle. v1 treats an audit as one unit and learns at the
bundle level. For clean per-field causal attribution, change one field at a time
(slower) — flagged as an open question below.

### 1.5 Revert

`_revert_audit(audit_id)` in `audits.py`:

- Load the before-state snapshot, `videos.update` back to the original
  title/description/tags.
- Respect `DRY_RUN`.
- **Quota:** charge 50 units (`videos.update`) through the same quota gate as apply.
- Mark the video eligible for redo.

### 1.6 Redo

A redo is a fresh audit with the prior failure injected as context, e.g.:
*"Previous title `X` produced a CTR change of -8% over 3 weeks. Try a materially
different angle (e.g. curiosity-led rather than keyword-led)."*

- Cap with `MAX_REDO` (default **2**) to bound LLM/image spend and prevent thrashing.
- After the cap, stop and leave the last applied version; `outcome_decision` records
  exhaustion.

### 1.7 Autopilot integration

Extend the autopilot eligibility query in `autopilot.py`:

- **Exclude** videos in `awaiting_window` / `measuring` (don't churn a video
  mid-measurement).
- **Include** `redo_queued` audits as work items.
- Gate the whole loop behind a per-channel flag and roll out to **one channel first,
  monitor ~1 week**, then widen — same cadence as the thumbnail rollout.

### 1.8 Endpoints (manual / ops)

- `GET /audits/{id}/measurement` — status + deltas + rationale.
- `POST /audits/{id}/revert` — manual revert.
- `POST /audits/{id}/redo` — manual redo trigger.
- `GET /channels/{id}/outcomes` — win/neutral/regression rollup (also the Loop 2
  input and a UI stat).

### 1.9 Config / flags (`config.py`)

| Setting | Default | Notes |
|---|---|---|
| `MEASUREMENT_ENABLED` | per-channel | like the thumbnail flags |
| `MEASUREMENT_WINDOW_DAYS` | 21 | post-change window before eval |
| `MIN_IMPRESSIONS` | 500 | statistical floor for trusting a CTR delta |
| `CTR_WIN_THRESHOLD` | +0.10 | relative |
| `CTR_REGRESSION_THRESHOLD` | -0.10 | relative |
| `MAX_REDO` | 2 | per video |
| `AUTO_REVERT_ON_REGRESSION` | **false** | start human-review-first |

---

## Loop 2 — Per-channel memory (the playbook)

**Goal:** turn accumulated Loop 1 outcomes into a structured, per-channel **playbook**
that conditions the audit prompt on what has actually worked *on this channel* — so
suggestions regress toward proven winners instead of generic SEO priors. This is the
layer where the system stops being a fixed function and becomes a function of
evidence. The LLM generator does not change; it gains a memory.

### 2.1 What the playbook is

A structured JSON document, per channel, distilled from measured outcomes. **Not
training — retrieval + few-shot conditioning.** Contents:

- **Winning patterns:** title structures, length bands, language mix (channel
  language vs English), hook types (curiosity / outcome / number / contrarian),
  emoji / caps usage — each tied to the CTR evidence behind it.
- **Anti-patterns:** a distilled "avoid" list derived from regressions and low-CTR
  titles — expressed as *patterns*, not verbatim titles (verbatim losers anchor the
  model toward the bad thing).
- **Exemplars:** the channel's top-N highest-CTR titles, verbatim, as few-shot
  examples to emulate.
- **Thumbnail correlations:** which thumbnail styles co-occurred with CTR wins —
  correlational, and referencing the style profile rather than replacing it.

### 2.2 Storage

Mirror the `style_profile_json` decision — DB column, not disk (easier to ship
between machines):

```sql
ALTER TABLE channels
  ADD COLUMN IF NOT EXISTS playbook_json JSONB,
  ADD COLUMN IF NOT EXISTS playbook_built_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS playbook_outcome_count INT DEFAULT 0;
  -- ^ # of outcomes the *current* playbook was built from (drives rebuild trigger)
```

Keep `playbook_json` **distinct** from `style_profile_json`: the style profile is the
curated *brand reference* (built from reference thumbnails, aspirational); the
playbook is *measured reality* (what actually got clicks). Different provenance,
different trust. They inform each other; neither replaces the other.

### 2.3 Distillation — `app/playbook.py`

`build_playbook(channel_id)`:

1. Pull the channel's audits with `measurement_status in ('win','regression')`, plus
   their `measurement_result` deltas and before/after metadata, joined to
   `video_metrics`.
2. Rank: wins by CTR uplift, regressions by CTR drop.
3. Feed winners + losers (with their CTR deltas) to the LLM via the existing
   `chat_json` and ask for the structured playbook JSON. The LLM does the pattern
   abstraction — it is good at "what do these high-CTR titles have in common."
4. Persist to `channels.playbook_json`; stamp `playbook_built_at` and
   `playbook_outcome_count`.

The distiller prompt **must** state two things: (a) these CTR signals are
**bundle-level and correlational** — title + description + thumbnail moved together,
so describe patterns, don't claim causation; (b) the **language rule** — patterns must
respect the channel's `default_language`, same load-bearing rule as everywhere else.

### 2.4 Rebuild trigger

Data-driven, analogous to the style-profile folder-hash auto-rebuild but keyed on
outcome volume:

- **Lazy rebuild at audit time** when
  `(current outcome count) - playbook_outcome_count >= PLAYBOOK_REFRESH_DELTA`
  (e.g. 10 new measured outcomes since the last build). No manual button needed.
- Plus a weekly scheduled safety rebuild and a force endpoint for ops.

### 2.5 Cold start (critical)

A channel with too few measured outcomes cannot have a meaningful playbook — building
one from 2 data points just overfits noise.

- Gate: only build / inject when
  `outcome_count >= MIN_OUTCOMES_FOR_PLAYBOOK` (start **15–20** wins+regressions).
- Below the floor: **no playbook injection** — fall back to the current per-channel
  prompt. Graceful degradation, consistent with the transcript / analytics skip
  patterns.
- Because each outcome takes ~3 weeks (Loop 1's clock), a channel realistically takes
  **months** to accumulate enough. The playbook is a slow-maturing asset — expected,
  not a bug.

### 2.6 Injection into the audit prompt

The playbook is dynamic per-channel evidence, so it goes in `_build_user_block()`
(alongside the language rule and current metadata), **not** the static
`DEFAULT_PROMPT`:

- Prepend a **"WHAT WORKS ON THIS CHANNEL (evidence-based)"** block — winning patterns
  + anti-patterns.
- Append the top-N highest-CTR titles as few-shot exemplars ("emulate the packaging
  instinct, not the literal topic").
- Bound the token budget: cap exemplars (`PLAYBOOK_MAX_EXEMPLARS`) and pattern
  bullets.

### 2.7 Guardrails (decisions to remember)

- **Don't let the playbook collapse exploration.** If every suggestion imitates past
  winners, the channel converges to a local optimum and stops discovering new angles.
  Keep Loop 1's redo-angle diversity, and consider occasionally generating one
  divergent candidate. (This is the seam where Loop 3's experimentation plugs in.)
- **Correlational, not causal.** Bundle-level attribution (the v1 decision) means the
  playbook describes what *co-occurred* with wins, not what caused them. The distiller
  prompt says so explicitly.
- **Playbook ≠ style profile.** Measured vs curated. Keep separate; cross-reference.
- **Language rule survives distillation.** Patterns must respect `default_language`.

### 2.8 Config / flags (`config.py`)

| Setting | Default | Notes |
|---|---|---|
| `PLAYBOOK_ENABLED` | per-channel | gate injection (like the thumbnail flags) |
| `MIN_OUTCOMES_FOR_PLAYBOOK` | 15 | cold-start floor before a playbook exists |
| `PLAYBOOK_REFRESH_DELTA` | 10 | new outcomes before a lazy rebuild |
| `PLAYBOOK_MAX_EXEMPLARS` | 10 | few-shot title cap |

### 2.9 Endpoints

- `POST /channels/{id}/playbook/rebuild` — force rebuild (ops).
- `GET /channels/{id}/playbook` — inspect the current playbook JSON (debugging, plus a
  UI "what the system has learned about this channel" panel).

---

## Loop 3 — Process / meta loop (improving the audit itself)

**Goal:** make the audit *strategy* a versioned, testable artifact, so a change to the
prompt / model / generation logic must **prove it beats the incumbent on real
outcomes** before it rolls out fleet-wide. Loops 1–2 improve suggestions *within* a
fixed strategy; Loop 3 improves the strategy itself — and is the controlled outlet for
the exploration that Loop 2 would otherwise suppress.

### 3.1 Version the strategy — `audit_strategies`

A *strategy* is the machinery that produces a suggestion: prompt template + model +
generation/validation logic + which signals are injected. It is **not** the playbook —
the playbook is per-channel learned *data* (Loop 2); the strategy is the fixed
*generator*. A strategy change is "we restructured the prompt / swapped the model /
changed how candidates are generated," not "the playbook got new entries."

```sql
CREATE TABLE audit_strategies (
    version TEXT PRIMARY KEY,             -- e.g. "2026.06-curiosity-v3"
    prompt_template TEXT NOT NULL,
    model TEXT NOT NULL,
    config JSONB,                         -- playbook on/off, candidate count, thresholds
    status TEXT DEFAULT 'challenger',     -- champion | challenger | retired
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS strategy_version TEXT REFERENCES audit_strategies(version);
```

Stamp **every** audit with the `strategy_version` that produced it. Without this, no
Loop 1/2 outcome can be attributed to a strategy, and Loop 3 has nothing to compare.

### 3.2 Offline eval harness — `app/eval.py`

A cheap gate to kill obviously-worse strategies before they touch a live video. Two
signals, **neither of which sees real CTR**:

1. **LLM-as-judge (pairwise).** Run challenger and champion on a frozen held-out video
   set; have a **different-family** judge model pick the better suggestion head-to-head
   (clarity, click-appeal, fidelity to content, language-rule compliance). Pairwise
   preference is more stable than absolute scoring. Different family is a hard
   requirement — same-family judges rubber-stamp their own style (same rule as the
   thumbnail validator).
2. **Backtest sanity check.** For videos with known measured outcomes, check whether
   the challenger re-derives the patterns that historically won and avoids those that
   regressed. This is weak — you can't observe the counterfactual CTR of a title you
   never shipped — so treat it as a guardrail, not proof.

The frozen held-out set stays fixed across versions so scores are comparable; refresh
it only deliberately.

### 3.3 Online champion / challenger (the only real proof)

Because offline can't see CTR, the decisive test is live:

- Exactly one `champion` (default for all audits) and at most one `challenger`.
- Route a fixed fraction of eligible audits to the challenger — split by video-id hash
  so assignment is stable — and stamp each with its `strategy_version`.
- Let those audits flow through Loops 0/1 until they reach measured outcomes, then
  compare **win-rate / mean CTR uplift** between the two arms.
- **Promotion rule:** challenger must beat champion by `PROMOTION_MARGIN` with at least
  `MIN_OUTCOMES_FOR_PROMOTION` measured outcomes per arm → promote challenger, retire
  the old champion. Otherwise retire the challenger.

**Reality check on the clock.** The unit of evaluation is *audits that reached a
measured outcome* — warm videos only, ~3 weeks each. That's a trickle. A single
champion/challenger cycle is **weeks to months** and needs outcome volume pooled across
channels to get signal. This is the slowest loop in the system. Run **one challenger at
a time** — splitting scarce outcomes across parallel experiments yields no conclusions.

### 3.4 Interaction with the other loops

- **Loop 3 is where Loop 2's exploration-collapse is countered.** A challenger can
  deliberately encode more divergence (new angles, looser playbook adherence); you then
  measure whether that exploration actually pays.
- **Strategy regime vs playbook comparability.** Outcomes generated under an old
  strategy still feed the playbook. In practice the playbook smooths over this; if a
  strategy change is drastic, consider tagging playbook inputs with their
  `strategy_version` and weighting recent regimes. Flagged as an open question, not
  built in v1.

### 3.5 Endpoints (ops)

- `POST /strategies` — register a challenger.
- `POST /strategies/{version}/eval` — run the offline harness; return judge results +
  backtest.
- `GET /strategies/compare?champion=&challenger=` — live outcome rollup once data
  exists.
- `POST /strategies/{version}/promote` · `POST /strategies/{version}/retire`.

### 3.6 Config / flags (`config.py`)

| Setting | Default | Notes |
|---|---|---|
| `CHALLENGER_TRAFFIC_PCT` | 0.20 | share of eligible audits routed to the challenger |
| `MIN_OUTCOMES_FOR_PROMOTION` | 30 | measured outcomes *per arm* before deciding |
| `PROMOTION_MARGIN` | +0.05 | challenger win-rate must exceed champion by this |
| `EVAL_HELDOUT_SIZE` | 50 | videos in the frozen offline eval set |

---

## Decisions / non-obvious items to remember

1. **Loop 0 is the gate.** No sensor, no loop. Everything else is downstream of it.
2. **Only warm videos enter the loop.** Dormant videos get `not_applicable` — by
   design, not as a bug. Metadata can't move a video with no impressions.
3. **The video's own pre-change window is the baseline.** Single-video A/B is
   impossible; trailing self-comparison is the honest substitute.
4. **Analytics quota is a separate pool** from the Data API — polling is "free"
   against the audit/apply budget, but revert/redo writes still cost Data API units.
5. **No CTR before 2026-01-15.** Forward-only evaluation.
6. **Slow clock.** A meaningful result is ~3 weeks out. This is a deliberate
   experiment log, not a fast controller. Don't expect quick before/after movement.
7. **Auto-revert defaults OFF.** Surface regressions for human review first
   (mirrors `thumbnail_auto_apply` caution); enable auto-revert per-channel once
   trusted.
8. **The playbook (Loop 2) is the memory.** Loops 0/1 only produce evidence; Loop 2
   is what turns the audit from a fixed function into one that learns. Without it the
   suggestions never improve, no matter how much outcome data accrues.
9. **Channel intelligence matures in months, not days.** The 3-week measurement clock
   times the cold-start floor means a playbook is a slow-compounding asset. Don't
   expect a smart channel early.
10. **Strategy versions the machinery, not the playbook.** `strategy_version` covers
    prompt template + model + generation logic; the playbook is per-channel learned
    data. Stamp every audit with its strategy so outcomes are attributable.
11. **Offline eval can't see CTR.** The judge harness only gates suggestion *quality*;
    the online champion/challenger is the only real proof, and it's the slowest loop.
12. **One challenger at a time.** Outcome volume is far too low to split across
    parallel experiments — scarce measured outcomes must pool into a single comparison.

## Open questions (resolve before/while building)

- **Auto-revert vs human-review-first on regression.** Recommend human-first in v1.
- **One-field-at-a-time (clean attribution, slow) vs bundle (fast, coarse).**
  Recommend bundle in v1; document the attribution limit.
- **Polling cadence:** weekly windows on a daily job (recommended) vs daily windows.
- **Significance:** relative-threshold v1 → two-proportion test v2.
- **Playbook distilled by LLM vs computed statistically?** v1 recommends LLM
  distillation via `chat_json` (strong at pattern abstraction); revisit if it
  hallucinates patterns — a statistical pre-pass could filter inputs first.
- **Negative exemplars:** show verbatim loser titles or only distilled anti-patterns?
  v1 recommends distilled anti-patterns, to avoid anchoring on bad titles.
- **Judge model + scoring:** pairwise vs absolute, and which different-family judge?
  v1 recommends pairwise with a non-generator-family judge.
- **Playbook comparability across strategy regimes:** ignore (smooth over) vs tag
  playbook inputs with `strategy_version` and weight recent regimes. v1 ignores it.

---

## Build order (the whole plan, sequenced)

The loops form a strict dependency chain on a slow clock, so sequencing matters more
than usual:

1. **Loop 0 first, in full** — scope re-consent + `analytics_client.py` +
   `video_metrics` + `metrics_poll`. Nothing downstream works without the sensor.
2. **Loop 1 minimal slice** — baseline capture at apply + a `measurement_eval` job
   writing `win`/`neutral`/`regression`. Get real feedback flowing; keep auto-revert
   OFF.
3. **Let it run.** Outcomes accrue at ~3 weeks each. Use the wait to build the
   `/channels/{id}/outcomes` UI rollup and watch the signal before automating anything.
4. **Loop 2** once a channel crosses `MIN_OUTCOMES_FOR_PLAYBOOK` — distillation +
   prompt injection. This is the first point the audit visibly gets smarter.
5. **Loop 3 last** — only worth it once there are real strategies to compare and enough
   outcome volume to tell them apart. Premature champion/challenger on thin data just
   adds noise.

Roll every loop out **one channel first, ~1 week of watching, then widen** — the same
cadence as the thumbnail rollout.
