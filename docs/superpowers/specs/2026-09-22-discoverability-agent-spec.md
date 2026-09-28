# The discoverability agent — implementation spec

Date: 2026-09-22
Status: superseded by `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` (2026-09-23); kept for history
Supersedes: the earlier draft of today (`2026-09-22-audit-agent-implementation-spec.md`, deleted) — that draft faithfully transcribed the planned diagram and issue #8, and in doing so inherited their central mistake: it scoped the agent to **metadata rewrite only**. This spec is the corrected design.
Reference: `docs/agentic-workflow-planned.excalidraw`, `2026-08-26-tool-using-audit-agent-design.md`, issue #8.

---

## 0. Why this replaces the audit-agent spec

Three operational learnings from the team invalidated the previous scope:

1. **The team sees SEO impact in ~1 week**, doing this by hand. A system built on a 21-day measurement window that "gets smarter at month 6" is running on a clock 3× too slow and cannot claim to match — let alone beat — the humans.
2. **Metadata rewrite alone is too thin to justify an agent.** With one lever, the model calls the same tools in the same order on every video — the exact failure the 2026-08-26 design named as "automation with more latency." No branch point, no judgment, no agent.
3. **The levers the team actually uses were not in scope at all:**
   - **Description backlinks** — they add links to the channel's top videos in a video's description. Midas has never done this.
   - **Playlist placement** — they add videos to playlists for visibility. Midas has a whole playlist subsystem (`app/playlists.py`) built for this, sitting **disconnected** from the audit flow; the previous spec even listed it *out of scope*.

The reframe: the agent's job is not "rewrite metadata." It is **"improve this video's discoverability using the channel's own catalog,"** across three levers — metadata, description backlinks, and playlist placement. This is simultaneously (a) what the team credits for weekly impact and (b) what finally makes the task genuinely agentic, because *which* links and *which* playlists are correct is a per-video, catalog-dependent judgment a fixed prompt cannot make.

### The invariant, restated for the new scope

- **Metadata + backlinks** still converge on `AuditSuggestion` and flow through the existing `validate → videos.update (50u)` path. Backlinks are structured input the agent chooses; we render them into the description canonically (§3.3), so they stay measurable and can't be malformed.
- **Playlist placement is a new action path** (`playlistItems.insert`, 50u) — this is the one place the "Step 9 only, apply path unchanged" invariant genuinely breaks, and this spec owns that cost explicitly.
- Second path behind `channels.agent_enabled`; `audit_video()` remains the fallback (flag off, or cold-start).

---

## 0.5 · Deliberately scrapped from the prior plan (and two unresolved dissents)

The audit-agent plan (issue #8 + the 2026-08-26 design doc + the diagram) got the *foundation* right and the *scope and sequencing* wrong. What this spec drops from it, and why — recorded so it doesn't creep back.

**Settled scraps (this spec already reflects these):**

1. **Metadata-only Phase A / playlists out-of-scope.** The prior plan shipped the lever the team credits *least* for visibility first and deferred the two they credit *most*. Scrapped: levers are sequenced by measured impact (§6), not by what's cheapest to bolt onto the existing apply path.
2. **The ~3-week learning clock and "smarter at month 6."** Scrapped for a weekly, leading-indicator loop (§1). A measurement window survives for statistical honesty; it is no longer the gate on the system getting smarter.
3. **Whole-prompt reflection rewriting as the memory.** Today's learning rewrites an opaque per-channel prompt blob on detected harm — coarse, channel-global, un-attributable. Scrapped for a structured, per-lever playbook exposed as a tool (§5). The harm-detection / champion–challenger scaffolding is reusable; the blob rewrite is not carried over.
4. **Fleet autonomy (tier 1/2/3) as the organizing driver.** Scrapped as a *structuring principle*. The organizing question is "does the agent beat the humans on **one** channel, measured weekly" — autonomy and per-channel budgets are a deployment concern proven *after* the core value is, not a frame that pulls orchestration tiers forward. They land in Slice 4 (§6), not the design's spine.
5. **The blind single call itself** (the flow this replaces) — writing metadata without ever seeing measured CTR. Non-negotiable scrap; it is the whole reason for the pivot.

**Two unresolved dissents — decisions currently standing in this doc that I recommend reversing:**

> These followed an explicit user override (2026-09-22) of issue #8's cuts. I disagree on the engineering merits and record it here rather than silently flip a decision the user made. **Not yet actioned — needs a call.**

6. **LangGraph → revert to a hand-rolled loop.** The design doc's own justification is "structure that survives the loop growing branches" that do not exist yet — speculative generality, a large dependency tree, and a second execution model alongside APScheduler. The falsifiability test (does tool choice actually vary per video?) must run *before* anyone knows the loop needs branches, and an ~80-line hand-rolled loop is more debuggable while finding out. Recommend: hand-rolled in v1; adopt LangGraph only if traces prove the loop is growing real branches. **Doc currently says LangGraph IN (§3).**
7. **`search_competitors` ($) → cut from v1.** The only tool that spends money, a quota-attack surface handed to a model, and it returns *inferred* competitor structure — which cuts against the "learn from what actually worked" thesis the rest of the design rests on. Recommend: ship the free tools; add it later only if traces show the agent genuinely reaching for it. **Doc currently includes it (§3.1).**

**Caveats against this spec's own bets (honesty, not the prior plan):**

8. **Backlinks as a *learnable* lever are contingent on the §9 traffic-source probe.** If `insightTrafficSourceType` can't attribute related-traffic lift, backlinks become a "do but can't learn from" action — a conscious decision to make, not a gap to paper over.
9. **Metadata rewrite may not deserve headline-lever status.** If the team's impact is distribution (backlinks + playlists) and the house-format title is already near-optimal, title-rewriting could be low-value inertia. Test whether it earns the agent's turns against measured CTR; don't assume it.

**Kept deliberately (so "scrap" is not read as scorched earth):** the sensor layer (`metrics_poll`, `reporting_poll`, `reach.py`, `video_reach_daily`), the `validate → videos.update` apply path, the `AuditSuggestion` decoder, quota, `status_vocab`, Certification — and the playlist *machinery* (`app/playlists.py`). What gets scrapped there is the playlist system's *disconnection* from the audit flow and its *embedding substrate* (§4 pre-req), never the code.

---

## 1. The learning loop — weekly, leading-indicator, continuous

This is the part the previous spec got most wrong, so it comes first.

**Cadence.** The learning clock moves to **weekly**, matching the team. The per-video work rate (autopilot `tick()` every 100s) is unchanged; what changes is measurement + playbook rebuild.

**Signal per lever** (decision: leading indicators + weekly directional — *not* statistical significance, *not* per-lever causal attribution):

| Lever | Leading indicator (≈7-day window) | Source |
|---|---|---|
| Metadata | CTR vs the video's own pre-change baseline | `video_reach_daily` / `video_metrics` (as today, shorter window) |
| Description backlinks | Lift in the **linked-to** videos' traffic from related/suggested sources, and the source video's session signal | `insightTrafficSourceType` (RELATED_VIDEO / SUGGESTED) — **needs a live probe, §8** |
| Playlist placement | `playlistStarts`, `viewsPerPlaylistStart`, `averageTimeInPlaylist` on the joined playlist + the video's playlist-source views | `playlist_metrics` (from the PO sensor work) |

**Directional, not significant.** A lever is judged by whether its indicator moved the right way over a week, accepting noise. To avoid learning from noise, the **playbook only commits a strategy once the direction is consistent across multiple videos** (distributional, echoing the design doc's note that per-run context now varies so comparisons must be distributional, not paired). One video is an anecdote; a consistent weekly pattern across the channel is a lesson.

**Continuous, not gated-for-months.** The playbook (§5) rebuilds **every week** from the latest outcomes once past a small floor — it does not wait for 15 CTR-significant outcomes accrued over a quarter. The system is expected to improve from **week 1**, not month 6. That is the whole point of the reframe.

**`MIN_IMPRESSIONS` tension (open, §9).** Some videos won't reach `MIN_IMPRESSIONS=500` in 7 days. Those either get a longer adaptive window or are excluded from that week's learning — decided in §9, not silently dropped.

---

## 2. Seams this plugs into (verified 2026-09-22)

Everything from the prior spec's seam table, plus the playlist machinery that already exists:

| Concern | Location |
|---|---|
| One-shot audit (branch around) | `app/audits.py:267` `audit_video()`; call at `:362` |
| Apply path (metadata + backlinks ride this) | `app/audits.py:426` `apply_audit_internal` → `yt_videos_update` `:497`; `app/youtube_client.py:169` |
| Autopilot call site (branch here) | `app/autopilot.py:557` |
| Contract / decoder | `app/audit_suggestion.py` `AuditSuggestion.from_llm` / `.rejection` |
| Metadata evidence | `app/reach.py` `aggregate`/`weighted_ctr`/`certify`; `video_reach_daily` |
| Verdicts | `app/verdicts.py` `from_audit`, `levers` |
| **Playlist writes (already built)** | `app/youtube_client.py` `yt_playlist_items_insert` / `yt_playlists_insert` / `yt_playlist_items_delete` |
| **Playlist fit judgment (already built)** | `app/playlists.py` `_llm_judge`, `join_pass(channel_id, video_id)`, `reconcile_channel` |
| **Playlist inventory / health / proposals** | `app/playlists.py` `_serialize_playlists`; `playlist_proposals` + `playlist_assignments` tables |
| Playlist quota | `app/quota.py` `Op.PLAYLIST_ITEMS_INSERT = 50`, `PLAYLISTS_INSERT = 50` |
| Measurement floor | `app/config.py` `MIN_IMPRESSIONS = 500`; `app/measurement.py judge_reach` |
| Quota gate | `app/quota.py` `can_afford`, `cost_of`, `JobBudget`; `YT_DAILY_QUOTA = 10000`; `Op.SEARCH_LIST = 100u` |
| Status vocab (no renames) | `app/status_vocab.py` (+ guard test) |
| Tracing seam | `app/tracing.py::configure()` |
| Test fakes / offline guard | `tests/fakes.py` `FakeSupabase`; `tests/conftest.py` `_no_network` |

`app/agent/` is greenfield. Description-backlink injection does **not** exist anywhere — net-new.

---

## 3. The agent — `app/agent/`

`tools.py`, `graph.py` (`langchain.agents.create_agent`, LangGraph 1.2.11 / LangChain 1.3.17, `ChatOpenAI`→OpenRouter, `AUDIT_MODEL = anthropic/claude-haiku-4.5`), `run.py` → `run_discoverability_audit(video_id) -> dict` (same row-dict shape as `audit_video`). Tracing via `openinference-instrumentation-langchain` wired **inside `app/tracing.py::configure()`** so the OpenTelemetry-isolation guard holds; trajectory persisted on the audit row.

### 3.1 Read / context tools

Each pure, hard-capped, compact return, **errors returned-not-raised**.

- `get_video(video_id)` — title/desc/tags/publish_date/is_short.
- `get_transcript(video_id)` — cached `transcripts.fetch_transcript`, truncated.
- `get_audit_history(video_id, limit=5)` — **calls** `verdicts.from_audit()` + `levers()`.
- ★ `get_channel_top_performers(channel_id, limit=10, order="best"|"worst")` — aggregate `video_reach_daily`, weight CTR by impressions, **filter on `settings.MIN_IMPRESSIONS`** (reuse the constant). Metadata evidence.
- **`get_related_top_performers(video_id, limit=10)`** — *for backlink selection*: the channel's top performers **topically relevant to this video**. Embeddings are unusable here (2.5% coverage), so relevance = tag/title overlap + the model's own judgment over candidates, not a vector search. Returns candidates with title + CTR + impressions so the model picks links that are both relevant *and* proven.
- **`get_playlists(channel_id)`** — *for placement*: the channel's playlists with role/health and current membership summary, from `playlists._serialize_playlists`. Lets the model decide fit and spot a missing playlist.
- `get_channel_playbook(channel_id)` — §5; empty below the floor.
- `search_competitors(query, limit=10)` — the only paid tool (`Op.SEARCH_LIST`, 100u): **gated on `quota.can_afford()`**, capped per run, logged via `_log_quota` into `quota_log`.

### 3.2 Action tools

- **`submit_audit(title, description, tags, reasoning, recommended_links, playlist_recommendations)`** — terminal. Carries all three levers:
  - `title/description/tags` → `AuditSuggestion.from_llm` (unchanged decoder).
  - `recommended_links: [video_id, ...]` → §3.3, rendered into the description.
  - `playlist_recommendations: [{playlist_id | new_playlist_title, reason}]` → §4, queued as proposals (Slice 2), not applied inline.

There is **one terminal tool** and **one decoder**, preserved. Backlinks and playlist recommendations are additional structured fields on the same submission, not a second exit.

### 3.3 Backlinks — structured, canonical, capped

The agent does **not** write raw URLs into the description. It chooses `recommended_links` (video ids from `get_related_top_performers`); the apply path renders them into a **canonical "Related videos" block** appended to the description, using each target's real watch URL. This:

- keeps the description well-formed (no hallucinated/malformed links),
- makes the backlink **measurable** (we know exactly which links were added, when — the anchor for §1's backlink indicator),
- caps the count (**start ≤3–5**, tune) so it reads as curation, not spam (§8 risk).

Because it lands in the description, it flows through the **existing** `videos.update` apply path — no new write path for Slice 1.

### 3.4 Loop, cold-start, budgets, failure modes

Unchanged from the prior spec, and now genuinely exercised:
- ≤12 turns; no `submit_audit` → quarantine, never apply. Cap is a guess — tune from traces (§9).
- Cold-start: `reach.certify(channel_id)` fails → skip agent, fall back to `audit_video`.
- Budgets: iterations, YouTube quota (`search_competitors` gated), wall-clock (`max_instances=1, coalesce=True`).
- Failures land on existing paths: tool raises → error text to model; run dies → autopilot `_record_failure`; invalid submit → `rejection()` → quarantine.
- **Falsifiability now has teeth.** With three catalog-dependent levers, tool choice *should* vary: a self-explanatory title skips heavy metadata work; a video already well-placed needs no playlist tool; a niche video with few relevant top performers gets no backlinks. If traces still show identical tool order everywhere, collapse to a context block — but the reframe is precisely what gives the agency something to prove.

---

## 4. Playlist placement — recommend-only first, flip per-channel

Decision: **recommend-only at first, auto per-channel once trustworthy.**

- The agent's `playlist_recommendations` are written to the existing **`playlist_proposals`** table for human confirmation — *not* applied inline. Fit is sanity-checked with the existing `playlists._llm_judge`.
- Confirmed proposals apply via the existing `join_pass` / `yt_playlist_items_insert`.
- Once a channel's recommendations have been trustworthy for a sustained window, flip a per-channel gate so **adds** auto-apply behind the flag (adds are non-destructive). **New-playlist creation and any deletes stay human-confirmed** longer — they're higher blast-radius.
- This reuses `app/playlists.py` wholesale; the new work is *connecting* it to the agent's output and measuring the result (§1), not rebuilding it.
- **Pre-req — homogenize the embedding substrate.** Playlist similarity currently runs on a heterogeneous vector space: `bootstrap_embeddings` embeds **title-only**, `autopilot.py:453` embeds **title + transcript[:6000]**, both under the *same* `model_version` — so cosine scores compare an inconsistent basis, and the `0.72 / 0.55` bands sit on shaky ground. Before the agent trusts `≥ PLAYLIST_JOIN_HIGH (0.72)` direct-adds, embed **one consistent input for every video**, re-embed under a **new `model_version`**, and recalibrate the two bands on the new distribution. Until that's done, placement stays recommend-only regardless of channel trust. (Chunking is *not* the fix — one vector per video is the right granularity for whole-video→playlist classification; consistency and content fidelity are what's missing.)

---

## 5. Playbook — continuous, three-lever (the "gets smarter" mechanism)

- `channels.playbook_json` (distinct from `style_profile_json`). `app/playbook.py::build_playbook(channel_id)` LLM-distills weekly outcomes across **all three levers** — which title patterns won, which backlink choices drove related traffic, which playlist placements drove starts — plus `levers()` and Reach/playlist deltas. Respects `default_language`. States the signal is correlational.
- **Exposed as the `get_channel_playbook` tool** (§3.1), *not* a prepended context block — consistent with "the agent asks," and its use shows in the trajectory so we can see whether the playbook actually helps.
- **Rebuilds weekly** past a small floor (avoid learning from 1–2 points), not gated behind months. Below floor → tool returns empty; agent falls back to top-performers + generic logic.

---

## 6. Slicing (ship order)

1. **Slice 1 — metadata + backlinks.** The agent, its read tools, `get_related_top_performers`, the canonical backlink block, weekly metadata + backlink measurement. Shares the existing apply path — fastest to a live, learning deploy on one certified channel.
2. **Slice 2 — playlist placement (fast-follow).** `get_playlists`, `playlist_recommendations`, proposal queue + confirm flow, playlist measurement. Recommend-only.
3. **Slice 3 — continuous playbook** across all three levers (needs a few weeks of Slice 1/2 outcomes).
4. **Slice 4 — fleet autonomy.** `decline` terminal outcome (valid "nothing worth changing", 0 apply quota; add to `status_vocab` + mirror + guard, distinct from `rejection()`); per-channel quota share of `YT_DAILY_QUOTA` via `JobBudget` (channel exhausts share → pauses alone).

Slices 1–2 are the weekly-impact core and ship close together. 3–4 accrue on the weekly clock — weeks, not months.

---

## 7. Testing (seams, not internals)

- **Loop** — scripted fake model (`patch` the model boundary in `app.agent.graph`): cap→quarantine, tool-raise→readable, invalid submit→`rejection()`, `decline`→outcome+0 quota.
- **Tools** — pure vs `FakeSupabase`: `MIN_IMPRESSIONS` exclusion; `get_audit_history` agrees with `verdicts.from_audit()` by calling it; `get_related_top_performers` returns only ≥floor candidates; `search_competitors` no-ops when `can_afford()` false; backlink renderer caps count and emits valid URLs; playlist recommendations land in `playlist_proposals`, not a live insert, while recommend-only.
- **Contract** — `submit_audit` metadata → `from_llm` → identical row; backlink field renders deterministically.
- **Measurement** — leading-indicator eval writes directional verdicts on a 7-day fixture; playbook commits a strategy only when the direction is consistent across N videos.
- **Tracing** guard passes with the instrumentor. **Offline** guard (`_no_network`) stays green; live tests marked `live`.

---

## 8. Honest risks

1. **Backlink measurement is the weakest link in the loop.** YouTube's `insightTrafficSourceType` is coarse; isolating a description backlink's causal effect is genuinely hard. If we can't get a usable signal, backlinks become a lever we *do* but can't *learn* from — which half-defeats the closed loop. **This needs a live probe before we commit** (as Phase 0 did for CTR metric names). Named in §9.
2. **Spam / ToS.** Over-linking descriptions and stuffing playlists can look manipulative and risk ranking penalties. Mitigations: hard caps (≤3–5 links), relevance-gated candidates, `_llm_judge` fit for playlists, recommend-only start. The agent's per-video judgment is the safeguard — a blunt automation is exactly what we're avoiding.
3. **Directional signal can mislead.** Weekly directional movement is confoundable (a video trending for unrelated reasons). Mitigation: distributional commitment (§1) — no strategy enters the playbook off one video.
4. **The invariant break is real work.** Playlist placement is a new write path with its own quota, validation, measurement, and failure handling — more than "Step 9 only." Slice 2 owns that; Slice 1 deliberately avoids it by riding the description.
5. **LangGraph dependency cost** — large tree, second execution model alongside APScheduler. Hand-rolled loop remains the documented fallback.

---

## 9. Open questions (resolve before/while building)

1. **Backlink signal — live probe.** Which `insightTrafficSourceType` fields are actually populated and granular enough to attribute related-traffic lift to a description block? Answer from one real Analytics query before building the backlink eval.
2. **Weekly window vs `MIN_IMPRESSIONS`.** Low-traffic videos won't clear 500 impressions in 7 days. Adaptive window per video-traffic, or exclude from that week's learning? (Do not silently drop.)
3. **Backlink/placement caps.** Start ≤3–5 links and a small max playlists/video; tune from outcomes.
4. **Iteration cap of 12** — set from traces.
5. **House format** — an agent that can see what wins may conclude the format is wrong yet must obey it; resolved by the separate format-properties evidence.
6. **First rollout channel** — the confound that the only autopilot-enabled channel is also the only one just starting to be measured.

## 10. Pre-req blocker

The rollout-candidate channel has **`default_language = NULL`** → wrong-language metadata (and now wrong-language backlink blocks) to a Haryanvi audience. Set it (`bgc`) before the channel becomes rollout #1. Vocabulary per `CONTEXT.md` (Reach, Coverage, Window, Certification; measurement-status vs outcome-decision).
