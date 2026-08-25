# Format properties, measured against outcomes

Date: 2026-08-24 (rewritten 2026-08-25 — see *What changed*)
Status: approved, not started
Implements step 4 of `2026-08-23-observability-evidence-loop-design.md`. Depends
on nothing — no database, no office machine, no Phoenix.

## What changed, and why

The first version of this document specified a **compliance checker**: take the
house format, freeze each of its rules into a scorer, report pass/fail. That was
wrong, and the objection that killed it is worth recording because it applies to
everything built on top of this.

Enforcing the house format cements it. The format is a set of human priors —
the title template, the five-block description order, *exactly* 15 hashtags
rather than *at most* 15, the bilingual layering — and **not one of them has
ever been tested.** `reflection.py` calls them `NON-NEGOTIABLE HOUSE FORMAT` and
instructs the model to "never weaken, reorder, or drop any of it." Writing an
enforcement layer under that would have moved the priors from prose into code,
where they are harder to dislodge, not easier.

That matters because the format is not visibly winning. Across the 171 audits
that carry a measured CTR verdict: **21 win, 147 neutral, 3 regression.** The
house format is an untested hypothesis being defended as a constraint.

So the job is not to enforce it. **The job is to make it falsifiable.** Measure
what shape each audit actually took, join that against what the shape earned,
and let each rule justify its own existence on evidence. A rule that survives
has earned its place; one that does not gets dropped, and the model gets that
much more room.

## Two kinds of constraint, and only one of them is a rule

The distinction the first draft collapsed:

**Platform physics.** YouTube ignores *every* hashtag on a video carrying more
than 15. Titles hard-truncate at 100 characters. Tags cap at 500 characters
total. These are properties of the environment, not opinions. A model emitting
30 hashtags has not exercised judgement — it has shipped a bug, and this
codebase has the receipts: between 2026-05 and 2026-06, **1,822 videos were
published with every hashtag ignored**, because the model was emitting 20–45
(738 audits emitted exactly 30) and nothing capped them until `dbef839`
(2026-07-30). These stay pass/fail forever.

**Unvalidated priors.** Everything else. The title template. The block order.
The exact-15 target. The keywords line. These become *measured properties* with
an outcome attached, never pass/fail.

## The evidence this was built from

Measured 2026-08-25 from `migration_export/audits.ndjson` (exported 2026-08-08),
over the 2,617 audits with `status = applied`.

| Applied | Channel | `default_language` | >15 hashtags | =15 | <15 |
|---|---|---|---|---|---|
| 2026-05 | `UCr5-…` | `mr` | **1332 (92.5%)** | 8 | 100 |
| 2026-06 | `UCr5-…` | `mr` | **490 (90.1%)** | 39 | 15 |
| 2026-07 | `UC8Kjo…` | `pa` | 0 | 8 | **568 (98.6%)** |
| 2026-08 | `UCc4Tv…` | **NULL** | 0 | 53 | 4 |

Two silent regressions in opposite directions, three months apart, neither
detected by anything. May–June is the hashtag overflow above. July is its
inverse: **169 audits emitted zero hashtags**, most of the rest 3–5, and the
first-line-3 rule — the hashtags a viewer sees above the title — was satisfied
in **1.4%** of that month's audits.

Both are one integer per audit, computable offline, no model in the loop.

### The persisted row cannot answer this today

August looks healthy: 53 of 57 at exactly 15. **That number is uninterpretable.**
`cap_description_hashtags` runs inside `AuditSuggestion._make`, before
`to_audit_row()` persists anything, so a model emitting 15 and a model emitting
30 write a byte-identical row. The fix destroyed the evidence of its own
necessity.

The cap is correct and stays — it is what stands between a prompt regression and
1,822 more dead-hashtag videos. But the count has to be captured **before**
normalisation or not at all.

### A confound that nearly became a finding

Regional-script presence in titles runs ~99% May–July and **3.5%** in August,
which reads as catastrophic. It is not: each month is a different channel, and
August's is `UCc4Tv_DEGDEKrKAt-vyVNmw` — *Taarak Mehta Ka Ooltah Chashmah
Baalgeet Haryanvi* — whose `default_language` is NULL, so `audit_video` falls
back to `"en"` (`app/audits.py:388`). The same confound inflates the
title-template rate from 0% to 73.7% across the same boundary.

**Cross-channel aggregates are not a signal.** Any comparison must hold the
channel fixed, or it manufactures regressions out of language differences.

This confound also exposed a live content bug — see open question 1.

## What gets measured

A **property vector per audit**, not a verdict. The unit of output is "this
audit had 30 hashtags, 3 on the first line, a title matching the template, 315
tag-characters," never "this audit failed rule 4."

`app/verdicts.py` already has the neighbouring concept: `levers()` says *which
fields moved*. This extends it to *how they moved*. The two compose — a lever
says the title changed, a property says it changed into the template shape.

**Platform gates** (pass/fail, universal, no prompt context needed):
- `hashtags_precap` — the count *before* `cap_description_hashtags` runs.
  Above 15 is a defect on any channel. The single highest-value measurement
  here, and roughly four lines of code.
- `safety` — delegate to `AuditSuggestion.rejection()` directly, never a
  reimplementation, so this and the production apply gate cannot drift.
- `json_intact` — did the response parse without `json_repair` or the
  brace-slice rescuing it. The tracing work emits these as span attributes for
  live calls; this reads the same facts for a candidate prompt that has never
  run in production.

**Measured properties** (no pass/fail; recorded with the outcome):
- `hashtag_count`, `first_line_hashtag_count`
- `title_matches_channel_template` — against the channel's *own* live prompt,
  resolved per channel, never a global format. Null when the prompt asserts no
  template.
- `description_block_order` — which of the five blocks are present, in order.
- `regional_script_present` — a codepoint-range check against the channel's
  `default_language`. **Null, not false, when that language is NULL** — the
  confound above is exactly this case.
- `tag_char_count`, `tag_count`
- `title_length`

Every property is also computed for the **pre-change** state (`title_before`,
`description_before`, `tags_before`) so the question can be "did moving this
property help?" rather than "do winners have this property?" The second question
is answerable by any correlation; only the first is worth acting on.

## Joining properties to outcomes

The point of the whole document. For each audit carrying a measured verdict,
emit its property vector alongside `measurement_status` and `ctr_delta`, so a
question like *"does matching the title template correlate with a win, within
this channel?"* becomes a query rather than an argument.

**What this can and cannot tell you, stated plainly.** The joinable set today is
**171 audits** — every one from a single channel, `UC8KjoL0Z9mTHKqB6gFutkJw`,
with 21 wins and 3 regressions. That is not enough to conclude anything about
any individual property, and this document does not pretend otherwise. Three
consequences:

1. **This ships as an accruing asset, not an answer.** Its output is a table
   that gets more informative every month once the evidence loop is reconnected
   (step 1 of the parent spec).
2. **No property may be acted on from a single channel's data.** Format effects
   and channel effects are perfectly confounded at n=1 channel.
3. **Report effect sizes with counts, never bare percentages.** "3 of 4 audits
   with property X won" must never render as "75%."

A property that shows no effect after a few hundred verdicts across more than
one channel is a candidate for removal from the prompt — which is the mechanism
by which the model gets more room, on evidence.

## Shape

`app/format_properties.py` — pure functions, no I/O, no network, no database.
Takes a suggestion plus a resolved channel context; returns a typed property
vector. Null is a first-class value meaning "not applicable here," never
silently false — a report of "100% present" must not be able to hide a property
that was never evaluated.

`scripts/audit_properties.py` — computes vectors over a set of audits and emits
a per-channel table joined to outcomes. Read-only. No scheduler entry, no
production write path. It cannot affect autopilot.

Two input modes, answering different questions:

- **Historical** — vectors over existing `audits` rows, which is what would have
  surfaced both regressions above. Honest limitation: for audits applied after
  2026-07-30, `hashtags_precap` returns **null, not a value**, because the
  stored description is already capped.
- **Fresh** — run a candidate prompt over a frozen, channel-stratified video
  sample and compute vectors before persistence, which is the only way
  `hashtags_precap` gets a real answer. Frozen is load-bearing: two prompt
  versions compared on different videos is not a comparison.

## Testing

Table-driven, fixtures drawn from the real failures:

- 22 hashtags must report `hashtags_precap = 22` and a platform-gate failure
  **despite** `cap_description_hashtags` normalising the description to 15 —
  the test that pins why this exists;
- 0 hashtags (July's most common shape, 169 audits) must report `0`, not null;
- a channel with `default_language = NULL` must report
  `regional_script_present = null`, not `false` — the confound this design is
  built to avoid, and the one that nearly became a published finding;
- `#मराठी` counts as one hashtag: `_HASHTAG_RE` is deliberately `#[^\s#]+`
  rather than `#\w+`, because `\w` excludes Devanagari combining marks and would
  split the regional hashtags the format is built around
  (`app/audit_suggestion.py:45`);
- the platform gate must agree with `AuditSuggestion.rejection()` on every
  fixture by *calling* it, not by restating its thresholds.

## Open questions

1. **`UCc4Tv_DEGDEKrKAt-vyVNmw` — "Taarak Mehta Ka Ooltah Chashmah Baalgeet
   Haryanvi" — has `default_language = NULL` and is the only autopilot-enabled
   channel.** `audit_video` falls back to `"en"`, so all 57 of its August
   applies got English-only metadata for a Haryanvi audience. This is a live
   content bug, not a scoring question, and it is invisible for exactly the
   reason the hashtag counts were. One field fixes it; a human picks the value.
2. **Which properties should reflection be allowed to change?** Today the
   house-format block forbids all of them. As evidence accrues, each property
   that shows no effect is a candidate for release from that block. The
   mechanism for deciding — and who decides — is not designed here.
3. **Does the tag-character budget matter at all?** Observed medians are
   217–392 against a 500 ceiling, so no channel is close. Whether more tag
   characters earn CTR is exactly the kind of question this join exists to
   answer, and exactly the kind that cannot be answered at n=171.

## What this deliberately does not do

It does not gate prompt promotion, and it does not enforce the house format. The
parent spec defers gating until a judge can be calibrated; gating on format
alone would assert only that a candidate is well-formed, which
`AuditSuggestion.rejection()` already enforces at apply time.

It also does not make Midas agentic. That needs the audit model to gather
information nobody pre-selected and to make decisions nobody pre-decided — tools
and a loop, designed separately. This document's contribution to that is
narrower and prior: it turns "the house format is non-negotiable" into a claim
with evidence attached, so the constraints an agent inherits are the ones that
earned their place.
