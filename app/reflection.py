import logging
import statistics
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db import supabase
from app.openrouter import chat_json, chat_text
from app.youtube_client import youtube_for_channel, yt_search_videos
from app.audits import audit_video

log = logging.getLogger("midas.reflection")

router = APIRouter(tags=["reflection"])

_WIN_RATE_THRESHOLD = 65.0
_REGRESSION_THRESHOLD = 3
_MIN_DATA_POINTS = 10
_REFLECT_COOLDOWN_DAYS = 7
_VELOCITY_WINDOW_DAYS = 7  # minimum post-apply days to count a data point


# ── Performance report ────────────────────────────────────────────────────────

def _build_perf_report(channel_id: str) -> dict | None:
    """Build structured performance report from applied audits.

    Returns None if fewer than _MIN_DATA_POINTS audits have velocity data.
    """
    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]
    if not video_ids:
        return None

    audits = (
        supabase().table("audits")
        .select("id,video_id,applied_at,suggested_title,title_before,"
                "suggested_description,description_before,"
                "suggested_tags,tags_before,"
                "view_count_at_apply,ai_reasoning")
        .in_("video_id", video_ids)
        .eq("status", "applied")
        .execute()
    ).data or []

    if not audits:
        return None

    vid_rows = (
        supabase().table("videos")
        .select("id,view_count,published_at")
        .in_("id", video_ids)
        .execute()
    ).data or []
    videos_by_id = {v["id"]: v for v in vid_rows}

    now = datetime.now(timezone.utc)
    enriched = []

    for a in audits:
        v = videos_by_id.get(a["video_id"])
        if not v:
            continue
        view_at = a.get("view_count_at_apply") or 0
        view_now = v.get("view_count") or 0
        if not a.get("applied_at") or not v.get("published_at") or view_at <= 0:
            continue
        try:
            ap = datetime.fromisoformat(a["applied_at"].replace("Z", "+00:00"))
            pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        days_since = (now - ap).total_seconds() / 86400.0
        if days_since < _VELOCITY_WINDOW_DAYS:
            continue
        age_at_apply = max(1.0, (ap - pub).total_seconds() / 86400.0)
        before_v = view_at / age_at_apply
        after_v = (view_now - view_at) / max(1.0, days_since)
        if before_v <= 0:
            continue
        velocity_lift_pct = ((after_v - before_v) / before_v) * 100.0
        enriched.append({
            "audit_id": a["id"],
            "velocity_lift_pct": velocity_lift_pct,
            "title_before": a.get("title_before"),
            "title_after": a.get("suggested_title"),
            "title_changed": (a.get("title_before") or "") != (a.get("suggested_title") or ""),
            "desc_changed": (a.get("description_before") or "") != (a.get("suggested_description") or ""),
            "tags_changed": list(a.get("tags_before") or []) != list(a.get("suggested_tags") or []),
            "ai_reasoning": a.get("ai_reasoning"),
            "is_recent": (now - ap) < timedelta(days=14),
        })

    if len(enriched) < _MIN_DATA_POINTS:
        return None

    win_rate = round(
        sum(1 for r in enriched if r["velocity_lift_pct"] > 10) / len(enriched) * 100, 1
    )
    regression_count = sum(
        1 for r in enriched if r["is_recent"] and r["velocity_lift_pct"] < -10
    )
    lifts = sorted(r["velocity_lift_pct"] for r in enriched)
    median_lift = statistics.median(lifts)

    def _lever_avg(key: str) -> float | None:
        sub = [r["velocity_lift_pct"] for r in enriched if r[key]]
        return round(sum(sub) / len(sub), 1) if sub else None

    by_lift = sorted(enriched, key=lambda r: r["velocity_lift_pct"])
    return {
        "count": len(enriched),
        "win_rate": win_rate,
        "regression_count": regression_count,
        "median_velocity_lift": round(median_lift, 1),
        "levers": {
            "title": _lever_avg("title_changed"),
            "description": _lever_avg("desc_changed"),
            "tags": _lever_avg("tags_changed"),
        },
        "worst_audits": by_lift[:2],
        "best_audits": by_lift[-2:],
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

    report = _build_perf_report(channel_id)
    if report is None:
        return False, "insufficient_data"

    if report["win_rate"] > _WIN_RATE_THRESHOLD and report["regression_count"] <= _REGRESSION_THRESHOLD - 1:
        return False, "performing_well"

    if report["win_rate"] < 50.0:
        return True, "low_win_rate"
    if report["regression_count"] > _REGRESSION_THRESHOLD:
        return True, "high_regressions"

    # Check if any single lever is consistently negative
    levers = report["levers"]
    for lever, lift in levers.items():
        if lift is not None and lift < -5.0:
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
    result = chat_json(prompt, model="anthropic/claude-haiku-4-5-20251001")
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

def _format_perf_report(report: dict) -> str:
    lines = [
        f"CHANNEL PERFORMANCE REPORT:",
        f"- Audits with velocity data: {report['count']}",
        f"- Win rate (velocity lift >10%): {report['win_rate']}%",
        f"- Regression count (last 14 days): {report['regression_count']}",
        f"- Median velocity lift: {report['median_velocity_lift']}%",
        f"- Lever performance:",
        f"    title: {report['levers'].get('title')}%",
        f"    description: {report['levers'].get('description')}%",
        f"    tags: {report['levers'].get('tags')}%",
    ]
    if report.get("worst_audits"):
        lines.append("\nSAMPLE REGRESSED AUDITS:")
        for a in report["worst_audits"]:
            lines.append(f'  Before: "{a.get("title_before", "")}"')
            lines.append(f'  After:  "{a.get("title_after", "")}"')
            lines.append(f'  Velocity lift: {round(a["velocity_lift_pct"], 1)}%')
            if a.get("ai_reasoning"):
                lines.append(f'  LLM reasoning: {(a["ai_reasoning"] or "")[:200]}')
    if report.get("best_audits"):
        lines.append("\nSAMPLE HIGH-PERFORMING AUDITS:")
        for a in report["best_audits"]:
            lines.append(f'  Before: "{a.get("title_before", "")}"')
            lines.append(f'  After:  "{a.get("title_after", "")}"')
            lines.append(f'  Velocity lift: {round(a["velocity_lift_pct"], 1)}%')
    return "\n".join(lines)


def _run_reflection(
    channel_id: str,
    perf_report: dict,
    competitive_ctx: str,
    platform_guidance: str,
) -> int | None:
    """Call Sonnet with full context. Store candidate in prompt_versions. Returns new version id."""
    cfg_rows = (
        supabase().table("audit_configs")
        .select("generated_prompt,reflection_mode")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    cfg = cfg_rows[0] if cfg_rows else {}
    current_prompt = cfg.get("generated_prompt") or ""
    reflection_mode = cfg.get("reflection_mode") or "shadow"

    system = (
        "You are a YouTube content optimisation expert improving an AI audit system. "
        "Analyse the performance data and competitive signals, then write an improved audit prompt."
    )
    user = (
        f"{_format_perf_report(perf_report)}\n\n"
        f"{competitive_ctx}\n\n"
        f"CURRENT YOUTUBE PLATFORM GUIDANCE:\n{platform_guidance}\n\n"
        f"CURRENT AUDIT PROMPT:\n{current_prompt}\n\n"
        "Based on all of the above, diagnose why the current prompt underperforms and write "
        "an improved version. Return JSON:\n"
        '{"reflection": "2-3 sentence diagnosis", "changes": ["change1", "change2"], '
        '"candidate_prompt": "full improved prompt text"}'
    )

    try:
        result = chat_json(user, model=settings.REFLECTION_MODEL, system=system)
    except Exception as e:
        log.error("Reflection LLM call failed for %s: %s", channel_id, e)
        return None

    candidate_prompt = (result.get("candidate_prompt") or "").strip()
    if not candidate_prompt:
        log.warning("Reflection returned empty candidate_prompt for %s", channel_id)
        return None

    # Find current live version for parent linkage
    live_rows = (
        supabase().table("prompt_versions")
        .select("id")
        .eq("channel_id", channel_id)
        .eq("status", "live")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    parent_id = live_rows[0]["id"] if live_rows else None

    row = {
        "channel_id": channel_id,
        "prompt_text": candidate_prompt,
        "status": reflection_mode if reflection_mode in ("shadow", "live") else "shadow",
        "reflection_reasoning": result.get("reflection", ""),
        "performance_snapshot": perf_report,
        "parent_version_id": parent_id,
    }
    inserted = supabase().table("prompt_versions").insert(row).execute()
    version_id = (inserted.data[0] if inserted.data else {}).get("id")
    log.info("Stored prompt candidate %s for %s (status=%s)", version_id, channel_id, row["status"])

    # If auto mode: go live immediately
    if reflection_mode == "auto" and version_id:
        supabase().table("audit_configs").update(
            {"generated_prompt": candidate_prompt}
        ).eq("channel_id", channel_id).execute()
        log.info("Auto mode: promoted candidate %s to live for %s", version_id, channel_id)

    return version_id


# ── Shadow audit runner ───────────────────────────────────────────────────────

def _run_shadow_audits(channel_id: str, candidate_prompt: str, version_id: int) -> int:
    """Run candidate prompt on 10 recently applied videos. Store as shadow_pending.

    Returns count of shadow audits created.
    """
    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]
    if not video_ids:
        return 0

    recent_applied = (
        supabase().table("audits")
        .select("video_id,applied_at")
        .in_("video_id", video_ids)
        .eq("status", "applied")
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
            result = audit_video(
                vid,
                prompt_override=candidate_prompt,
                status_override="shadow_pending",
            )
            # Tag shadow audit with the version that generated it
            if result and result.get("id"):
                supabase().table("audits").update(
                    {"prompt_version_id": version_id}
                ).eq("id", result["id"]).execute()
            count += 1
        except Exception as e:
            log.warning("Shadow audit failed for %s: %s", vid, e)

    log.info("Shadow: ran %d audits for candidate %s on channel %s", count, version_id, channel_id)
    return count


# ── Auto-revert cohort comparison ─────────────────────────────────────────────

def _cohort_median_lift(version_id: int, channel_video_ids: list[str]) -> float | None:
    """Compute median velocity_lift_pct for audits generated by a specific prompt version.

    Returns None if fewer than _MIN_DATA_POINTS audits have sufficient post-apply data.
    """
    audits = (
        supabase().table("audits")
        .select("video_id,applied_at,view_count_at_apply")
        .eq("prompt_version_id", version_id)
        .eq("status", "applied")
        .execute()
    ).data or []

    if not audits or not channel_video_ids:
        return None

    vid_rows = (
        supabase().table("videos")
        .select("id,view_count,published_at")
        .in_("id", [a["video_id"] for a in audits])
        .execute()
    ).data or []
    videos_by_id = {v["id"]: v for v in vid_rows}

    now = datetime.now(timezone.utc)
    lifts = []
    for a in audits:
        v = videos_by_id.get(a["video_id"])
        if not v or not a.get("applied_at") or not v.get("published_at"):
            continue
        view_at = a.get("view_count_at_apply") or 0
        if view_at <= 0:
            continue
        try:
            ap = datetime.fromisoformat(a["applied_at"].replace("Z", "+00:00"))
            pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        days_since = (now - ap).total_seconds() / 86400.0
        if days_since < _VELOCITY_WINDOW_DAYS:
            continue
        age_at_apply = max(1.0, (ap - pub).total_seconds() / 86400.0)
        before_v = view_at / age_at_apply
        after_v = (v.get("view_count", 0) - view_at) / max(1.0, days_since)
        if before_v > 0:
            lifts.append(((after_v - before_v) / before_v) * 100.0)

    if len(lifts) < _MIN_DATA_POINTS:
        return None
    return statistics.median(lifts)


def _check_auto_revert(channel_id: str) -> None:
    """For channels in auto mode: compare live cohort vs parent cohort. Revert if regression."""
    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]

    live_rows = (
        supabase().table("prompt_versions")
        .select("id,parent_version_id,created_at")
        .eq("channel_id", channel_id)
        .eq("status", "live")
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

    new_median = _cohort_median_lift(live["id"], video_ids)
    old_median = _cohort_median_lift(live["parent_version_id"], video_ids)

    if new_median is None or old_median is None:
        return  # insufficient data in one or both cohorts

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
        {"status": "retired_regression", "retired_at": now_iso}
    ).eq("id", live["id"]).execute()

    supabase().table("prompt_versions").update(
        {"status": "live", "promoted_at": now_iso}
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

    version_id = _run_reflection(channel_id, perf_report, competitive_ctx, platform_guidance)
    if version_id is None:
        return {"reflected": False, "reason": "reflection_llm_failed"}

    cfg_rows = (
        supabase().table("audit_configs")
        .select("reflection_mode")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    mode = (cfg_rows[0].get("reflection_mode") if cfg_rows else None) or "shadow"

    shadow_count = 0
    if mode == "shadow":
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
    if version["status"] != "shadow":
        raise HTTPException(400, f"Cannot promote version with status={version['status']}")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Retire any currently live version
    supabase().table("prompt_versions").update(
        {"status": "retired", "retired_at": now_iso}
    ).eq("channel_id", channel_id).eq("status", "live").execute()

    supabase().table("prompt_versions").update(
        {"status": "live", "promoted_at": now_iso}
    ).eq("id", version_id).execute()

    supabase().table("audit_configs").update(
        {"generated_prompt": version["prompt_text"]}
    ).eq("channel_id", channel_id).execute()

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
        .eq("status", "shadow_pending")
        .execute()
    ).data or []

    if not shadow_audits:
        return []

    video_ids = list({a["video_id"] for a in shadow_audits})

    live_audits = (
        supabase().table("audits")
        .select("video_id,suggested_title,suggested_description,suggested_tags,created_at")
        .in_("video_id", video_ids)
        .eq("status", "applied")
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
