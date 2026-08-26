# The tool-using audit agent

Date: 2026-08-26
Status: approved, not started
Depends on nothing already built. Related: the observability work
(`2026-08-23-observability-evidence-loop-design.md`) supplies the tracing this
design leans on, and the format-properties work
(`2026-08-24-format-scorers-design.md`) supplies the evidence that decides
whether the constraints this agent inherits deserve to survive.

## Why

Midas today makes one LLM call per audit. The model receives a string another
part of the program assembled — current metadata, transcript, channel language —
and returns a rewrite. It cannot ask a question. It cannot look anything up. It
cannot know that this channel's highest-CTR videos all front-load the rhyme
name, because nobody put that in the string.

Meanwhile the database holds **1,083,011 rows** of per-video daily impressions
and click-through rate, 49,144 videos, and 2,865 audits — 171 of them carrying a
measured CTR verdict. All of it is invisible at audit time.

That gap is the whole reason for this document. Not "agents are good", but: the
system already knows which titles earn clicks on this channel, and the thing
writing the titles has never been allowed to see it.

**What this is not.** Wrapping the existing call in a framework and calling it
an agent. If the model ends up calling the same tools in the same order on every
video, this design has produced automation with more latency, and §Falsifying
the agency says how we will know.

## Decisions taken before design

Recorded because each closes off alternatives a reader would otherwise reopen.

- **Purpose: learn from what already worked.** Of the candidate purposes —
  triage, generalising to unseen channels, explaining its reasoning — this is
  the one where the agent gets measurably better as the evidence loop fills up.
- **Pure tools, no pre-computed context block.** The model starts from a video
  id and asks for everything, including the transcript and the current metadata.
  The cheaper hybrid (pre-fetch the universal, tools for the conditional) was
  rejected deliberately: it is a better-fed automation, and the point is to find
  out whether the model's judgement about what it needs beats ours.
- **LangGraph runs the loop.** A hand-rolled loop would be ~80 lines and no new
  dependency; LangGraph was chosen for structure that survives the loop growing
  branches. §Orchestration records what that costs.
- **The house format stays, for now.** Its rules are unvalidated priors, and the
  parallel format-properties work makes them falsifiable rather than enforcing
  them. The agent inherits today's constraints; evidence removes them later.

## Orchestration

`langchain.agents.create_agent` (LangChain 1.3.17), running on LangGraph 1.2.11.

Verified against the packages themselves rather than documentation, because the
API has moved and the search results contradict each other:

- `langgraph.prebuilt` **does not exist** in LangGraph 1.2.11. The subpackages
  are `graph`, `func`, `pregel`, `channels`, `managed`, `stream`, `utils`.
- The agent factory now lives in `langchain.agents`, and it is **`create_agent`**,
  not `create_react_agent`. Confirmed by reading `langchain/agents/__init__.py`
  in the 1.3.17 wheel: it exports exactly `AgentState` and `create_agent`.
- Its signature is
  `create_agent(model, tools, *, system_prompt, middleware, checkpointer, ...)`.
  Note `response_format` and `state_schema` are typed `None` — **there is no
  structured-output parameter any more.** That is why the answer is a tool
  (§The answer is a tool).

The model is `ChatOpenAI` pointed at OpenRouter's base URL, so the existing
`OPENROUTER_API_KEY` and `AUDIT_MODEL` (`anthropic/claude-haiku-4.5`) keep
working. OpenRouter implements OpenAI-shape tool calling, so no adapter is
needed.

**Cost of this choice, stated plainly.** LangGraph plus LangChain plus
`langchain-openai` is a large dependency tree in a `requirements.txt` where every
pin carries a comment justifying it. It also introduces a second execution model
alongside APScheduler. Neither is fatal; both are real, and a hand-rolled loop
remains the fallback if the dependency proves troublesome.

**Tracing.** `openinference-instrumentation-langchain` (0.1.72) instruments the
graph natively. Its setup call goes **inside `app/tracing.py::configure()`**, so
the "only `app/tracing.py` imports OpenTelemetry" guard test still holds — the
seam survives, and Phoenix gets the full trajectory for free.

## Shape

New package `app/agent/`, three files with one job each:

- `tools.py` — the tool surface and its return schemas.
- `graph.py` — `create_agent` wiring, model construction, system prompt.
- `run.py` — one entry point: `run_agentic_audit(video_id) -> AuditSuggestion`.

**It does not replace `audit_video()`.** It is a second path behind a per-channel
flag, and both converge on `AuditSuggestion.from_llm(...)`. The agent therefore
inherits every existing guarantee without restating any of them: the 15-hashtag
cap, `rejection()`, autopilot's quarantine of invalid output, the apply-time
override path, the prompt-version attribution. **The agent decides what to
write; it does not get to decide what YouTube will accept.**

### The answer is a tool

LangGraph 1.x removed structured-output parameters, so the run finishes when the
model calls `submit_audit(title, description, tags, reasoning)`.

This is better than parsing a final text message, for three reasons: the tool
schema enforces the shape at the boundary; "done" becomes an explicit act rather
than an inference from the model falling silent; and a run that never submits is
cleanly detectable as a failure instead of yielding half an audit.

The submitted payload is mapped to the shape `AuditSuggestion.from_llm()`
already decodes, so there is exactly one decoder for LLM output in this codebase.

## Tools

Six. Each has a hard cap and returns a compact shape, never raw rows — an agent
design fails when a tool returns 500 records and buries the signal in the
model's own context.

**`get_channel_top_performers(channel_id, limit=10, order="best"|"worst")`**
The centerpiece: aggregates `video_reach_daily` per video over a recent window,
weights CTR by impressions, returns title, tags, CTR and impressions.

Two constraints that matter more than they look:

- It **must** filter on `settings.MIN_IMPRESSIONS` (500) — the same floor
  `measurement.py` uses to decide a video carries signal. Without it a video
  with 3 impressions and one click ranks as a 33% CTR champion and the model
  learns from noise. Reuse the constant; do not pick a new number. This is the
  same single-ownership discipline `app/verdicts.py` already enforces for win
  rate, and `tests/test_verdicts.py` has guard tests for exactly this class of
  drift.
- `order="worst"` is deliberate, not symmetry for its own sake. "What does a
  title that fails on this channel look like" is as instructive as its inverse,
  and it costs one parameter.

**`get_audit_history(video_id, limit=5)`** — past attempts and what they
measured. Built on `verdicts.from_audit()` and `verdicts.levers()`, never a
reimplementation, so what the model is told an audit did agrees with what the
dashboard says it did.

**`get_video(video_id)`** — current title, description, tags, publish date,
`is_short`.

**`get_transcript(video_id)`** — the existing cached `video_transcripts` path,
truncated to a fixed character budget.

**`search_competitors(query, limit=10)`** — the only tool that spends money.
`Op.SEARCH_LIST` costs **100 units** against a 10,000/day quota, so: gated on
`quota.can_afford()`, capped per run, and logged through the existing
`_log_quota` path so it appears in `quota_log` like every other metered call. A
curious model must not be able to consume the fleet's daily apply budget.

**`submit_audit(title, description, tags, reasoning)`** — terminal.

### Cut before specification

`find_similar_videos`, backed by `video_embeddings`, was designed and then
dropped: coverage is **1,233 of 49,144 videos (2.5%)**. A tool that returns
nothing 97% of the time teaches the model to stop calling it and burns an
iteration each time it tries. Backfilling embeddings is separate work that needs
its own justification.

### Errors are returned, not raised

A tool that fails hands the model its error text as the tool result. A missing
transcript is information to route around, not a crashed audit. This is what
makes the loop robust rather than brittle, and it is the difference between an
agent and a pipeline with extra steps.

## Budgets

Three, all required.

**Iterations** — a cap of ~12 model turns. Exceeding it fails the audit rather
than applying a half-formed one.

**YouTube quota** — `search_competitors` capped per run and gated on
`quota.can_afford()`.

**Wall clock** — autopilot ticks every 100 seconds with `max_instances=1` and
`coalesce=True`, so a slow audit causes the next tick to be skipped rather than
to pile up. Throughput degrades; correctness does not. (The `.env` previously set
`AUTOPILOT_TICK_SECONDS` twice, 900 then 100, with the second silently winning;
that has been corrected.)

## Failure modes

Every one lands on a path that already exists, which is the point of converging
on `AuditSuggestion`:

| Failure | Handling |
|---|---|
| A tool raises | Error text returned to the model as the tool result; it adapts |
| Iteration cap hit with no `submit_audit` | Audit fails → existing quarantine path |
| `submit_audit` called with invalid content | `AuditSuggestion.rejection()` → existing quarantine |
| The run dies outright | Autopilot's existing `except Exception` → `_record_failure` |
| OpenRouter times out | Existing two-timeouts-then-skip logic in `tick()` |

## Falsifying the agency

The section this design is answerable to.

Every run records its trajectory — which tools were called, in what order, with
what arguments — on the audit row, and Phoenix captures the same thing through
the LangChain instrumentor. That is not bookkeeping. It is the test of whether
the agency is real:

- **If the traces show the same tools in the same order on every video**, this
  is automation with more latency and a larger dependency tree, and the honest
  response is to collapse it back to a pre-computed context block, which would
  be cheaper and deterministic.
- **If tool choice varies meaningfully by video** — skipping the transcript when
  the title already describes the content, reaching for competitors only when
  the channel's own history is thin — then the model's judgement is doing work
  no fixed block could.

This is a claim with a stated way to be wrong, and the answer arrives from
traces rather than from anyone's opinion.

It also mitigates the cost of pure tools: because context now varies per run,
comparing two prompt versions is noisier than before. Shadow comparisons must
therefore be distributional over many videos rather than paired, and when two
runs differ the recorded trajectory shows whether the cause was the prompt or
the context.

## Testing

- **Tools are pure and independently testable.** Each gets table-driven tests
  against fixture data with no model in the loop.
- `get_channel_top_performers` must **exclude** a video below
  `settings.MIN_IMPRESSIONS` even when its CTR is the highest in the channel —
  the noise case that motivates the floor.
- `get_audit_history` must agree with `verdicts.from_audit()` by calling it, not
  by restating its logic.
- **The loop is tested with a scripted fake model** that emits a fixed sequence
  of tool calls, so loop mechanics — iteration cap, error-return, terminal tool
  — are verified without network or spend.
- A tool that raises must produce a tool result the model can read, and must not
  propagate.
- A run that hits the iteration cap without calling `submit_audit` must fail
  cleanly and quarantine, never apply.
- `search_competitors` must not execute when `quota.can_afford()` is false.
- The existing guard test that only `app/tracing.py` imports OpenTelemetry must
  still pass with the LangChain instrumentor installed.

## Open questions

1. **Which channel runs it first?** The per-channel flag makes this a choice,
   and the answer is not obvious: the only autopilot-enabled channel is also the
   only one whose outcomes are about to start being measured, so running the
   agent there immediately confounds "did the agent help" with "did measurement
   start working". Consider waiting for a baseline.
2. **Does the model get told the house format at all?** Today's prompt asserts
   it as non-negotiable. An agent that can see which titles actually win might
   reasonably conclude the format is wrong — and under the current design it
   still has to obey it. That tension is real, and resolving it is what the
   format-properties evidence is for.
3. **Iteration cap of 12 is a guess.** It should be set from observed
   trajectories once traces exist, not defended as a principled number.
