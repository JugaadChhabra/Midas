# Deterministic format scorers

Date: 2026-08-24
Status: approved, not started
Implements step 4 of `2026-08-23-observability-evidence-loop-design.md`. Depends
on nothing — no database, no office machine, no Phoenix.

## The evidence

Every number below was measured on 2026-08-24 from `migration_export/audits.ndjson`
(exported 2026-08-08), over the 2,617 audits with `status = applied`.

The house format says a description carries **exactly 15 hashtags** — 3 on the
first line, which YouTube surfaces above the title, and 12 at the bottom.
Fifteen is not a preference: **YouTube ignores every hashtag on a video that
carries more than 15**, so 16 hashtags and 0 hashtags are the same thing to a
viewer.

Two silent regressions, in opposite directions, three months apart:

| Applied | Channel | >15 hashtags | exactly 15 | <15 |
|---|---|---|---|---|
| 2026-05 | `UCr5-…` (mr) | **1332 (92.5%)** | 8 | 100 |
| 2026-06 | `UCr5-…` (mr) | **490 (90.1%)** | 39 | 15 |
| 2026-07 | `UC8Kjo…` (pa) | 0 | 8 | **568 (98.6%)** |
| 2026-08 | `UCc4Tv…` | 0 | 53 | 4 |

**May–June: 1,822 videos were published with every hashtag ignored.** The model
was emitting 20–45 hashtags — 738 audits emitted exactly 30 — and nothing
capped them. `cap_description_hashtags` did not exist until `dbef839`
(2026-07-30).

**July: the opposite failure.** 169 audits emitted **zero** hashtags, most of
the rest 3–5. The first-line-3 rule — the one that puts hashtags above the
title — was satisfied in **1.4%** of that month's audits.

Neither regression was detected by anything. Both are a single integer per
audit, computable offline, with no model in the loop.

### Why the persisted row cannot answer this now

August looks healthy: 53 of 57 audits carry exactly 15. That number is
uninterpretable. `cap_description_hashtags` runs inside `AuditSuggestion._make`,
so it has already trimmed the description before `to_audit_row()` persists it. A
model emitting 15 and a model emitting 30 produce a **byte-identical row**.

So the fix destroyed the evidence of its own necessity. The cap is correct and
must stay — it is what stands between a prompt regression and 1,822 more videos
with dead hashtags — but it means the count has to be measured **before**
normalisation or not at all. This is the single highest-value scorer in this
document, and it is roughly four lines of code.

## The constraint that shapes everything: score per channel, against its own prompt

While gathering the evidence above I produced a wrong finding and caught it. The
regional-script rate in titles is ~99% in May–July and **3.5%** in August, which
reads as a catastrophic regression. It is not. Each month is a different
channel:

| Channel | `default_language` |
|---|---|
| `UCr5-YUqBiW7PUmeAtxUWuRg` | `mr` (Marathi) |
| `UC8KjoL0Z9mTHKqB6gFutkJw` | `pa` (Punjabi) |
| `UCc4Tv_DEGDEKrKAt-vyVNmw` | **`None`** → `audit_video` falls back to `"en"` |

August's audits are an English-language channel correctly not emitting Devanagari.
The same confound inflates the title-template rate from 0% to 73.7% across the
same boundary.

Two consequences, both binding:

1. **A scorer must be evaluated against the prompt that actually ran**, resolved
   per channel (`audit_configs.generated_prompt`, or `shorts_prompt`, or
   `DEFAULT_PROMPT`), never against a single global house format. `audits.py`
   already records which prompt was used; `prompt_version_id` attributes it.
2. **Cross-channel aggregate rates are not a signal.** A comparison is only
   meaningful within one channel, or within one prompt version. Any report that
   averages a rule's pass rate across channels will manufacture regressions out
   of language differences, exactly as my first pass did.

Not every rule is channel-dependent. The hashtag ceiling is a YouTube platform
rule and applies to every channel identically. The rules split cleanly on this
axis, and the split is what the design turns on.

## What gets scored

### Universal rules — platform facts, identical for every channel

These need no prompt context and cannot produce a false alarm from a language
difference.

- **`hashtags_precap`** — the count *before* `cap_description_hashtags` runs.
  Fails above 15. This is the rule the whole document exists for.
- **`hashtags_exact_15`** — reports the count against the house target. Advisory
  where a channel's live prompt does not demand 15; see below.
- **`safety`** — delegate to `AuditSuggestion.rejection()` directly, never a
  reimplementation, so the eval and the production apply gate cannot drift. It
  already checks title ≤100 chars, description ≤5000, tags a list of strings,
  ≤30 tags, ≤500 tag-characters.
- **`json_intact`** — did the response parse without `json_repair` or the
  brace-slice rescuing it. The tracing work already emits these as span
  attributes; this reads the same facts offline for a candidate prompt that has
  never run in production.

### Channel-dependent rules — require the live prompt

Each of these must resolve the channel's own prompt and skip, not fail, when
that prompt does not assert the rule.

- **`first_line_3_hashtags`** — 1.4% in July. The rule exists because these are
  the hashtags a viewer actually sees.
- **`description_blocks`** — the five blocks present and in order: 3 hashtags,
  English description, regional description, a Keywords line, 12 hashtags.
- **`regional_script_present`** — a codepoint-range check against the channel's
  `default_language`, not a heuristic and not a language-detection model.
  **Skipped entirely when `default_language` is null**, which is the state
  `UCc4Tv…` is in today.
- **`title_template`** — matches the channel's prompt's title shape. For the
  nursery-rhyme default that is `[regional] | [english] | [theme] Nursery 3D
  Rhymes`.
- **`tag_budget`** — total tag characters within a target band. Under 200 is a
  wasted budget, not a pass; the observed medians are 315 / 324 / 217 / 392 by
  month against a 500 ceiling.

### Explicitly not scored

- **Anything requiring a judgement about quality.** No LLM. This document is
  entirely deterministic, and that is what makes its output trustworthy enough
  to gate on later. The judge is deferred in the parent spec with its own
  re-entry criterion (≥30 regression verdicts).
- **Whether a suggestion will earn CTR.** Not knowable offline. A format scorer
  says the output is well-formed, never that it is good.

## Shape

`app/scorers.py` — pure functions, no I/O, no database, no network. Each takes a
suggestion (and, for channel-dependent rules, a resolved prompt context) and
returns a typed result: rule name, pass/fail/skip, the observed value, and the
expected one. Skip is a first-class outcome, not a silent pass — a rule that
cannot apply must say so, or a report of "100% passing" will hide the fact that
half the rules never ran.

`scripts/score_audits.py` — runs the scorers over a set of audits and prints a
per-channel, per-rule table. Read-only. No production write path, no scheduler
entry. It cannot affect autopilot.

Two input modes, because they answer different questions:

- **Historical** — score existing `audits` rows to see how a live prompt has
  been behaving. This is what would have surfaced both regressions above.
  Limitation, stated plainly: for audits applied after 2026-07-30, the
  `hashtags_precap` rule cannot run, because the stored description is already
  capped. It reports `skip`, not `pass`.
- **Fresh** — run a candidate prompt against a frozen video sample and score the
  output before it is persisted, which is the only way `hashtags_precap` gets a
  real answer.

The frozen sample is load-bearing: comparing two prompt versions on different
videos is not a comparison. Stratify across channels so the per-channel
requirement above is exercisable.

## Testing

Table-driven per rule, with the fixtures drawn from the real failures:

- a description with 22 hashtags must score **fail** on `hashtags_precap`
  **despite** `cap_description_hashtags` normalising it to 15 — this is the
  test that pins the reason this work exists;
- a description with 0 hashtags (July's most common shape, 169 audits) must fail
  both `hashtags_exact_15` and `first_line_3_hashtags`;
- an English-language channel with `default_language = None` must **skip**
  `regional_script_present`, not fail it — the false alarm this design is built
  to avoid;
- `#मराठी` must count as one hashtag: `_HASHTAG_RE` is deliberately
  `#[^\s#]+` rather than `#\w+`, because `\w` excludes Devanagari combining
  marks and would truncate the regional hashtags the house format is built
  around;
- `safety` must agree with `AuditSuggestion.rejection()` on every fixture, by
  calling it rather than restating its thresholds.

## Open questions

1. **Is `UCc4Tv…`'s null `default_language` deliberate?** It is the autopilot
   channel. `audit_video` silently falls back to `"en"`, so it currently gets
   English-only metadata. If that channel is meant to be regional, this is a
   live content bug affecting every audit it has ever produced — and it is
   invisible for exactly the same reason the hashtag counts were. Needs a human
   answer, not a code change.
2. **What is the right tag-character band?** 500 is YouTube's ceiling and is
   already enforced by `rejection()`. The lower bound is a judgement about
   wasted budget, and the observed medians (217–392) suggest no channel is
   close to the ceiling. Pick a number only after looking at whether tag count
   correlates with measured CTR — which needs the evidence loop running, so
   this rule ships advisory-only.
3. **Should `hashtags_exact_15` fail or warn when a channel's prompt does not
   demand 15?** Reflection can rewrite a prompt within the house format's rails,
   and the rails are asserted as prose. Until a prompt's assertions are
   machine-readable, this rule is advisory outside the default prompt.

## What this deliberately does not do

It does not gate prompt promotion. The parent spec defers that until a judge can
be calibrated, and gating on format alone would only assert that a candidate is
well-formed — which the apply path already enforces through `rejection()`. These
scorers report. Wiring them into `_promote_version` is a separate decision that
should be made once there is evidence they predict anything.
