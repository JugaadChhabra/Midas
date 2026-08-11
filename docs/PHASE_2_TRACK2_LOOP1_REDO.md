# Phase 2 · Track 2 — Finish Loop 1's act half: the redo pipeline — Implementation Checklist

**Status:** DRAFT — to be reviewed before any implementation work begins.
**Spec source of record:** `docs/CONTINUOUS_IMPROVEMENT_LOOP.md` §1 (esp. §1.1 state
machine, §1.5 Revert, §1.6 Redo, §1.8 Endpoints, §1.9 Config).
**Substrate already shipped:** the whole sense→judge half of Loop 1 — apply enters
measurement (`audits.py` `apply_audit_internal`), the daily `eval_measurements` cron
lands `win`/`neutral`/`regression`, regressions surface at
`GET /channels/{id}/outcomes`, and human revert is `POST /audits/{id}/revert`.
**Estimated size:** ~1–1.5 days (1 migration, 1 config read, 1 executor, 1 endpoint,
1 trigger seam, review at each step).

> This is an **executable checklist**, not a spec. It proposes, justifies, and flags
> the open decisions. Every file:line seam below was read and verified against the
> tree at the time of writing. Steps within a track are sequential.

---

## 1. Goals + non-goals

### Goals (what this track ships)

The sense→judge half of Loop 1 is live but **the act half is inert** — a regression
verdict is recorded and shown to a human, and revert exists, but **redo does not**.
This track lights up the redo pipeline that CIL §1.6 specifies:

CIL §1.6, verbatim:

> A redo is a fresh audit with the prior failure injected as context, e.g.:
> *"Previous title `X` produced a CTR change of -8% over 3 weeks. Try a materially
> different angle (e.g. curiosity-led rather than keyword-led)."*
>
> - Cap with `MAX_REDO` (default **2**) to bound LLM/image spend and prevent
>   thrashing.
> - After the cap, stop and leave the last applied version; `outcome_decision`
>   records exhaustion.

Concretely:

1. A **redo executor** — `redo_audit(audit_id)` in `app/audits.py` — that builds a
   fresh, LLM-generated audit whose prompt injects the prior failure, links it back
   to the regressed audit via `redo_of_audit_id`, and marks the superseded audit
   `outcome_decision='redo_queued'`.
2. A **manual endpoint** — `POST /audits/{audit_id}/redo` — mirroring `revert_audit`,
   the last of the three CIL §1.8 ops endpoints not yet built.
3. **`MAX_REDO` enforcement** so a chain of redos on one video stops at the cap
   (config knob exists at `config.py:131` but is **never read** today).
4. A **migration** adding `audits.redo_count` (see §4) so the cap is a cheap column
   read, not an FK-chain walk.
5. **Measurement-state consistency**: the superseded audit must be parked out of the
   `eval_measurements` query so a redone-away audit is not still evaluated.

### Non-goals (explicit out-of-scope)

- **No auto-redo.** Redo is manually triggered (endpoint) in this track, mirroring
  `AUTO_REVERT_ON_REGRESSION=false` (CIL Decision 7). Auto-enqueue from the
  `_eval_audit` regression branch is designed here (§6, Step 2.4) but ships **behind
  a default-off flag** — the human stays in the loop first.
- **No Loop 2 / playbook** work — the redo failure-context is injected ad hoc from the
  regressed audit's own `measurement_result`, not from a distilled playbook.
- **No autopilot `redo_queued` work-item pickup** (CIL §1.7 — "Include `redo_queued`
  audits as work items"). This track *produces* `redo_queued` rows and the linked
  successor audit; wiring autopilot to prioritise them is a separate slice.
- **No thumbnail redo.** Redo re-runs the metadata audit only, same surface as
  `audit_video`.
- **No new significance test** (still v1 relative-delta, per CIL §1.4).

The human gate that stays OFF: auto-enqueue of redo on regression (the new
`AUTO_REDO_ON_REGRESSION` flag, §5, default `false`).

---

## 2. Existing-state audit — what is inert

Everything below was **built but never wired**; this is the debt this track pays down.

| Artifact | Location | State today |
|---|---|---|
| `audits.redo_of_audit_id bigint references audits(id)` | migration `20260702183233_phase1a_loop1_measurement.sql:45` | Column exists, only ever **read** (never written) — SELECTed in `get_measurement` (`measurement.py:328`). |
| `outcome_decision` value `redo_queued` | migration `…:43-44` (free-text column, comment lists the value — **not** a CHECK/domain, so no schema change needed to write it) | Never written anywhere. |
| `MAX_REDO` config | `config.py:131` (`int(os.getenv("MAX_REDO") or "2")`) | Defined, **never read** by any module. |
| Redo forward-ref comment | `measurement.py:23-25` | "Redo (§1.6) is NOT in this slice — queued behind watching a few real regressions first. redo_of_audit_id exists in the schema so nothing blocks it later." |
| Regression branch (the trigger seam) | `measurement.py:231-241` | Only calls `_finalize(audit["id"], "regression", "none", result)` + a warning log. This is exactly where an auto-enqueue would hook. |
| `_eval_audit` SELECT column set | `measurement.py:260` | **Narrow** — `id,video_id,applied_at,measurement_started_at,measurement_status`. Does NOT fetch `redo_of_audit_id` or a redo-depth column. Must widen if the cap is enforced at eval time. |
| Revert endpoint (the mirror template) | `audits.py:632-700` | Complete; the redo endpoint copies its status/verdict-guard + measurement-parking shape. |
| `audit_video` (the executor template) | `audits.py:217-277` | Complete; builds the audit row (`row` dict `audits.py:262-275`) and inserts it. |
| Prompt-version stamp pattern | `autopilot.py:542-557` | Post-insert `.update({...}).eq("id", audit_row["id"])` — the pattern for stamping `redo_of_audit_id` onto the freshly-inserted redo row. |

Confirmed **absent**: no `redo_count` column, no `redo_audit`/`_redo_audit` function,
no `/redo` route, no reference to `settings.MAX_REDO` outside `config.py`.

---

## 3. The redo-semantics decision (resolve first — everything downstream depends on it)

"Redo" is undefined by the schema. Two candidate meanings:

- **(a) Re-run the LLM for NEW suggestions**, injecting the prior failure as context so
  the model tries a materially different angle.
- **(b) Re-apply a different already-stored candidate** from the original audit's output.

**Recommendation: option (a).** Grounds:

1. **Spec.** CIL §1.6 is explicit — *"A redo is a fresh audit with the prior failure
   injected as context… Try a materially different angle."* Option (b) has no "prior
   failure injected" step and no notion of "a materially different angle" — the stored
   candidates were all generated from the same context that just regressed.
2. **We store one suggestion per field, not a candidate set.** `audit_video`
   (`audits.py:265-267`) writes a single `suggested_title` /
   `suggested_description` / `suggested_tags`. There is no bench of alternates to pick
   (b) from without re-running the model anyway.
3. **It composes for free with measurement.** A redo produced by option (a) is a
   normal pending audit; when it is applied via `apply_audit_internal`, the existing
   `measurement_enabled` branch (`audits.py:421-425`) sets it to `awaiting_window`
   automatically — the redo **re-enters measurement with zero extra code**. The
   failure→retry→re-measure trajectory (fuel for Loop 2) records itself.

**How the prior failure is injected (option a mechanics):**

- `audit_video` already accepts a `prompt_override` param (`audits.py:217`,
  used at `:231-232`). The redo executor computes a **failure-context preamble** and
  prepends it to the effective audit prompt for that channel, then calls
  `audit_video(video_id, prompt_override=<preamble + base_prompt>)`.
- The preamble is built from data already on the regressed audit — no new fetch:
  - prior title from `title_before` (the metadata that was live *before* the regressed
    apply) and/or the regressed `suggested_title` (what was applied and regressed);
  - the CTR delta and pre/post windows from `measurement_result`
    (`measurement.py:198-209` writes `pre_window`/`post_window`/`ctr_delta_relative`).
- Preamble template (fills the CIL §1.6 example):
  > "A previous audit changed this video's packaging and CTR moved by {delta:+.0%}
  > over the measurement window ({pre_ctr:.3f} → {post_ctr:.3f}). The prior applied
  > title was: '{prior_title}'. Propose a **materially different angle** — do not
  > re-suggest the prior packaging or minor variants of it."
- The base prompt is resolved the same way `audit_video` resolves it
  (`audits.py:229-236`: per-channel `generated_prompt` / `shorts_prompt` /
  `DEFAULT_PROMPT`). Simplest implementation: pass the preamble as a prefix and let
  `audit_video` use it as the whole `system` prompt — i.e. the redo executor resolves
  the base prompt itself and hands `preamble + "\n\n" + base_prompt` as
  `prompt_override`.

Document the chosen semantics in the executor docstring and the PR description so
future readers don't re-litigate it.

---

## 4. Migration — `audits.redo_count`

**One new idempotent migration**, name it e.g.
`20260730000000_loop1_redo_count.sql` (matches the `YYYYMMDDHHMMSS_name.sql`
convention; pick the real timestamp at author time).

```sql
-- CIL §1.6 — bound the redo chain with MAX_REDO. The chain is a linked list via
-- audits.redo_of_audit_id; redo_count is the denormalised depth so the cap is a
-- single-row read at enqueue time, not a per-hop FK-chain walk.
alter table audits
    add column if not exists redo_count integer not null default 0;
```

**Why a column, not an FK walk:** `redo_of_audit_id` already gives a walkable chain,
but enforcing the cap by walking it costs one query per hop, per enqueue, and races
under concurrent triggers. A denormalised `redo_count` on the successor row (set to
`parent.redo_count + 1` at creation) makes the cap check `new_parent.redo_count <
MAX_REDO` — one read. Every existing row defaults to `0`, which is correct (they are
not redos). No backfill.

**What this migration does NOT touch:** `outcome_decision` needs no change —
`redo_queued` is already an allowed free-text value (comment at migration
`…:43-44`); there is no CHECK constraint or PG domain to alter. `redo_of_audit_id`
already exists (`…:45`).

*Appendix discipline:* the `IF NOT EXISTS` guard and `default 0` keep the migration
idempotent and backfill-free, matching the Phase 0/1A conventions.

---

## 5. Config

`MAX_REDO` already exists (`config.py:131`, default `2`) — this track is the first
reader. Add one new flag next to `AUTO_REVERT_ON_REGRESSION` (`config.py:135`):

| Setting | Default | Notes |
|---|---|---|
| `MAX_REDO` | `2` | **existing** — now actually read by the executor (§6). CIL §1.9. |
| `AUTO_REDO_ON_REGRESSION` | **`false`** | **new** — gates the auto-enqueue seam in `_eval_audit` (Step 2.4). Mirrors `AUTO_REVERT_ON_REGRESSION`: human-review-first in v1. Regression → surfaced at `/outcomes` → operator POSTs `/redo`; only once trusted per-deployment does auto-enqueue turn on. |

`AUTO_REDO_ON_REGRESSION` is a global env flag (like `AUTO_REVERT_ON_REGRESSION`),
not a per-channel column — the per-channel gate is already `measurement_enabled` at
apply time, and a redo only ever fires on a channel that was measurement-enabled.

---

## 6. Implementation steps (IMPLEMENT → REVIEW)

### Track A — schema + config (must ship first)

**Step 2.1 — Migration.** Author the `redo_count` ALTER from §4. No data backfill.
*Effort: ~20 min.*
*Review:* migration applies cleanly to a clone; every pre-existing audit row has
`redo_count = 0`; no existing reader breaks (the column is additive).

**Step 2.2 — Config flag.** Add `AUTO_REDO_ON_REGRESSION` at `config.py:135`
(after `AUTO_REVERT_ON_REGRESSION`). Confirm `MAX_REDO` (`config.py:131`) is
importable as `settings.MAX_REDO`.
*Effort: ~10 min.*
*Review:* `settings.MAX_REDO` and `settings.AUTO_REDO_ON_REGRESSION` both read; grep
confirms `MAX_REDO` now has exactly one non-config reader after Step 2.3.

### Track B — the redo executor (depends on Track A)

**Step 2.3 — `redo_audit(audit_id)` in `app/audits.py`.** New function, placed near
`revert_audit` (`audits.py:632`) so the two act-half operations sit together.

Behaviour (mirrors `audit_video` `audits.py:217-277` for the generate half and the
`autopilot.py:542-557` post-insert stamp pattern for the linkage):

1. Load the regressed (parent) audit; `single()` like `revert_audit`
   (`audits.py:639`). 404 if missing.
2. **Guards** (mirror `revert_audit:642-645`):
   - parent `status` must be `applied` (the redone-away metadata must currently be
     live — you cannot redo something that was never applied or was already reverted);
   - parent `measurement_status` must be `regression` (CIL §1.4: only regressions
     queue a redo). Reject `win`/`neutral`/others with a 400.
   - **cap:** `parent.get("redo_count") or 0` must be `< settings.MAX_REDO`; else 400
     `"redo cap reached"` and set the parent's `outcome_decision` to record exhaustion
     (CIL §1.6: *"After the cap… `outcome_decision` records exhaustion."* — e.g.
     `redo_exhausted`; keep it as a distinct string so the outcomes UI can show it).
3. **Build the failure-context preamble** from `title_before` +
   `measurement_result` (§3 mechanics). Resolve the base prompt exactly as
   `audit_video` does (`audits.py:229-236`).
4. **Generate the new audit:** `new = audit_video(parent["video_id"],
   prompt_override=<preamble + base_prompt>)`. This inserts a fresh pending audit and
   returns the row (`audits.py:276-277`).
5. **Stamp linkage on the new row** (mirror `autopilot.py:552-555`):
   `.update({"redo_of_audit_id": parent["id"], "redo_count": (parent.get("redo_count") or 0) + 1}).eq("id", new["id"])`.
6. **Park the superseded parent** so the daily eval stops touching it and its state
   reflects the decision:
   `.update({"outcome_decision": "redo_queued"}).eq("id", parent["id"])`.
   See §7 — this is the consistency gotcha.
7. Return `{"redo_of": parent["id"], "audit_id": new["id"], "status": "pending"}`.

Note: the new audit is **pending**, not applied — it is generated, not pushed. Apply
happens through the existing `/audits/{id}/apply` path (or autopilot later), at which
point `apply_audit_internal` re-enters it into measurement for free (§3 point 3). The
redo executor performs **no YouTube write** — no `DRY_RUN` branch needed here (unlike
revert), because generation is an OpenRouter call, not a Data API write.
*Effort: ~3-4 hrs incl. the preamble builder.*
*Review:* on a channel with a real regression verdict, call `redo_audit` and confirm:
a new pending audit exists with `redo_of_audit_id` = parent id and `redo_count = 1`;
the suggestions differ from the parent's; the parent now has
`outcome_decision='redo_queued'`; a second/third redo respects `MAX_REDO=2` and the
capped parent lands the exhaustion string; no YouTube call was made.

### Track C — endpoint (depends on Track B)

**Step 2.4 — `POST /audits/{audit_id}/redo`.** Mirror `revert_audit`'s route
(`audits.py:632-633`). Thin wrapper: `return redo_audit(audit_id)`. This completes
the CIL §1.8 trio (`/measurement`, `/revert` already exist; `/redo` was the gap).
*Effort: ~15 min.*
*Review:* `curl -XPOST /audits/{id}/redo` on a regressed audit returns the new audit
id; on a non-regression audit returns 400; on a capped chain returns 400 with the
exhaustion message.

**Step 2.5 (optional, flag-gated) — auto-enqueue seam in `_eval_audit`.** In the
regression branch (`measurement.py:231-241`), after `_finalize(audit["id"],
"regression", "none", result)`, add:

```python
if settings.AUTO_REDO_ON_REGRESSION:
    try:
        redo_audit(audit["id"])
    except Exception:
        log.exception("auto-redo failed for audit %s", audit["id"])
```

For this the `_eval_audit` SELECT (`measurement.py:260`) must be **widened** to fetch
`redo_of_audit_id, redo_count` (currently absent) so the cap check inside
`redo_audit` sees the real depth — otherwise `redo_audit` re-fetches the full row
itself (it loads the parent via `single()` in Step 2.3, so the widening is only
needed if you want the cap decision available *before* calling the executor). Default
`AUTO_REDO_ON_REGRESSION=false` means this path is dormant on ship — the human
`/redo` endpoint is the only live trigger in v1.
*Effort: ~30 min.*
*Review:* with the flag off, `_eval_audit` behaviour is byte-for-byte unchanged
(regressions still just surface at `/outcomes`). With the flag on (test deploy only),
a fresh regression auto-produces a linked pending redo and respects the cap.

---

## 7. Consistency gotcha — don't leave a redone-away audit in the eval loop

`eval_measurements` only evaluates rows with `status='applied'` **and**
`measurement_status in ('awaiting_window','measuring')` (`measurement.py:261,267`).
`revert_audit` already handles its own supersession: when a human reverts mid-window
it parks the audit as `measurement_status='not_applicable'` (`audits.py:684-692`) so
the post-window would not measure post-revert exposure and `_finalize` cannot clobber
`outcome_decision='reverted'`.

The redo path must be **equally disciplined about the parent's state**:

- A redo is only enqueued on a `regression` verdict, and a regression is **terminal**
  — its `measurement_status` is already `regression` (not `awaiting_window`/
  `measuring`), so it is **already outside** the `eval_measurements` in-flight filter.
  Setting `outcome_decision='redo_queued'` (Step 2.3 point 6) does not re-open it.
- **Therefore the parent needs no `measurement_status` change** — unlike revert, which
  supersedes a *mid-window* audit. Only `outcome_decision` moves
  (`none` → `redo_queued`). This is the key difference from `revert_audit` and must be
  called out in the executor docstring so nobody "helpfully" also flips
  `measurement_status` and loses the regression verdict.
- The **new** redo audit is `pending` (not `applied`), so it too is outside the eval
  filter until it is applied — at which point `apply_audit_internal` sets it to
  `awaiting_window` and the loop resumes on the successor. No audit is ever evaluated
  twice for the same window.

**Separate-columns reminder (do not conflate):** `audits.status`
(`pending|applied|failed|quarantined|…`) is the **apply lifecycle**;
`measurement_status` (`not_applicable|awaiting_window|measuring|win|neutral|
regression`) is the **measurement lifecycle**; `outcome_decision`
(`none|kept|reverted|redo_queued`) is the **human/critic decision**. They are three
independent columns (migration `…:38-46`). The redo executor writes `outcome_decision`
on the parent and `redo_of_audit_id`/`redo_count` on the child — it must not touch the
parent's `measurement_status` (verdict) or `status` (the parent's metadata is still
the live/applied version until an operator applies the redo or reverts).

---

## 8. Rollout

Same cadence as every CIL loop — but redo is a *manual* endpoint in v1, so the
rollout is lighter than a cron:

1. Ship Tracks A–C with `AUTO_REDO_ON_REGRESSION=false`. The `/redo` endpoint is the
   only trigger.
2. Watch the first few operator-triggered redos on the already-measurement-enabled
   pilot channel: do the regenerated suggestions actually differ from the regressed
   ones? Does the applied redo re-enter `awaiting_window`? Does the cap hold at the
   third attempt?
3. Only once redos look sane and the cap is trusted, flip
   `AUTO_REDO_ON_REGRESSION=true` (Step 2.5) on one deployment and watch a full
   auto-redo cycle (weeks — the CIL slow clock).

---

## Appendix — discipline checklist (carry into PRs)

- [ ] Migration op is `add column if not exists … not null default 0` — idempotent,
      no backfill (matches Phase 0/1A migration conventions).
- [ ] `redo_count` on the new row = `parent.redo_count + 1`; cap check is
      `parent.redo_count < settings.MAX_REDO` (`config.py:131` — first real reader).
- [ ] `MAX_REDO` cap enforced; at the cap, `outcome_decision` records exhaustion
      (CIL §1.6) — a distinct string the `/outcomes` UI can render.
- [ ] Redo semantics = option (a): LLM re-run with prior failure injected via
      `prompt_override` (CIL §1.6). Chosen semantics documented in the executor
      docstring + PR body.
- [ ] Prior-failure preamble built **only** from data already on the regressed audit
      (`title_before`, `measurement_result`) — no new fetch.
- [ ] Redo executor performs **no YouTube write** (generation only). The redo audit is
      `pending`; measurement re-entry happens via `apply_audit_internal:421-425` when
      it is applied — verified, not assumed.
- [ ] Parent supersession touches **only** `outcome_decision` (→ `redo_queued`), never
      `measurement_status` (would destroy the regression verdict) and never the
      parent's `status` (its metadata is still live). Contrast with
      `revert_audit:684-692`, which parks a *mid-window* audit.
- [ ] `status`/`measurement_status`/`outcome_decision` treated as three separate
      columns — none conflated (migration `…:38-46`).
- [ ] `AUTO_REDO_ON_REGRESSION` defaults `false`; with it off, `_eval_audit`
      (`measurement.py:231-241`) behaviour is byte-for-byte unchanged.
- [ ] If the auto-enqueue seam (Step 2.5) ships, the `_eval_audit` SELECT
      (`measurement.py:260`) is widened to include `redo_of_audit_id,redo_count` (or
      the cap is deferred entirely to `redo_audit`'s own parent load).
- [ ] `POST /audits/{id}/redo` completes the CIL §1.8 endpoint trio; guards mirror
      `revert_audit` (status/verdict checks).
</content>
</invoke>
