# Phase 2 · Track 4 — Memory + Meta Loops — Implementation Checklist

**Status:** DRAFT — to be reviewed before any implementation work begins.
**Spec sources of record:** `docs/CONTINUOUS_IMPROVEMENT_LOOP.md` §Loop 2 / §Loop 3
(the "meta / process loop"), `docs/PLAYLIST_OPTIMIZATION.md` §Memory (Loop 2, for
playlists) / §Meta loop (Loop 3, for playlists).
**Substrate already shipped:** Loop 0 sensor + Loop 1 measurement (`measurement.py`,
`video_reach_daily`, `audits.measurement_status`/`measurement_result`), the
`audit_strategies` table + per-audit `strategy_version` stamping (Phase 1A
migration `20260702183233_phase1a_loop1_measurement.sql`), and the
`reflection.py` per-channel prompt champion/challenger machinery
(`prompt_versions` + shadow/live/auto + auto-revert).

> This is an **implementation checklist**, modelled on `docs/PHASE_1B_PLAN.md`:
> numbered IMPLEMENT → REVIEW steps, exact `file:line` seams, spec quotes for
> grounding, and a discipline checklist to carry into PRs. Every seam below was
> read and verified against the codebase before this doc was written.

---

## 0. Read this first — two things that change how you build this track

### 0.1 ⚠️ The payoff is gated on MONTHS of accrued outcomes, not on the ~10–12 build days

The build for all three sub-pieces is roughly **10–12 engineer-days**. **That number
is a trap if read alone.** None of it produces value until real measured outcomes
exist to distill and compare, and each outcome takes **~3 weeks** (metadata,
`MEASUREMENT_WINDOW_DAYS=21`) to **~5 weeks** (playlists,
`PLAYLIST_MEASUREMENT_WINDOW_DAYS=35`) to mature — *per outcome*, and cold-start
floors need 15–30 of them **pooled**.

CIL says this in its own words:

> **Reality check on the clock.** The unit of evaluation is *audits that reached a
> measured outcome* — warm videos only, ~3 weeks each. That's a trickle. A single
> champion/challenger cycle is **weeks to months** and needs outcome volume pooled
> across channels to get signal. This is the slowest loop in the system.
> (`CONTINUOUS_IMPROVEMENT_LOOP.md` §3.3)

> Because each outcome takes ~3 weeks (Loop 1's clock), a channel realistically
> takes **months** to accumulate enough. The playbook is a slow-maturing asset —
> expected, not a bug. (`CONTINUOUS_IMPROVEMENT_LOOP.md` §2.5)

**Consequences that must shape sequencing and expectations:**

- **Build the machinery; do not expect it to *do* anything for months.** Loop 2
  injects nothing below `MIN_OUTCOMES_FOR_PLAYBOOK`; Loop 3 cannot promote below
  `MIN_OUTCOMES_FOR_PROMOTION`. Both graceful-degrade to today's behaviour until
  the data arrives.
- **Do not tune thresholds on thin data.** The first months produce noise.
  Thresholds (`PROMOTION_MARGIN`, percentile cutoffs, `CTR_*_THRESHOLD`) get one
  honest calibration pass only after real volume accrues.
- **Ship the read/inspect endpoints early** so operators can *watch the data fill*
  and gain confidence before any automated promotion/injection turns on.
- **One challenger at a time** (Loop 3). Splitting scarce pooled outcomes across
  parallel experiments yields no conclusions (CIL §3.3 "Decisions" #12).

### 0.2 ⚠️ `style_profile_json` DOES NOT EXIST — mirror `reflection.py`, not the phantom

Both spec docs repeatedly say to "mirror the `style_profile_json` decision"
(`CONTINUOUS_IMPROVEMENT_LOOP.md` §2.2; `PLAYLIST_OPTIMIZATION.md` §Memory,
"kept distinct, like `style_profile_json` vs `playbook_json`").

**There is no `style_profile` anywhere in the codebase.** Verified:
`grep -rn style_profile app/` → **zero hits**; the string appears *only* in
`docs/CONTINUOUS_IMPROVEMENT_LOOP.md` and `docs/PLAYLIST_OPTIMIZATION.md`. It is a
documentation-only reference to a pattern that was never built. Do **not** search
for it, import it, or model your storage on it.

**The real, buildable analog already in the repo is `app/reflection.py` +
the `prompt_versions` table.** It is a per-channel **LLM-distillation-into-a-DB-
column plus a weekly job** pattern that *already* implements
champion/challenger-with-auto-revert over prompt text:

- **Distill-into-a-column:** `derive_niche_queries` (`reflection.py:172-214`)
  runs `chat_json` over the channel's own content and `UPDATE`s a jsonb column
  (`audit_configs.niche_queries`). **This is the exact shape Loop 2's
  `build_playbook` should copy** — LLM in, structured column out.
- **Champion/challenger + auto-revert:** `_run_shadow_audits`
  (`reflection.py:400-436`, tags candidates via `prompt_version_id`
  `:428-430`), `_cohort_median_lift` (`reflection.py:441-498`, per-version cohort
  metric with a `_MIN_DATA_POINTS` floor), `_check_auto_revert`
  (`reflection.py:501-568`, promote/retire by status). **This is the exact shape
  Loop 3's compare/promote should copy** — cohort metric per version, floor-gated,
  status-driven promotion.

Wherever the spec says "style profile," read **"`reflection.py` + `prompt_versions`
pattern"** and mirror that.

---

## 1. Shared idioms (use these; do not reinvent)

These are the load-bearing conventions every step below assumes. Verified seams:

| Concern | Idiom | Seam |
|---|---|---|
| DB handle | `from app.db import supabase` then `supabase().table("X").select/upsert/update(...).execute()` | throughout |
| Idempotent seed/insert | `.upsert({...}, on_conflict="version", ignore_duplicates=True)` — never overwrite a curated row | `audits.py:199-209` |
| Paging past the 1000-row cap (by hand) | `offset`/`range(offset, offset+PAGE-1)` loop, `PAGE=1000`, break when `len(page) < PAGE` | `measurement.py:99-114`, `measurement.py:344-382` |
| Paging (helper) | `fetch_all(query_builder)` / `audits_for_channel(channel_id, cols)` | `reflection.py:451`, import `reflection.py:8` |
| `audits` has **no `channel_id`** | scope by video-ids-of-channel, chunk `.in_(...)` in ≤100–500 id batches | `measurement.py:344-382` (100s), `reflection.py:460-471` (500s) |
| Exclude non-measured outcomes | `.neq("measurement_status", "not_applicable")` | `measurement.py:373` |
| LLM (structured) | `chat_json(prompt, model=None, system=None, image_urls=None) -> dict` — forces `json_object`, default `settings.AUDIT_MODEL` | `openrouter.py:31-85` |
| LLM (raw text) | `chat_text(prompt, model=None, system=None) -> str` | `openrouter.py:88-117` |
| LLM judge with an explicit model | `chat_json(prompt, model=JUDGE_MODEL)` | `playlists.py:251` |
| **No image generation exists** | there is **no `chat_image_gen`** anywhere — do not reference it | verified absent |
| Per-channel DB boolean gate | column on `channels`, `boolean default false`, one-channel-first | `channels.measurement_enabled`, `20260702183233...:56-57` |
| Config knob | `os.getenv("X") or default` in `app/config.py` `Settings` | `config.py:29-31, :166-168` |
| Router registration | each module has `router = APIRouter(...)`; register in `main.py` | `main.py:324-335` |
| Weekly cron precedent | `scheduler.add_job(fn, "cron", day_of_week="mon", hour=N, minute=0, id="...", max_instances=1, coalesce=True)` | `_weekly_reflection` `main.py:213-222` |
| UTC-pinned daily cron precedent | same, `"cron", hour=N, timezone="UTC"` | `poll_metrics` `main.py:223-243`, `playlist_health_score` `main.py:263-281` |

**Migration convention:** files are `supabase/migrations/<UTCstamp>_<name>.sql`,
every op is `add column if not exists` / `create table if not exists` /
`create index if not exists`. **Latest existing stamp is `20260728010000`** — every
new migration must sort strictly after it (e.g. `20260730000000_...`).

---

## 2. Sub-piece map, effort, and dependency graph

| Sub-piece | What it is | Rough effort | Depends on |
|---|---|---|---|
| **Loop 2 — metadata playbook** | Distill measured metadata outcomes → per-channel `playbook_json` → inject into the audit prompt | ~3–4 days | Loop 1 outcomes (shipped); nothing else in this track |
| **3B — playlist playbook** | Same, for playlists | ~1.5 days | **BLOCKED** on Track 3's **2B** (construction prompt = injection target) and **2C** (`playlist_interventions` outcomes) |
| **Loop 3 — meta / champion-challenger** | Version the *strategy* (prompt+model), route challenger traffic, offline eval + online compare/promote | ~5–6 days | Loop 1 outcomes; **payoff gated on outcome VOLUME** (§0.1) |

**Recommended build order:** Loop 2 → Loop 3 → 3B (3B last because it is blocked on
Track 3 landing regardless). Loop 2 and Loop 3 are independent to build; both are
independent of Track 3.

---

# SUB-PIECE A — LOOP 2: metadata playbook (~3–4 days)

**Spec:** `CONTINUOUS_IMPROVEMENT_LOOP.md` §2 (2.1–2.9).

> **Goal:** turn accumulated Loop 1 outcomes into a structured, per-channel
> **playbook** that conditions the audit prompt on what has actually worked *on this
> channel* … The LLM generator does not change; it gains a memory. (§2, opening)

### Goals

1. New `channels.playbook_json` distilled from measured `win`/`regression` outcomes.
2. Inject a "WHAT WORKS ON THIS CHANNEL" block into the audit prompt, gated behind a
   per-channel flag + a cold-start floor.
3. Lazy rebuild keyed on outcome-count drift, plus a weekly safety rebuild.
4. Ops endpoints to force-rebuild and inspect.

### Non-goals

- No change to the LLM generator / `DEFAULT_PROMPT` static text (playbook is
  *dynamic per-channel* evidence → belongs in `_build_user_block`, not the system
  prompt — §2.6).
- No causal claims: attribution is **bundle-level and correlational** — the data
  literally carries `"attribution": "bundle"` (`measurement.py:198-209`). The
  distiller prompt must say so (§2.3).
- No thumbnail-style-profile cross-reference (phantom — §0.2). Drop that bullet from
  §2.1's "thumbnail correlations."
- No exploration-collapse: keep the door open for Loop 3 divergence (§2.7); Loop 2
  only conditions, it does not hard-constrain.

### Migration

`supabase/migrations/20260730000000_loop2_playbook.sql` (adjust stamp to sort after
`20260728010000`). Mirror the CIL §2.2 block **but with `reflection.py` idioms, not
`style_profile`**:

```sql
alter table channels
  add column if not exists playbook_json jsonb,
  add column if not exists playbook_built_at timestamptz,
  add column if not exists playbook_outcome_count int default 0,
  add column if not exists playbook_enabled boolean default false;
```

`playbook_outcome_count` = number of outcomes the *current* playbook was built from
(drives the lazy rebuild trigger). `playbook_enabled` mirrors
`channels.measurement_enabled` (`20260702183233...:56-57`).

### Config (`app/config.py`)

Add to `Settings`, `os.getenv(...) or default` style (see `config.py:29-31`):

| Setting | Default | Notes |
|---|---|---|
| `MIN_OUTCOMES_FOR_PLAYBOOK` | `15` | cold-start floor before a playbook is built/injected (§2.5) |
| `PLAYBOOK_REFRESH_DELTA` | `10` | new outcomes since last build before a lazy rebuild (§2.4) |
| `PLAYBOOK_MAX_EXEMPLARS` | `10` | few-shot title cap (§2.6) |

`PLAYBOOK_ENABLED` is the **per-channel DB column** `channels.playbook_enabled`
above (not an env var), mirroring `measurement_enabled` — §2.8 says "per-channel …
like the thumbnail flags."

### Endpoints

| Method + path | Purpose | Router |
|---|---|---|
| `POST /channels/{id}/playbook/rebuild` | force rebuild (ops) | reuse `audits.py`'s `router` (co-located with `audit_video`), or a small new `playbook_router` registered at `main.py:324-335` |
| `GET /channels/{id}/playbook` | inspect current `playbook_json` (debug + UI panel) | same |

### Steps

**Step A.1 — Migration.** Author the idempotent `ALTER TABLE channels` set above.
*Effort: ~0.5 day.*
*REVIEW:* applies cleanly to a clone; pre-existing channels have `playbook_json` NULL,
`playbook_outcome_count = 0`, `playbook_enabled = false`.

**Step A.2 — `app/playbook.py` : `build_playbook(channel_id)`.** Mirror
`derive_niche_queries` (`reflection.py:172-214`) — pull inputs, `chat_json`, write a
column. Specifics:
- **Scope outcomes by video-ids-of-channel** (audits have no `channel_id`) using the
  `channel_outcomes` shape (`measurement.py:344-382`): page all `videos.id` for the
  channel, then chunk `.in_()` over the `audits` table in 100-id batches.
- Filter `measurement_status in ('win','regression')` and
  `.neq("measurement_status","not_applicable")` (`measurement.py:373`). Pull
  `measurement_result` (carries `pre_window`/`post_window` ctr,
  `ctr_delta_relative`, and `"attribution":"bundle"` — `measurement.py:198-224`) plus
  the before/after metadata.
- Rank wins by CTR uplift, regressions by drop; feed to `chat_json` for the structured
  playbook JSON.
- **Distiller prompt MUST encode two things** (§2.3): (a) signals are *bundle-level,
  correlational* — describe patterns, don't claim causation (the input data tags
  `attribution:"bundle"`); (b) the **language rule** — patterns must respect the
  channel's `default_language` (the same load-bearing rule as
  `_build_user_block` `audits.py:142-150`).
- Persist: `UPDATE channels SET playbook_json=..., playbook_built_at=now(),
  playbook_outcome_count=<live count>` (same `.update().eq("channel_id",...)` idiom as
  `reflection.py:209-211`).
*Effort: ~1.5 days.*
*REVIEW:* run against a channel with ≥15 outcomes (or a fixture); eyeball the JSON;
confirm the distiller prompt contains the bundle-caveat + language-rule sentences;
confirm `playbook_outcome_count` matches the live filtered count.

**Step A.3 — Inject into the audit prompt.** Thread a `playbook: dict | None = None`
param into `_build_user_block` (`audits.py:132-181`).
- The block **goes right AFTER the LANGUAGE RULE** (~`audits.py:151`, before VIDEO
  METADATA at `:152`) — keep the language rule first and load-bearing. Prepend a
  **"WHAT WORKS ON THIS CHANNEL (evidence-based)"** section (winning patterns +
  anti-patterns).
- **Exemplars** (top-N highest-CTR titles) append near the closing block (~`:173`),
  capped by `PLAYBOOK_MAX_EXEMPLARS`.
- In `audit_video` (`audits.py:217`): fetch `channels.playbook_json` +
  `playbook_outcome_count` + `playbook_enabled` **alongside the existing
  `default_language` fetch** (`audits.py:238-241`). Inject only when
  `playbook_enabled` is true **and** live outcome count ≥ `MIN_OUTCOMES_FOR_PLAYBOOK`;
  otherwise pass `playbook=None` — graceful degradation exactly like the
  transcript-missing branch (`audits.py:167-171`).
*Effort: ~0.75 day.*
*REVIEW:* below the floor / flag off → prompt is byte-identical to today's; above the
floor → block present, language rule still first, exemplar count ≤ cap.

**Step A.4 — Lazy + weekly rebuild.** In `audit_video` (`audits.py:217`, near the
playbook fetch), compare live outcome count vs `channels.playbook_outcome_count`; if
`live - stored >= PLAYBOOK_REFRESH_DELTA`, call `build_playbook(channel_id)` before
building the block. Add a **weekly safety rebuild** cron next to `_weekly_reflection`
(`main.py:213-222`, `day_of_week="mon"`) iterating `playbook_enabled` channels.
*Effort: ~0.5 day.*
*REVIEW:* crossing the delta triggers exactly one rebuild; weekly job skips
flag-off channels silently; `max_instances=1, coalesce=True` set.

**Step A.5 — Endpoints.** `POST /channels/{id}/playbook/rebuild` (force) +
`GET /channels/{id}/playbook` (read). Recommend-safe: no YouTube writes.
*Effort: ~0.5 day.*
*REVIEW:* curl both; rebuild stamps `playbook_built_at`; GET returns stored JSON.

---

# SUB-PIECE B — 3B: playlist playbook (~1.5 days)

**Spec:** `PLAYLIST_OPTIMIZATION.md` §Memory (Loop 2, for playlists) + §Meta loop.

> ⛔ **BLOCKED — do not start until Track 3 lands both:**
> - **2B (construction pipeline)** — its construction prompt is the *injection
>   target*; it does not exist until 2B ships. There is nothing to inject into today.
> - **2C (intervention outcomes)** — `playlist_interventions` win/regression rows are
>   the *distillation input*; the table is created in 2C, not before
>   (`PHASE_1B_PLAN.md` §1 non-goals explicitly excludes it from 1B).

This sub-piece is a near-mechanical mirror of Loop 2 (Sub-piece A) but for playlists.
Build it *after* A so you copy a working shape.

### Goals

1. `channels.playlist_playbook_json` distilled from measured playlist-intervention
   outcomes.
2. Inject into the 2B construction prompt; the **measured playbook OVERRIDES the
   competitor reference (inferred) on conflict** (§Memory: "The playbook overrides on
   conflict").
3. Below the cold-start floor, fall back to
   `channels.playlist_competitor_reference_json` + generic construction logic.

### Non-goals

- No new sensor / no touching `playlist_metrics` (Loop 0 already ships it).
- No competitor-reference build (that is Track 3 requirement 2, separate).

### Migration

`supabase/migrations/20260730010000_3b_playlist_playbook.sql` (mirror
`PLAYLIST_OPTIMIZATION.md` §Memory):

```sql
alter table channels
  add column if not exists playlist_playbook_json jsonb,
  add column if not exists playlist_playbook_built_at timestamptz;
```

(`playlist_competitor_reference_json` / `playlist_competitor_built_at` are owned by
Track 3, not created here.)

### Config (`app/config.py`)

| Setting | Default | Notes |
|---|---|---|
| `MIN_OUTCOMES_FOR_PLAYLIST_PLAYBOOK` | `10` | cold-start floor; longer (~5-week) clock than metadata (§Memory) |
| `PLAYLIST_PLAYBOOK_REFRESH_DELTA` | `5` | new outcomes before a lazy rebuild |

### Endpoint

| Method + path | Purpose |
|---|---|
| `GET /channels/{id}/playlist-playbook` | inspect current playlist playbook JSON |

### Steps

**Step B.1 — Migration.** Idempotent `ALTER TABLE channels` above.
*Effort: ~0.25 day.* *REVIEW:* applies clean; columns NULL for existing rows.

**Step B.2 — `app/playlist_playbook.py` : `build_playlist_playbook(channel_id)`.**
Copy the Sub-piece A `build_playbook` shape, but distill `win`/`regression` rows from
the **`playlist_interventions` rollup that 2C's `/outcomes` exposes** (source of
truth for playlist outcomes) via `chat_json` → `channels.playlist_playbook_json`.
Distiller prompt encodes the same two caveats (bundle-level attribution — see
`PLAYLIST_OPTIMIZATION.md` §"Attribution caveat"; and `default_language`).
*Effort: ~0.75 day.* *REVIEW:* run against a channel with playlist outcomes; JSON
records roles/length-bands/opener/sequencing/naming patterns tied to start-lift.

**Step B.3 — Inject into the 2B construction prompt.** Mirror the `_build_user_block`
injection shape (`audits.py:132-181`). The playbook block (measured) is placed so it
**overrides** the competitor-reference block (inferred) on conflict; below
`MIN_OUTCOMES_FOR_PLAYLIST_PLAYBOOK`, inject nothing and let 2B fall back to
`playlist_competitor_reference_json` + generic logic.
*Effort: ~0.25 day.* *REVIEW:* with a playbook present, construction prompt shows the
override precedence; below floor, prompt is identical to 2B's default.

**Step B.4 — Endpoint + rebuild trigger.** `GET /channels/{id}/playlist-playbook`;
lazy rebuild on `PLAYLIST_PLAYBOOK_REFRESH_DELTA` drift at construction time; optional
weekly safety rebuild folded into the same weekly cron as A.4.
*Effort: ~0.25 day.* *REVIEW:* endpoint returns stored JSON; delta triggers one
rebuild.

---

# SUB-PIECE C — LOOP 3: meta / champion-challenger (~5–6 days)

**Spec:** `CONTINUOUS_IMPROVEMENT_LOOP.md` §3 (3.1–3.6);
`PLAYLIST_OPTIMIZATION.md` §Meta loop.

> ⏳ **Gated on outcome VOLUME.** Build the machinery now; it cannot *promote*
> anything until `MIN_OUTCOMES_FOR_PROMOTION` measured outcomes exist **per arm**,
> which is weeks-to-months out (§0.1). Ship the register/eval/inspect endpoints first
> so operators watch the arms fill before any promotion fires.

### What is ALREADY built (do not rebuild)

- **`audit_strategies` table** (`20260702183233...:13-25`): `version` PK,
  `prompt_template`, `model`, `config jsonb`, `status default 'challenger'`, `notes`,
  `created_at`. Seeded champion `'2026.07-baseline-v1'` (`:28-36`, model
  `anthropic/claude-haiku-4.5`). FK `audits.strategy_version -> audit_strategies` (`:46`).
- **Stamping site (THE single one):** `audits.py:274` writes
  `"strategy_version": settings.STRATEGY_VERSION` (`config.py:168`) on **every**
  audit insert (`audits.py:262-276`).
- **FK-safety:** `_ensure_strategy_row` (`audits.py:184-214`, champion-biased,
  `ignore_duplicates=True`) called at the top of `audit_video` (`audits.py:219`).

`audit_video` currently always uses `settings.STRATEGY_VERSION` +
`generated_prompt`/`DEFAULT_PROMPT` (`audits.py:231-236`) + `settings.AUDIT_MODEL`.

### Goals

1. **Challenger routing** at the single stamping site: deterministic video-id hash
   decides champion vs challenger; when challenger, override
   `strategy_version` + prompt_template + model from the challenger's
   `audit_strategies` row.
2. **Offline eval** (`app/eval.py`): pairwise LLM-as-judge over a frozen held-out set
   + a backtest sanity check.
3. **Online compare/promote**: cohort metric per `strategy_version`, floor-gated,
   promote/retire — mirroring `reflection.py`.
4. Ops endpoints + a new router.

### Non-goals

- No parallel challengers — **one challenger at a time** (§3.3, "Decisions" #12).
- Offline eval does **not** see CTR — it gates suggestion *quality* only; online is
  the only real proof (§3.2, "Decisions" #11).
- No fleet-wide rollout of a challenger before it clears the online margin.

### Migration

`supabase/migrations/20260730020000_loop3_champion_challenger.sql`. The table exists;
this migration only **enforces the invariant the spec assumes but the DB does not**:

> Exactly one `champion` (default for all audits) and at most one `challenger`.
> (§3.3)

`audit_strategies.status default 'challenger'` + the champion-biased seed +
`_ensure_strategy_row` do **not** enforce this. Add a partial unique index (or
enforce in app):

```sql
create unique index if not exists audit_strategies_one_champion_idx
  on audit_strategies (status) where status = 'champion';
-- Optionally the same for status = 'challenger' (at most one).
```

### Config (`app/config.py`)

| Setting | Default | Notes |
|---|---|---|
| `CHALLENGER_TRAFFIC_PCT` | `0.20` | share of eligible audits routed to the challenger (§3.6) |
| `MIN_OUTCOMES_FOR_PROMOTION` | `30` | measured outcomes **per arm** before deciding (§3.6) |
| `PROMOTION_MARGIN` | `0.05` | challenger win-rate must exceed champion by this (§3.6) |
| `EVAL_HELDOUT_SIZE` | `50` | frozen offline eval set size (§3.6) |
| `EVAL_JUDGE_MODEL` | `os.getenv("EVAL_JUDGE_MODEL") or "google/gemini-2.0-flash-001"` | **different-family** judge (generator = Anthropic/Claude); reuse the already-wired Gemini id from `PROMPT_GEN_MODEL` (`config.py:30`) but as its own knob, not hardcoded |

### Endpoints (new router — register at `main.py:324-335`)

| Method + path | Purpose |
|---|---|
| `POST /strategies` | register a challenger row |
| `POST /strategies/{version}/eval` | run the offline harness; return judge results + backtest |
| `GET /strategies/compare?champion=&challenger=` | live outcome rollup once data exists |
| `POST /strategies/{version}/promote` | promote challenger, retire old champion |
| `POST /strategies/{version}/retire` | retire a strategy |

### Steps

**Step C.1 — Migration (invariant only).** Partial unique index above.
*Effort: ~0.25 day.* *REVIEW:* attempting a 2nd `champion` row fails; existing seed
unaffected.

**Step C.2 — Register-challenger endpoint + `POST /strategies`.** Insert a new
`audit_strategies` row **with explicit `status='challenger'`**. ⚠️ Do **not** rely on
`_ensure_strategy_row` (`audits.py:184-214`) — it is champion-biased and
`ignore_duplicates`, so it will never create a proper challenger. New router module,
registered at `main.py:324-335`.
*Effort: ~0.5 day.* *REVIEW:* row lands with `status='challenger'`, chosen
`prompt_template`+`model`; the champion invariant index does not block it.

**Step C.3 — Challenger routing at the single stamping site.** In `audit_video`:
- No `hashlib` is imported today (verified absent in `audits.py`). Build fresh
  **deterministic** assignment:
  `int(hashlib.sha256(video_id.encode()).hexdigest(), 16) % 100 < CHALLENGER_TRAFFIC_PCT * 100`.
- When routed to challenger, override all three: `strategy_version`
  (the write at `audits.py:274`), `prompt_template` (the prompt selection at
  `audits.py:231-236` — feed the challenger's `prompt_template` into the `chat_json`
  `system=` at `audits.py:251`), and `model` (pass the challenger's `model` into
  `chat_json(..., model=...)`). **All three must move together or outcomes
  mis-attribute** — the same failure the `playlists.py:251` judge-model discipline
  guards against.
- Both entry points are covered because routing lives *inside* `audit_video`:
  autopilot (`autopilot.py:509`) and manual `POST /videos/{id}/audit`
  (`audits.py:298-300`) both call it.
*Effort: ~1 day.* *REVIEW:* the same `video_id` always lands in the same arm;
challenger audits carry the challenger's `strategy_version` AND were generated with
its prompt+model (spot-check the `chat_json` call args vs the stamped row).

**Step C.4 — Offline eval `app/eval.py`.** Two signals, neither sees CTR (§3.2):
- **Pairwise LLM-as-judge:** run champion and challenger on the frozen held-out set
  (`EVAL_HELDOUT_SIZE=50`); a **different-family** judge (`EVAL_JUDGE_MODEL` = Gemini)
  picks the better suggestion head-to-head. Judge idiom: `chat_json(prompt,
  model=EVAL_JUDGE_MODEL)` (mirror `playlists.py:251`). Generate both arms by reusing
  `audit_video` with a prompt/model override — the same no-YouTube-write shadow shape
  as `_run_shadow_audits` (`reflection.py:400-436`).
- **Backtest:** for videos with known `measurement_status`, check the challenger
  re-derives historically-winning patterns and avoids regressed ones. Guardrail, not
  proof (§3.2).
*Effort: ~1.5 days.* *REVIEW:* `POST /strategies/{version}/eval` returns judge
tallies + backtest; the frozen set is stable across runs; judge model ≠ generator
family.

**Step C.5 — Online compare/promote.** Mirror `_cohort_median_lift`
(`reflection.py:441-498`) + `_check_auto_revert` (`reflection.py:501-568`), but scope
by `audits.strategy_version` (not `prompt_version_id`) and use the measured metric =
**win-rate / mean CTR uplift from `measurement_result`** (`measurement_result` carries
`ctr_delta_relative` and the win/regression status — `measurement.py:198-224`). Apply
the `_MIN_DATA_POINTS`-style floor as `MIN_OUTCOMES_FOR_PROMOTION` **per arm**.
- `GET /strategies/compare` = rollup; `POST /.../promote` promotes challenger + retires
  old champion (respect the C.1 one-champion invariant — flip statuses in one logical
  step); `POST /.../retire` retires.
*Effort: ~1.25 days.* *REVIEW:* below the per-arm floor, compare returns
"insufficient data" and promote refuses; above it and past the margin, promote flips
statuses and the invariant index still holds exactly one champion.

### Loop 3 gotchas (carry into the PR)

- **Table default `status='challenger'`** but the seed + `_ensure_strategy_row` are
  **champion-biased with `ignore_duplicates`** — a new challenger must be inserted with
  **explicit `status='challenger'`** (C.2). Never route through `_ensure_strategy_row`
  to make a challenger.
- **"Exactly one champion / at most one challenger" is NOT DB-enforced** — add the
  partial unique index (C.1) or enforce in app.
- **Unit of eval = measured outcomes (~3 weeks each, pooled across channels)** — thin
  volume for a long time. **One challenger at a time.**
- **Challenger prompt + model must thread to BOTH** the `chat_json` call
  (`audits.py:251`) **and** the row write (`audits.py:274`), or outcomes
  mis-attribute (C.3).
- **Playlist Loop 3 (`PLAYLIST_OPTIMIZATION.md` §Meta loop) reuses this same
  `audit_strategies` table** with a `playlist:` version prefix, routed by playlist-id
  hash — out of scope for Track 4 (belongs with Track 3), but do not design the routing
  in a way that blocks it.

---

## 3. Consolidated artifacts

### Migrations (all `add/create ... if [not] exists`; stamps must sort after `20260728010000`)

| File | Adds |
|---|---|
| `20260730000000_loop2_playbook.sql` | `channels`: `playbook_json`, `playbook_built_at`, `playbook_outcome_count int default 0`, `playbook_enabled boolean default false` |
| `20260730010000_3b_playlist_playbook.sql` | `channels`: `playlist_playbook_json`, `playlist_playbook_built_at` |
| `20260730020000_loop3_champion_challenger.sql` | partial unique index `audit_strategies_one_champion_idx` (invariant only; table already exists) |

### Config knobs (`app/config.py`, `os.getenv(...) or default`)

| Setting | Default | Sub-piece |
|---|---|---|
| `MIN_OUTCOMES_FOR_PLAYBOOK` | `15` | Loop 2 |
| `PLAYBOOK_REFRESH_DELTA` | `10` | Loop 2 |
| `PLAYBOOK_MAX_EXEMPLARS` | `10` | Loop 2 |
| `MIN_OUTCOMES_FOR_PLAYLIST_PLAYBOOK` | `10` | 3B |
| `PLAYLIST_PLAYBOOK_REFRESH_DELTA` | `5` | 3B |
| `CHALLENGER_TRAFFIC_PCT` | `0.20` | Loop 3 |
| `MIN_OUTCOMES_FOR_PROMOTION` | `30` | Loop 3 |
| `PROMOTION_MARGIN` | `0.05` | Loop 3 |
| `EVAL_HELDOUT_SIZE` | `50` | Loop 3 |
| `EVAL_JUDGE_MODEL` | `google/gemini-2.0-flash-001` | Loop 3 |

(Per-channel DB gates, not env: `channels.playbook_enabled`.)

### Endpoints

| Method + path | Sub-piece |
|---|---|
| `POST /channels/{id}/playbook/rebuild` | Loop 2 |
| `GET /channels/{id}/playbook` | Loop 2 |
| `GET /channels/{id}/playlist-playbook` | 3B |
| `POST /strategies` | Loop 3 |
| `POST /strategies/{version}/eval` | Loop 3 |
| `GET /strategies/compare?champion=&challenger=` | Loop 3 |
| `POST /strategies/{version}/promote` | Loop 3 |
| `POST /strategies/{version}/retire` | Loop 3 |

---

## Appendix — discipline checklist (carry into every PR)

- [ ] **Phantom check:** no reference to `style_profile` / `style_profile_json`
      anywhere in new code; storage + distillation mirror `reflection.py` +
      `prompt_versions` (§0.2).
- [ ] **Payoff-gate honesty:** PR description states the feature is inert until the
      relevant cold-start floor / promotion floor is crossed (months out); no
      threshold tuned on thin data (§0.1).
- [ ] All migration ops `add column if not exists` / `create ... if not exists`;
      stamp sorts strictly after `20260728010000`.
- [ ] **Language rule stays first** in `_build_user_block` (`audits.py:142-150`);
      playbook block inserted AFTER it, never before.
- [ ] Distiller prompts (Loop 2 + 3B) explicitly state **bundle-level, correlational
      attribution** (data carries `"attribution":"bundle"`) AND the
      `default_language` rule.
- [ ] Outcome scoping uses **video-ids-of-channel** paging (`measurement.py:344-382`)
      — never a naive `.select()` (respects the 1000-row cap) — and excludes
      `not_applicable` (`.neq(...)`, `measurement.py:373`).
- [ ] Per-channel gate (`playbook_enabled`) honoured in BOTH the injection path and
      any rebuild/scheduled job; flag-off channels skipped silently.
- [ ] Cold-start floor honoured: below `MIN_OUTCOMES_FOR_PLAYBOOK` /
      `MIN_OUTCOMES_FOR_PLAYLIST_PLAYBOOK` → inject nothing, prompt byte-identical to
      today (graceful degradation, `audits.py:167-171` precedent).
- [ ] **Loop 3:** challenger inserted with explicit `status='challenger'`, NOT via
      `_ensure_strategy_row`; challenger prompt+model threaded to BOTH `chat_json`
      (`audits.py:251`) AND the row write (`audits.py:274`).
- [ ] **Loop 3:** one-champion invariant enforced (index or app); one challenger at a
      time; promotion refuses below `MIN_OUTCOMES_FOR_PROMOTION` per arm.
- [ ] **Loop 3:** `EVAL_JUDGE_MODEL` is a different family from the generator
      (Anthropic) — Gemini via config, not hardcoded.
- [ ] New scheduled jobs use `max_instances=1, coalesce=True`; weekly rebuilds mirror
      `_weekly_reflection` (`main.py:213-222`); new routers registered at
      `main.py:324-335`.
- [ ] `DRY_RUN` respected; no YouTube writes leak from distillation, eval, or
      compare/promote paths (offline eval reuses the `_run_shadow_audits` no-write
      shape, `reflection.py:400-436`).
