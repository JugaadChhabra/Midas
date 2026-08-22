import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException

from app import verdicts
from app.config import settings
from app.db import supabase
from app.channel_audits import audits_for_channel, fetch_all
from app.openrouter import chat_json, chat_text
from app.youtube_client import youtube_for_channel, yt_search_videos
from app.audits import audit_video
from app.status_vocab import (
    AuditStatus,
    MEASURED_STATUSES,
    MeasurementStatus,
    PromptVersionStatus,
    PROMOTING_REFLECTION_MODES,
    ReflectionMode,
)

log = logging.getLogger("midas.reflection")

router = APIRouter(tags=["reflection"])

#: Reflection fires on evidence of HARM, never on an absence of wins.
#:
#: The rule this replaces was `win_rate < 50 -> reflect`, and it could not do
#: anything else. `verdicts.win_rate` counts neutral in its denominator — by
#: design, because neutral is a measured outcome — and neutral is what a
#: metadata rewrite does to CTR most of the time. Measured over the 171 verdicts
#: that existed on 2026-08-23 the fleet ran 147 neutral / 21 win / 3 regression,
#: a win rate of 12.3%. So the trigger returned `low_win_rate` every cooldown
#: from 2026-05 onward: five candidate prompts, none promoted, each opening its
#: diagnosis with a "core failure" it had been handed as a premise by a prompt
#: that asked it to explain underperformance it was told to assume.
#:
#: Wins outnumbering regressions 7:1 is a prompt that helps when it does
#: anything at all. What warrants a rewrite is the prompt doing damage:
#: regressions outnumbering wins, the median delta actually negative, or one
#: lever consistently harmful. Absence of movement is not damage.
#:
#: The 65%-win-rate "performing well" ceiling is gone with it. It was
#: unreachable for the same reason — no neutral-dominant channel can clear it —
#: and an unreachable early-return only hid the branches below it.
_MIN_DATA_POINTS = 10
#: Median CTR delta below this counts as a real decline rather than flat noise.
_NEGATIVE_MEDIAN_PCT = -2.0
#: A single lever's average delta below this is consistently harmful.
_NEGATIVE_LEVER_PCT = -5.0
_REFLECT_COOLDOWN_DAYS = 7

# Loop 1 verdicts that count as evidence. `not_applicable` is excluded on
# purpose: it means the audit was never measured (dormant pre-window, missing
# timestamp), not that it performed neutrally.


# ── Performance report ────────────────────────────────────────────────────────

def _build_perf_report(channel_id: str) -> dict | None:
    """Build a structured performance report from MEASURED CTR outcomes.

    Reads Loop 1's verdicts (audits.measurement_status + measurement_result),
    never raw view counts. `not_applicable` rows are excluded: they were never
    measured, so they carry no evidence either way. Returns None if fewer than
    _MIN_DATA_POINTS audits have a verdict — the prompt loop must not run on a
    signal too thin to trust.

    Why not view velocity (what this used to do): it compared a video's
    LIFETIME average views/day against its post-apply rate. View curves decay,
    so the baseline is systematically inflated — measured across 439 audits
    with a real pre-apply window it was too high in 100% of cases, median 25.8x,
    scoring an audit that changed nothing at -96%. Correcting the baseline is
    not sufficient either: any before/after on raw views is dominated by decay,
    which is why this needs CTR over the symmetric windows measurement.py
    already builds.
    """
    audits = fetch_all(
        audits_for_channel(
            channel_id,
            "id,video_id,applied_at,suggested_title,title_before,"
            "suggested_description,description_before,"
            "suggested_tags,tags_before,"
            "measurement_status,measurement_result,ai_reasoning",
        )
        .in_("measurement_status", list(MEASURED_STATUSES))
    )
    if not audits:
        return None

    now = datetime.now(timezone.utc)
    enriched = []

    for a in audits:
        status = a.get("measurement_status")
        if status not in MEASURED_STATUSES:
            continue
        applied_at = a.get("applied_at")
        try:
            ap = datetime.fromisoformat((applied_at or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        # `neutral` can legitimately carry no delta (pre_ctr was 0, or post
        # impressions were under the floor). It is still a measured verdict, so
        # it counts toward the win rate — it just can't contribute to the median.
        verdict = verdicts.from_audit(a)
        delta = verdict.ctr_delta if verdict else None
        moved = verdicts.levers(a)
        enriched.append({
            "audit_id": a["id"],
            "measurement_status": status,
            "ctr_delta_pct": (delta * 100.0) if delta is not None else None,
            "ctr_delta": delta,
            "title_before": a.get("title_before"),
            "title_after": a.get("suggested_title"),
            "title_changed": verdicts.TITLE in moved,
            "desc_changed": verdicts.DESCRIPTION in moved,
            "tags_changed": verdicts.TAGS in moved,
            "ai_reasoning": a.get("ai_reasoning"),
            "is_recent": (now - ap) < timedelta(days=14),
        })

    if len(enriched) < _MIN_DATA_POINTS:
        return None

    win_rate = verdicts.win_rate(r["measurement_status"] for r in enriched)
    # The same population as win_rate's denominator, kept as counts. A win rate
    # alone cannot tell "mostly neutral" from "mostly regression" — both read
    # low — and the trigger below has to distinguish them, so the counts travel
    # with it. Owned by app.verdicts for the same reason the rate is.
    dist = verdicts.distribution(r["measurement_status"] for r in enriched)
    regression_count = sum(
        1 for r in enriched if r["is_recent"] and r["measurement_status"] == "regression"
    )

    # Aggregated from the raw fractions, not from the per-row percentages: the
    # UI and the prompt loop must not compute this number two different ways.
    median_delta = verdicts.median_ctr_delta_pct(r["ctr_delta"] for r in enriched)

    def _lever_avg(key: str) -> float | None:
        sub = [r["ctr_delta_pct"] for r in enriched
               if r[key] and r["ctr_delta_pct"] is not None]
        return round(sum(sub) / len(sub), 1) if sub else None

    # Rank on the delta; verdict-only rows (no delta) sort to the middle so they
    # never masquerade as the best or worst example shown to the LLM.
    ranked = sorted(enriched, key=lambda r: (r["ctr_delta_pct"] is None, r["ctr_delta_pct"] or 0.0))
    return {
        "count": len(enriched),
        "win_rate": win_rate,
        "distribution": dist,
        "regression_count": regression_count,
        "median_ctr_delta_pct": median_delta,
        "levers": {
            "title": _lever_avg("title_changed"),
            "description": _lever_avg("desc_changed"),
            "tags": _lever_avg("tags_changed"),
        },
        "worst_audits": ranked[:2],
        "best_audits": ranked[-2:],
    }


# ── Trigger logic ─────────────────────────────────────────────────────────────

def _should_reflect(channel_id: str) -> tuple[bool, str]:
    """Return (should_reflect, reason)."""
    # Check cooldown — did we reflect in the last N days?
    last_rows = (
        supabase().table("prompt_versions")
        .select("created_at")
        .eq("channel_id", channel_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if last_rows:
        last_dt = datetime.fromisoformat(last_rows[0]["created_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - last_dt) < timedelta(days=_REFLECT_COOLDOWN_DAYS):
            return False, "reflected_recently"

    # The ONLY signal the prompt loop may act on is measured CTR. No verdicts
    # (or too few) means no reflection — a prompt rewrite is expensive and
    # self-reinforcing, so it must never fire on an unmeasured guess. This
    # channel's history is the cautionary case: a broken velocity metric
    # reported a 0.4% win rate every week and drove four prompt versions.
    report = _build_perf_report(channel_id)
    if report is None:
        return False, "no_measured_outcomes"

    # Three ways the evidence can show harm. Note what is NOT here: a low win
    # rate. See the threshold block at the top of this module for why — a
    # neutral-dominant channel is the normal case, not a failing one.
    dist = report["distribution"]
    if dist[MeasurementStatus.REGRESSION] > dist[MeasurementStatus.WIN]:
        return True, "regressions_outnumber_wins"

    median = report["median_ctr_delta_pct"]
    if median is not None and median < _NEGATIVE_MEDIAN_PCT:
        return True, "negative_median_delta"

    for lever, lift in report["levers"].items():
        if lift is not None and lift < _NEGATIVE_LEVER_PCT:
            return True, f"negative_lever_{lever}"

    return False, "performing_well"


# ── Niche extraction ──────────────────────────────────────────────────────────

def derive_niche_queries(channel_id: str) -> list[str]:
    """Derive 2-3 YouTube search queries from channel's own content. Stores result."""
    titles = [
        v["title"] for v in (
            supabase().table("videos")
            .select("title")
            .eq("channel_id", channel_id)
            .order("published_at", desc=True)
            .limit(15)
            .execute()
        ).data or []
        if v.get("title")
    ]

    tag_rows = (
        supabase().table("videos")
        .select("tags")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    tag_freq: dict[str, int] = {}
    for row in tag_rows:
        for tag in (row.get("tags") or []):
            tag_freq[tag] = tag_freq.get(tag, 0) + 1
    top_tags = sorted(tag_freq, key=lambda t: tag_freq[t], reverse=True)[:20]

    prompt = (
        f"This YouTube channel's most-used tags: {top_tags}\n"
        f"Sample video titles: {titles[:10]}\n\n"
        f"Produce 2-3 YouTube search queries that would find similar channels and videos. "
        f"Be specific to the actual content niche, not the broad category. "
        f'Return JSON: {{"queries": ["query1", "query2"]}}'
    )
    result = chat_json(prompt, model="anthropic/claude-haiku-4.5")
    queries = result.get("queries") or []
    queries = [q for q in queries if isinstance(q, str) and q.strip()][:3]

    supabase().table("audit_configs").update(
        {"niche_queries": queries}
    ).eq("channel_id", channel_id).execute()

    log.info("Derived niche queries for %s: %s", channel_id, queries)
    return queries


def get_or_derive_niche_queries(channel_id: str) -> list[str]:
    """Return cached niche queries or derive if not yet stored."""
    rows = (
        supabase().table("audit_configs")
        .select("niche_queries")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    cached = (rows[0].get("niche_queries") if rows else None) or []
    if cached:
        return cached
    return derive_niche_queries(channel_id)


# ── Competitive sampling ──────────────────────────────────────────────────────

def _sample_competitors(channel_id: str, niche_queries: list[str]) -> str:
    """Sample top-performing videos in niche via YouTube search. Returns formatted context string."""
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=90)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        yt = youtube_for_channel(channel_id)
    except Exception as e:
        log.warning("competitive_sample: could not build YouTube client: %s", e)
        return "(competitive data unavailable)"

    all_results: list[dict] = []
    for query in niche_queries[:2]:  # max 2 queries = 200 quota units
        try:
            results = yt_search_videos(yt, channel_id, query, max_results=10, published_after=published_after)
            all_results.extend(results)
        except Exception as e:
            log.warning("competitive_sample: search failed for '%s': %s", query, e)

    if not all_results:
        return "(competitive data unavailable)"

    lines = ["TOP PERFORMING VIDEOS IN YOUR NICHE (last 90 days):"]
    seen_titles: set[str] = set()
    for r in all_results:
        title = r.get("title", "")
        if title in seen_titles or not title:
            continue
        seen_titles.add(title)
        tags_preview = ", ".join(r.get("tags", [])[:5])
        desc_preview = (r.get("description") or "")[:100]
        lines.append(f'- "{title}"')
        if tags_preview:
            lines.append(f'  Tags: {tags_preview}')
        if desc_preview:
            lines.append(f'  Desc start: {desc_preview}')

    return "\n".join(lines)


# ── Platform guidance ─────────────────────────────────────────────────────────

def _get_platform_guidance(niche_description: str) -> str:
    """Call Perplexity/sonar for current YouTube metadata best practices."""
    query = (
        f"What are the current best practices for YouTube metadata optimisation "
        f"(titles, descriptions, tags) for {niche_description} channels in 2025? "
        f"Focus on what drives search discovery and click-through rate. Be specific and practical."
    )
    try:
        return chat_text(query, model="perplexity/sonar")
    except Exception as e:
        log.warning("platform_guidance: Perplexity call failed: %s", e)
        return "(platform guidance unavailable)"


# ── Reflection LLM call ───────────────────────────────────────────────────────

def _fmt_delta(a: dict) -> str:
    """CTR delta for one audit, or its verdict when the delta is undefined."""
    d = a.get("ctr_delta_pct")
    return f"{round(d, 1)}%" if d is not None else f"{a.get('measurement_status')} (no delta)"


def _format_perf_report(report: dict) -> str:
    median = report.get("median_ctr_delta_pct")
    dist = report.get("distribution") or {}
    lines = [
        f"CHANNEL PERFORMANCE REPORT (measured click-through rate, "
        f"pre vs post change over matched windows):",
        f"- Audits with a measured CTR verdict: {report['count']}",
        # Spell out the split, not just the rate. The rate counts neutral in its
        # denominator, so a healthy neutral-dominant channel reads as ~12% and a
        # model shown only that number concludes catastrophe. The counts, plus
        # the note below, are what stop it inventing one.
        f"- Verdict split: {dist.get(MeasurementStatus.WIN, 0)} win / "
        f"{dist.get(MeasurementStatus.NEUTRAL, 0)} neutral / "
        f"{dist.get(MeasurementStatus.REGRESSION, 0)} regression",
        f"- Win rate (wins as a share of ALL measured verdicts, neutral "
        f"included in the denominator): {report['win_rate']}%",
        f"- Regression count (last 14 days): {report['regression_count']}",
        f"- Median CTR change: {median if median is not None else 'n/a'}%",
        f"- Lever performance (mean CTR change where the field was rewritten):",
        f"    title: {report['levers'].get('title')}%",
        f"    description: {report['levers'].get('description')}%",
        f"    tags: {report['levers'].get('tags')}%",
    ]
    if report.get("worst_audits"):
        lines.append("\nSAMPLE REGRESSED AUDITS:")
        for a in report["worst_audits"]:
            lines.append(f'  Before: "{a.get("title_before", "")}"')
            lines.append(f'  After:  "{a.get("title_after", "")}"')
            lines.append(f'  CTR change: {_fmt_delta(a)}')
            if a.get("ai_reasoning"):
                lines.append(f'  LLM reasoning: {(a["ai_reasoning"] or "")[:200]}')
    if report.get("best_audits"):
        lines.append("\nSAMPLE HIGH-PERFORMING AUDITS:")
        for a in report["best_audits"]:
            lines.append(f'  Before: "{a.get("title_before", "")}"')
            lines.append(f'  After:  "{a.get("title_after", "")}"')
            lines.append(f'  CTR change: {_fmt_delta(a)}')
    lines.append(
        "\nHOW TO READ THIS: neutral is the ordinary result of a metadata "
        "rewrite — most title and description edits do not move CTR "
        "measurably, and a high neutral share is NOT evidence that the prompt "
        "is failing. Judge the prompt on whether it does harm (regressions "
        "outnumbering wins, a negative median, a consistently negative lever), "
        "not on how many verdicts came back flat."
    )
    return "\n".join(lines)


def _promote_version(channel_id: str, version_id: int, prompt_text: str) -> None:
    """Make `version_id` the channel's live prompt.

    Three writes that must always move together: retire whatever is currently
    live, mark this version live, and put its text where audit_video() reads it
    (`audit_configs.generated_prompt`). Splitting them desynchronises prompt
    attribution — autopilot stamps `audits.prompt_version_id` from the row
    marked live (autopilot.py:548), so a promoted prompt whose row still says
    `shadow` gets every one of its audits credited to the *previous* version,
    and _check_auto_revert (which reads status='live') never sees it.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    supabase().table("prompt_versions").update(
        {"status": PromptVersionStatus.RETIRED, "retired_at": now_iso}
    ).eq("channel_id", channel_id).eq("status", PromptVersionStatus.LIVE).execute()

    supabase().table("prompt_versions").update(
        {"status": PromptVersionStatus.LIVE, "promoted_at": now_iso}
    ).eq("id", version_id).execute()

    supabase().table("audit_configs").update(
        {"generated_prompt": prompt_text}
    ).eq("channel_id", channel_id).execute()


def _run_reflection(
    channel_id: str,
    perf_report: dict,
    competitive_ctx: str,
    platform_guidance: str,
) -> tuple[int | None, str]:
    """Call Sonnet with full context. Returns (version_id, reason).

    `version_id` is None when nothing was stored, and `reason` says which of the
    two very different causes applied: `no_change_warranted` (the model read the
    evidence and judged the current prompt fine — a legitimate verdict, now that
    the prompt no longer presupposes underperformance) or `llm_failed` /
    `empty_insert` (the call or the write broke). Collapsing both into a bare
    None is what let three months of no-op cycles log as a failure.
    """
    cfg_rows = (
        supabase().table("audit_configs")
        .select("generated_prompt,reflection_mode")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    cfg = cfg_rows[0] if cfg_rows else {}
    current_prompt = cfg.get("generated_prompt") or ""
    reflection_mode = cfg.get("reflection_mode") or ReflectionMode.SHADOW

    system = (
        "You are a YouTube content optimisation expert improving an AI audit system "
        "for a nursery-rhyme / kids 3D-rhyme channel. "
        "Analyse the performance data and competitive signals, then write an improved audit prompt. "
        "You may tune wording, emphasis, keyword strategy, and priorities, but you MUST preserve "
        "the fixed house metadata format below verbatim — never weaken, reorder, or drop any of it."
    )
    # Hard invariant: the candidate prompt must keep producing this exact house
    # format (title template, ordered description skeleton, ≤15 hashtags, ~500-char
    # tags) and the nested `comparisons` JSON shape audit_video() parses. Reflection
    # optimises within these rails, it does not get to redesign the output.
    house_format = (
        "NON-NEGOTIABLE HOUSE FORMAT (the improved prompt MUST keep all of this):\n"
        "TITLE: [Regional rhyme name] | [English rhyme name] | [theme] Nursery 3D Rhymes "
        "(under 100 chars; regional name in the channel's script, English name in English).\n"
        "DESCRIPTION (this exact order): (1) exactly 3 hashtags on the first line; "
        "(2) English keyword-rich description; (3) regional-language keyword-rich description; "
        "(4) a Keywords line of comma-separated search phrases (English + regional); "
        "(5) exactly 12 hashtags on the final line(s). TOTAL hashtags must be EXACTLY 15 — "
        "YouTube ignores all hashtags above 15.\n"
        "TAGS: broad + specific, English + regional, up to ~500 characters (~25-30 tags).\n"
        "OUTPUT SCHEMA: strictly a JSON object with keys comparisons "
        "(title/description/tags, each with current_problems/suggested/why_better; "
        "description.suggested holds the full multi-line description; tags.suggested is a list), "
        "issues (array of {field,severity,problem,fix}), and reasoning."
    )
    user = (
        f"{_format_perf_report(perf_report)}\n\n"
        f"{competitive_ctx}\n\n"
        f"CURRENT YOUTUBE PLATFORM GUIDANCE:\n{platform_guidance}\n\n"
        f"{house_format}\n\n"
        f"CURRENT AUDIT PROMPT:\n{current_prompt}\n\n"
        # Do NOT ask it to explain underperformance. That phrasing was the
        # premise, not the question: handed a 12% win rate and told to diagnose
        # why the prompt underperforms, the model dutifully produced five
        # confident "core failure" diagnoses of a prompt that was working. Ask
        # first whether there IS a problem, and make "no" a first-class answer.
        "Based on all of the above, first judge whether the evidence actually "
        "shows a problem with the current prompt. A high neutral share is not a "
        "problem — do not invent a diagnosis to justify a rewrite.\n"
        "If the evidence does show harm or clear headroom, diagnose it and write "
        "an improved version that still enforces the HOUSE FORMAT above exactly. "
        "If it does not, say so and return an empty candidate_prompt.\n"
        "Return JSON:\n"
        '{"reflection": "2-3 sentence assessment", "changes": ["change1", "..."], '
        '"candidate_prompt": "full improved prompt text, or \\"\\" if no change is warranted"}'
    )

    try:
        result = chat_json(user, model=settings.REFLECTION_MODEL, system=system)
    except Exception as e:
        log.error("Reflection LLM call failed for %s: %s", channel_id, e)
        return None, "llm_failed"

    candidate_prompt = (result.get("candidate_prompt") or "").strip()
    if not candidate_prompt:
        # Expected outcome, not an error: the model was explicitly allowed to
        # conclude the current prompt is fine.
        log.info(
            "Reflection for %s judged no change warranted: %s",
            channel_id, (result.get("reflection") or "")[:200],
        )
        return None, "no_change_warranted"

    # Find current live version for parent linkage
    live_rows = (
        supabase().table("prompt_versions")
        .select("id")
        .eq("channel_id", channel_id)
        .eq("status", PromptVersionStatus.LIVE)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    parent_id = live_rows[0]["id"] if live_rows else None

    # Always land the candidate as `shadow`; promotion is a separate, explicit
    # step so the version row and the prompt text can never disagree.
    row = {
        "channel_id": channel_id,
        "prompt_text": candidate_prompt,
        "status": PromptVersionStatus.SHADOW,
        "reflection_reasoning": result.get("reflection", ""),
        "performance_snapshot": perf_report,
        "parent_version_id": parent_id,
    }
    inserted = supabase().table("prompt_versions").insert(row).execute()
    version_id = (inserted.data[0] if inserted.data else {}).get("id")
    log.info("Stored prompt candidate %s for %s (status=%s)", version_id, channel_id, row["status"])

    # `live` and `auto` both mean "use this prompt now" — they differ only in
    # who asked (a human toggling the mode vs the weekly cycle).
    if reflection_mode in PROMOTING_REFLECTION_MODES and version_id:
        _promote_version(channel_id, version_id, candidate_prompt)
        log.info("%s mode: promoted candidate %s to live for %s",
                 reflection_mode, version_id, channel_id)

    return version_id, ("stored" if version_id else "empty_insert")


# ── Shadow audit runner ───────────────────────────────────────────────────────

def _run_shadow_audits(channel_id: str, candidate_prompt: str, version_id: int) -> int:
    """Run candidate prompt on 10 recently applied videos. Store as shadow_pending.

    Returns count of shadow audits created.
    """
    # 10 most-recently-applied videos for this channel (join-scoped — no truncation).
    recent_applied = (
        audits_for_channel(channel_id, "video_id,applied_at")
        .eq("status", AuditStatus.APPLIED)
        .order("applied_at", desc=True)
        .limit(10)
        .execute()
    ).data or []

    if not recent_applied:
        return 0

    count = 0
    for row in recent_applied:
        vid = row["video_id"]
        try:
            audit_video(
                vid,
                prompt_override=candidate_prompt,
                status_override=AuditStatus.SHADOW_PENDING,
                prompt_version_id=version_id,  # the candidate, not the live version
            )
            count += 1
        except Exception as e:
            log.warning("Shadow audit failed for %s: %s", vid, e)

    log.info("Shadow: ran %d audits for candidate %s on channel %s", count, version_id, channel_id)
    return count


# ── Auto-revert cohort comparison ─────────────────────────────────────────────

def _cohort_median_ctr_delta(version_id: int) -> float | None:
    """Median measured CTR change (%) across audits generated by a prompt version.

    Returns None if fewer than _MIN_DATA_POINTS audits in the cohort carry a
    usable delta — auto-revert must never retire a prompt on thin evidence.

    Audits are scoped by prompt_version_id (already channel-specific), so no
    channel video-id list is needed. No video join either: the verdict lives on
    the audit row, which is the point of measuring CTR rather than views.
    """
    # Version-scoped measured audits, fully paged past the 1000-row cap.
    #
    # No `status='applied'` filter: this cohort is the evidence for or against a
    # prompt version, and a regression an operator later reverted is still a
    # regression that version produced. Filtering on applied would drop exactly
    # the outcomes an operator felt the need to undo — the worst ones — and
    # flatter the version that caused them. See verdicts.is_evidence.
    audits = fetch_all(
        supabase().table("audits")
        .select("id,measurement_status,measurement_result")
        .eq("prompt_version_id", version_id)
        .in_("measurement_status", list(MEASURED_STATUSES))
    )
    if not audits:
        return None

    usable = [v.ctr_delta for v in verdicts.evidence(audits) if v.ctr_delta is not None]
    if len(usable) < _MIN_DATA_POINTS:
        return None
    return verdicts.median_ctr_delta_pct(usable)


def _check_auto_revert(channel_id: str) -> None:
    """For channels in auto mode: compare live cohort vs parent cohort. Revert if regression."""
    live_rows = (
        supabase().table("prompt_versions")
        .select("id,parent_version_id,created_at")
        .eq("channel_id", channel_id)
        .eq("status", PromptVersionStatus.LIVE)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []

    if not live_rows:
        return
    live = live_rows[0]
    if not live.get("parent_version_id"):
        return  # no parent to compare against

    # Minimum 21 days since promotion before making a verdict
    promoted_dt = datetime.fromisoformat(live["created_at"].replace("Z", "+00:00"))
    if (datetime.now(timezone.utc) - promoted_dt) < timedelta(days=21):
        return

    new_median = _cohort_median_ctr_delta(live["id"])
    old_median = _cohort_median_ctr_delta(live["parent_version_id"])

    if new_median is None or old_median is None:
        return  # insufficient measured data in one or both cohorts

    # 10 percentage points of relative CTR change between cohorts.
    regression = (old_median - new_median) > 10.0
    if not regression:
        log.info(
            "Auto-revert check for %s: new=%.1f%% old=%.1f%% — keeping",
            channel_id, new_median, old_median,
        )
        return

    log.warning(
        "Auto-revert triggered for %s: new cohort %.1f%% vs old %.1f%% (>10pp regression)",
        channel_id, new_median, old_median,
    )

    # Fetch parent prompt text and restore
    parent_rows = (
        supabase().table("prompt_versions")
        .select("prompt_text")
        .eq("id", live["parent_version_id"])
        .execute()
    ).data or []
    if not parent_rows:
        return

    parent_prompt = parent_rows[0]["prompt_text"]
    now_iso = datetime.now(timezone.utc).isoformat()

    supabase().table("prompt_versions").update(
        {"status": PromptVersionStatus.RETIRED_REGRESSION, "retired_at": now_iso}
    ).eq("id", live["id"]).execute()

    supabase().table("prompt_versions").update(
        {"status": PromptVersionStatus.LIVE, "promoted_at": now_iso}
    ).eq("id", live["parent_version_id"]).execute()

    supabase().table("audit_configs").update(
        {"generated_prompt": parent_prompt}
    ).eq("channel_id", channel_id).execute()

    log.info("Reverted channel %s to parent prompt version %s", channel_id, live["parent_version_id"])


# ── Playlist threshold tuner ──────────────────────────────────────────────────

_THRESHOLD_JOIN_HIGH_MIN = 0.65
_THRESHOLD_JOIN_HIGH_MAX = 0.85
_THRESHOLD_NUDGE = 0.01
_FPR_HIGH = 0.20   # false positive rate above which we tighten
_FPR_LOW = 0.05    # false positive rate below which we loosen


def tune_thresholds(channel_id: str) -> dict:
    """Adjust PLAYLIST_JOIN_HIGH based on playlist assignment churn rate.

    Churn signal: embedding-adds that were later removed = false positives.
    Writes a new threshold_history row and updates settings in-process.
    Returns dict with fpr, old_join_high, new_join_high.
    """
    rows = (
        supabase().table("playlist_assignments")
        .select("action,decision_source")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []

    embedding_adds = [r for r in rows if r["action"] == "added" and r["decision_source"] == "embedding"]
    removals = [r for r in rows if r["action"] == "removed"]

    total_adds = len(embedding_adds)
    if total_adds < 5:
        log.info("tune_thresholds: insufficient assignment data for %s (%d adds)", channel_id, total_adds)
        return {"skipped": True, "reason": "insufficient_data"}

    fpr = len(removals) / total_adds
    old_high = settings.PLAYLIST_JOIN_HIGH

    if fpr > _FPR_HIGH:
        delta = _THRESHOLD_NUDGE
    elif fpr < _FPR_LOW:
        delta = -_THRESHOLD_NUDGE
    else:
        log.info("tune_thresholds: FPR %.2f in stable range for %s — no change", fpr, channel_id)
        return {"skipped": True, "reason": "stable_fpr", "fpr": round(fpr, 3)}

    new_high = round(
        max(_THRESHOLD_JOIN_HIGH_MIN, min(_THRESHOLD_JOIN_HIGH_MAX, old_high + delta)), 4
    )

    if new_high == old_high:
        return {"skipped": True, "reason": "at_boundary", "fpr": round(fpr, 3), "new_join_high": new_high}

    # Retire current active threshold row
    supabase().table("threshold_history").update(
        {"status": "retired"}
    ).eq("channel_id", channel_id).eq("status", "active").execute()

    # Insert new active threshold row
    supabase().table("threshold_history").insert({
        "channel_id": channel_id,
        "join_high": new_high,
        "join_low": settings.PLAYLIST_JOIN_LOW,
        "leave_threshold": settings.PLAYLIST_LEAVE,
        "status": "active",
        "reason": f"fpr={round(fpr, 3):.3f} ({'tightened' if delta > 0 else 'loosened'})",
    }).execute()

    # Update in-process settings so the running app uses new threshold immediately
    settings.PLAYLIST_JOIN_HIGH = new_high
    log.info(
        "tune_thresholds: %s PLAYLIST_JOIN_HIGH %.4f → %.4f (fpr=%.2f)",
        channel_id, old_high, new_high, fpr,
    )
    return {
        "fpr": round(fpr, 3),
        "old_join_high": old_high,
        "new_join_high": new_high,
        "delta": delta,
    }


# ── Main orchestrator ─────────────────────────────────────────────────────────

def reflect(channel_id: str) -> dict:
    """Full reflection cycle for one channel. Called weekly by scheduler.

    Returns dict describing what happened.
    """
    log.info("Reflection tick for channel %s", channel_id)

    should, reason = _should_reflect(channel_id)
    if not should:
        log.info("Reflection skipped for %s: %s", channel_id, reason)
        # Still run threshold tuner regardless
        tune_result = tune_thresholds(channel_id)
        return {"reflected": False, "reason": reason, "threshold_tune": tune_result}

    niche_queries = get_or_derive_niche_queries(channel_id)
    perf_report = _build_perf_report(channel_id)
    if perf_report is None:
        return {"reflected": False, "reason": "insufficient_data_at_reflect_time"}

    competitive_ctx = _sample_competitors(channel_id, niche_queries)
    niche_desc = ", ".join(niche_queries[:2]) if niche_queries else "general"
    platform_guidance = _get_platform_guidance(niche_desc)

    version_id, run_reason = _run_reflection(
        channel_id, perf_report, competitive_ctx, platform_guidance
    )
    if version_id is None:
        # `no_change_warranted` is a healthy outcome; the others are faults.
        # Surfaced verbatim so the two stop looking alike in the log.
        return {"reflected": False, "reason": run_reason}

    cfg_rows = (
        supabase().table("audit_configs")
        .select("reflection_mode")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    mode = (cfg_rows[0].get("reflection_mode") if cfg_rows else None) or ReflectionMode.SHADOW

    shadow_count = 0
    if mode == ReflectionMode.SHADOW:
        version_row = (
            supabase().table("prompt_versions")
            .select("prompt_text")
            .eq("id", version_id)
            .single()
            .execute()
        ).data
        if version_row:
            shadow_count = _run_shadow_audits(channel_id, version_row["prompt_text"], version_id)

    _check_auto_revert(channel_id)
    tune_result = tune_thresholds(channel_id)

    log.info(
        "Reflection complete for %s: version_id=%s mode=%s shadow_count=%d",
        channel_id, version_id, mode, shadow_count,
    )
    return {
        "reflected": True,
        "version_id": version_id,
        "mode": mode,
        "shadow_audits_created": shadow_count,
        "threshold_tune": tune_result,
    }


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/channels/{channel_id}/reflection/history")
def reflection_history(channel_id: str):
    """List all prompt versions for a channel, newest first."""
    rows = (
        supabase().table("prompt_versions")
        .select("id,status,created_at,promoted_at,retired_at,reflection_reasoning,performance_snapshot,parent_version_id")
        .eq("channel_id", channel_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return rows


@router.post("/channels/{channel_id}/prompt-versions/{version_id}/promote")
def promote_version(channel_id: str, version_id: int):
    """Manually promote a shadow candidate to live. Only valid for status=shadow."""
    version = (
        supabase().table("prompt_versions")
        .select("*")
        .eq("id", version_id)
        .eq("channel_id", channel_id)
        .single()
        .execute()
    ).data
    if not version:
        raise HTTPException(404, "Version not found")
    if version["status"] != PromptVersionStatus.SHADOW:
        raise HTTPException(400, f"Cannot promote version with status={version['status']}")

    _promote_version(channel_id, version_id, version["prompt_text"])

    log.info("Manually promoted prompt version %s for channel %s", version_id, channel_id)
    return {"ok": True, "promoted_version_id": version_id}


@router.post("/channels/{channel_id}/reflection/trigger")
def trigger_reflection(channel_id: str):
    """Manually trigger a reflection cycle (ignores cooldown check)."""
    result = reflect(channel_id)
    return result


@router.get("/channels/{channel_id}/reflection/shadow-comparison")
def shadow_comparison(channel_id: str):
    """Return side-by-side comparison: live vs shadow_pending audits for same videos."""
    shadow_audits = (
        supabase().table("audits")
        .select("id,video_id,suggested_title,suggested_description,suggested_tags,prompt_version_id,created_at")
        .eq("status", AuditStatus.SHADOW_PENDING)
        .execute()
    ).data or []

    if not shadow_audits:
        return []

    video_ids = list({a["video_id"] for a in shadow_audits})

    live_audits = (
        supabase().table("audits")
        .select("video_id,suggested_title,suggested_description,suggested_tags,created_at")
        .in_("video_id", video_ids)
        .eq("status", AuditStatus.APPLIED)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    live_by_vid: dict[str, dict] = {}
    for a in live_audits:
        if a["video_id"] not in live_by_vid:
            live_by_vid[a["video_id"]] = a

    result = []
    for shadow in shadow_audits:
        vid = shadow["video_id"]
        live = live_by_vid.get(vid)
        result.append({
            "video_id": vid,
            "shadow_audit_id": shadow["id"],
            "shadow_title": shadow.get("suggested_title"),
            "shadow_description": shadow.get("suggested_description"),
            "shadow_tags": shadow.get("suggested_tags"),
            "live_title": (live or {}).get("suggested_title"),
            "live_description": (live or {}).get("suggested_description"),
            "live_tags": (live or {}).get("suggested_tags"),
            "prompt_version_id": shadow.get("prompt_version_id"),
        })
    return result
