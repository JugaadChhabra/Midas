import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.db import supabase
from app.openrouter import chat_json
# Keyframe extraction lives in app.keyframes but is not used by audits — it is
# reserved for thumbnail generation (Block D). Do not re-import without
# revisiting CONTENT_INTELLIGENCE_ROADMAP.md.
from app.transcripts import fetch_transcript, lang_display_name
from app.youtube_client import (
    youtube_for_channel,
    yt_videos_list_stats,
    yt_videos_update,
    TokenExpiredError,
)

log = logging.getLogger("midas.audits")

router = APIRouter(tags=["audits"])


DEFAULT_PROMPT = """\
You are a YouTube SEO and content optimization expert. Audit this video's metadata.

CONTENT SOURCES
You will receive: the current title/description/tags (which may be placeholder or
inadequate), the video transcript when available (in any language — content signal
only), and the current thumbnail image. Treat the transcript as the primary source
of truth for what the video is actually about, with the thumbnail as supporting
visual context. The current metadata is a starting point, not a constraint —
rewrite freely to reflect the real content.

ANALYZE THE THUMBNAIL DIRECTLY when present: describe what you actually see
(composition, faces, on-screen text, colors, focal point). Do NOT say "no
information provided" if an image is attached.

LANGUAGE
The user message will state the channel's configured language. ALL output (title,
description, tags) must target that language and audience regardless of what
language the transcript is in. Use whatever mix of the channel language and English
performs best on YouTube — your editorial call.

Return strictly a JSON object with this exact shape:
{
  "comparisons": {
    "title":       { "current_problems": "what's weak about the current title", "suggested": "your rewrite", "why_better": "1-2 sentences" },
    "description": { "current_problems": "what the current description is missing or doing badly", "suggested": "your rewrite (full text)", "why_better": "..." },
    "tags":        { "current_problems": "gaps or noise in the current tag list", "suggested": ["tag1","tag2",...], "why_better": "..." },
    "thumbnail":   { "current_problems": "what is weak about the actual thumbnail you see", "suggested": "describe the ideal thumbnail concretely", "why_better": "..." }
  },
  "issues":   [ { "field":"title|description|tags|thumbnail", "severity":"high|medium|low", "problem":"...", "fix":"..." } ],
  "reasoning": "short overall summary"
}

Rules:
- suggested title under 70 characters
- suggested_tags: 12-15 tags mixing broad and specific
- Be specific and actionable, not generic
- Preserve the channel's voice
"""


class AuditConfigIn(BaseModel):
    raw_insights: str | None = None
    generated_prompt: str | None = None
    shorts_prompt: str | None = None


@router.get("/channels/{channel_id}/audit-config")
def get_config(channel_id: str):
    res = supabase().table("audit_configs").select("*").eq("channel_id", channel_id).execute()
    if res.data:
        return res.data[0]
    return {"channel_id": channel_id, "raw_insights": "", "generated_prompt": DEFAULT_PROMPT, "shorts_prompt": ""}


@router.post("/channels/{channel_id}/audit-config")
def save_config(channel_id: str, body: AuditConfigIn):
    payload = {
        "channel_id": channel_id,
        "raw_insights": body.raw_insights or "",
        "generated_prompt": body.generated_prompt or DEFAULT_PROMPT,
    }
    if body.shorts_prompt is not None:
        payload["shorts_prompt"] = body.shorts_prompt
    supabase().table("audit_configs").upsert(payload).execute()
    return {"ok": True}


@router.post("/channels/{channel_id}/audit-config/elaborate")
def elaborate(channel_id: str, body: AuditConfigIn):
    """Turn natural-language insights into a full audit prompt via LLM."""
    insights = (body.raw_insights or "").strip()
    if not insights:
        raise HTTPException(400, "raw_insights is required")

    elaboration_prompt = f"""\
You are helping a YouTube creator codify their audit criteria into a structured prompt
that will be used to evaluate every video on their channel.

The creator's notes (in their own words):
\"\"\"{insights}\"\"\"

Produce a single JSON object with one key: "generated_prompt".
Its value must be a complete, well-organized audit prompt suitable for an LLM that will:
- Evaluate the video's title, description, tags, and (when available) thumbnail.
- Return strictly a JSON object with keys:
  issues (array of {{field,severity,problem,fix}}),
  suggested_title (string, <70 chars),
  suggested_description (string),
  suggested_tags (array of 12-15 strings),
  thumbnail_feedback (string),
  reasoning (string).

Embed the creator's preferences and priorities directly into the prompt so the auditor
knows what they care about. Be specific. Do not lose the creator's voice.
"""
    result = chat_json(elaboration_prompt, model=settings.PROMPT_GEN_MODEL)
    generated = result.get("generated_prompt", "").strip()
    if not generated:
        raise HTTPException(500, "Elaboration returned no prompt")

    supabase().table("audit_configs").upsert({
        "channel_id": channel_id,
        "raw_insights": insights,
        "generated_prompt": generated,
    }).execute()
    return {"generated_prompt": generated}


def _build_user_block(
    video: dict,
    transcript: str | None,
    transcript_lang: str | None,
    channel_language: str,
    thumb_attached: bool,
) -> str:
    """Audit user message: language rule first, then metadata, transcript, thumbnail note."""
    channel_lang_name = lang_display_name(channel_language)
    transcript_lang_name = lang_display_name(transcript_lang)

    lines = [
        "LANGUAGE RULE (non-negotiable):",
        f"  Channel configured language: {channel_language} ({channel_lang_name}).",
        "  The transcript is a CONTENT SIGNAL ONLY — use it to understand what the",
        "  video is about. Do NOT use its language for output.",
        f"  ALL output (title, description, tags) must target a {channel_lang_name}-speaking",
        f"  audience. Use whatever mix of {channel_lang_name} and English performs best on",
        "  YouTube for this content type and audience — your editorial call.",
        "  NEVER let the transcript language override the channel's configured language.",
        "",
        "VIDEO METADATA (CURRENT — may be placeholder or inadequate):",
        f"Title: {video.get('title') or ''}",
        f"Description: {(video.get('description') or '')[:1500]}",
        f"Tags: {', '.join(video.get('tags') or [])}",
        f"Views: {video.get('view_count', 0)}",
        f"Likes: {video.get('like_count', 0)}",
        f"Published: {video.get('published_at') or ''}",
    ]

    if transcript:
        lines += [
            "",
            f"VIDEO TRANSCRIPT (detected language: {transcript_lang_name} — content signal only):",
            transcript,
        ]
    else:
        lines += [
            "",
            "VIDEO TRANSCRIPT: not available — base content judgment on metadata + thumbnail only.",
        ]

    lines += [
        "",
        f"THUMBNAIL: {'attached as image — analyze it directly' if thumb_attached else 'not available'}.",
        "",
        "The current title and description may be placeholder or poorly written.",
        "Use the transcript as the primary signal for what the video is about, with the",
        "thumbnail as supporting visual context. Generate metadata that reflects the actual",
        "content — do not just polish what's already there.",
        "",
        "Run the audit now and return only the JSON object.",
    ]
    return "\n".join(lines)


def _is_image_fetch_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "fetching image" in msg or ("image" in msg and "url" in msg)


def audit_video(video_id: str) -> dict:
    """Run a content-aware audit and insert a pending audit row.

    Pulls the transcript alongside the existing thumbnail input, applies the
    channel's language rule, and persists the transcript-signal columns.
    Keyframe extraction is deliberately not used here — those are reserved for
    thumbnail generation (see CONTENT_INTELLIGENCE_ROADMAP.md, Block D).
    """
    v = supabase().table("videos").select("*").eq("id", video_id).single().execute().data
    if not v:
        raise HTTPException(404, "Video not found")
    if (v.get("privacy_status") or "public") != "public":
        raise HTTPException(
            400,
            f"Skipping audit: video is {v.get('privacy_status')} (only public videos are audited)",
        )

    cfg = supabase().table("audit_configs").select("*").eq("channel_id", v["channel_id"]).execute().data
    cfg_row = cfg[0] if cfg else {}
    if v.get("is_short") and cfg_row.get("shorts_prompt"):
        audit_prompt = cfg_row["shorts_prompt"]
    else:
        audit_prompt = cfg_row.get("generated_prompt") or DEFAULT_PROMPT

    channel = supabase().table("channels").select("default_language").eq(
        "id", v["channel_id"]
    ).single().execute().data or {}
    channel_language = channel.get("default_language") or "en"

    transcript, transcript_lang = fetch_transcript(video_id, channel_id=v["channel_id"])

    stable_thumb_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    def _call(thumb_attached: bool) -> dict:
        user = _build_user_block(
            video=v,
            transcript=transcript,
            transcript_lang=transcript_lang,
            channel_language=channel_language,
            thumb_attached=thumb_attached,
        )
        images = [stable_thumb_url] if thumb_attached else None
        return chat_json(user, system=audit_prompt, image_urls=images)

    try:
        result = _call(thumb_attached=True)
    except RuntimeError as e:
        if _is_image_fetch_error(e):
            log.warning("Thumbnail fetch failed for %s — text-only audit", video_id)
            result = _call(thumb_attached=False)
        else:
            raise

    if isinstance(result, list):
        # Some models occasionally return a bare JSON array (usually the issues list)
        # instead of the documented object shape. Recover gracefully.
        log.warning("Audit for %s returned a list; coercing to object shape", video_id)
        result = {"issues": result, "comparisons": {}}
    comparisons = result.get("comparisons") or {}
    if isinstance(comparisons, list):
        # Models sometimes emit comparisons as [{field, ...}, ...] instead of a keyed object.
        comparisons = {(c.get("field") or "").lower(): c for c in comparisons if isinstance(c, dict)}
    row = {
        "video_id": video_id,
        "status": "pending",
        "suggested_title": (comparisons.get("title") or {}).get("suggested"),
        "suggested_description": (comparisons.get("description") or {}).get("suggested"),
        "suggested_tags": (comparisons.get("tags") or {}).get("suggested") or [],
        "thumbnail_feedback": (comparisons.get("thumbnail") or {}).get("suggested"),
        "issues_found": {"comparisons": comparisons, "issues": result.get("issues") or []},
        "ai_reasoning": result.get("reasoning"),
        "transcript_available": transcript is not None,
        "transcript_lang": transcript_lang,
    }
    inserted = supabase().table("audits").insert(row).execute()
    return inserted.data[0] if inserted.data else row


def validate_audit(audit: dict) -> tuple[bool, str | None]:
    """Return (ok, reason). Used before autopilot apply to refuse junk output."""
    title = (audit.get("suggested_title") or "").strip()
    if not title or len(title) > 100:
        return False, "title empty or >100 chars"
    desc = audit.get("suggested_description") or ""
    if not desc or len(desc) > 5000:
        return False, "description empty or >5000 chars"
    tags = audit.get("suggested_tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return False, "tags not a list of strings"
    if len(tags) > 30:
        return False, ">30 tags"
    if sum(len(t) for t in tags) > 500:
        return False, "tags total chars >500"
    return True, None


@router.post("/videos/{video_id}/audit")
def run_audit(video_id: str):
    return audit_video(video_id)


@router.get("/videos/{video_id}/audits")
def list_audits(video_id: str):
    res = (
        supabase().table("audits")
        .select("*")
        .eq("video_id", video_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


class ApplyIn(BaseModel):
    # Optional per-field overrides — lets the user edit before pushing.
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None


def apply_audit_internal(audit_id: int, body: ApplyIn | None = None) -> dict:
    """Core apply logic, callable from HTTP handler and from autopilot."""
    audit = supabase().table("audits").select("*").eq("id", audit_id).single().execute().data
    if not audit:
        raise HTTPException(404, "Audit not found")
    if audit["status"] == "applied":
        raise HTTPException(400, "Audit already applied")

    video = supabase().table("videos").select("*").eq("id", audit["video_id"]).single().execute().data
    if not video:
        raise HTTPException(404, "Video not found")

    channel = supabase().table("channels").select("*").eq("id", video["channel_id"]).single().execute().data
    lang = (channel or {}).get("default_language") or None

    # Capture before-state from the local row before we overwrite it.
    before_patch = {
        "title_before": video.get("title"),
        "description_before": video.get("description"),
        "tags_before": video.get("tags") or [],
    }

    new_title = (body and body.title) or audit.get("suggested_title") or video.get("title")
    new_description = (body and body.description) or audit.get("suggested_description") or video.get("description")
    new_tags = (body.tags if body and body.tags is not None else audit.get("suggested_tags")) or []

    snippet: dict = {
        "title": new_title,
        "description": new_description,
        "tags": new_tags,
        "categoryId": "27",  # Education
    }
    if lang:
        snippet["defaultLanguage"] = lang
        snippet["defaultAudioLanguage"] = lang

    payload = {
        "id": video["id"],
        "snippet": snippet,
        "status": {
            "selfDeclaredMadeForKids": True,
        },
    }

    if settings.DRY_RUN:
        log.warning("[DRY_RUN] would update video %s with %s", video["id"], payload)
        # Persist before-state even on dry-run so the UI can show what would have changed.
        supabase().table("audits").update(before_patch).eq("id", audit_id).execute()
        return {"status": "dry_run", "payload": payload}

    try:
        yt = youtube_for_channel(video["channel_id"])
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")

    # Fresh stats for an accurate apply-time baseline (1 quota unit).
    baseline_patch: dict = {}
    try:
        stats_items = yt_videos_list_stats(yt, video["channel_id"], [video["id"]])
        if stats_items:
            stats = stats_items[0].get("statistics", {})
            baseline_patch = {
                "view_count_at_apply": int(stats.get("viewCount") or 0),
                "like_count_at_apply": int(stats.get("likeCount") or 0),
                "comment_count_at_apply": int(stats.get("commentCount") or 0),
            }
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")
    except Exception as e:
        log.warning("Failed to fetch baseline stats for %s: %s", video["id"], e)

    try:
        yt_videos_update(yt, video["channel_id"], payload, parts="snippet,status")
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")
    except Exception as e:
        err_str = str(e)
        if "UPDATE_TITLE_NOT_ALLOWED_DURING_TEST_AND_COMPARE" in err_str:
            supabase().table("audits").update({
                "status": "blocked_test_and_compare",
                **before_patch,
                **baseline_patch,
            }).eq("id", audit_id).execute()
            raise HTTPException(409, "blocked_test_and_compare")
        if "quotaExceeded" in err_str:
            # Leave audit as-is (pending) so it retries when quota resets.
            raise HTTPException(429, "youtube_quota_exceeded")
        supabase().table("audits").update({"status": "failed", **before_patch, **baseline_patch}).eq("id", audit_id).execute()
        raise HTTPException(500, f"YouTube update failed: {e}")

    now = datetime.now(timezone.utc).isoformat()
    supabase().table("audits").update({
        "status": "applied",
        "applied_at": now,
        **before_patch,
        **baseline_patch,
    }).eq("id", audit_id).execute()
    supabase().table("videos").update({
        "title": new_title,
        "description": new_description,
        "tags": new_tags,
        "last_fetched_at": now,
    }).eq("id", video["id"]).execute()

    return {"status": "applied", "payload": payload}


@router.post("/audits/{audit_id}/apply")
def apply_audit(audit_id: int, body: ApplyIn | None = None):
    """Push the audit's suggested metadata to YouTube. Respects DRY_RUN."""
    return apply_audit_internal(audit_id, body)


@router.post("/channels/{channel_id}/audits/apply-pending")
def apply_pending_audits(channel_id: str):
    """Bulk-apply every pending audit for this channel.

    For each video in the channel, finds the latest audit. If status='pending'
    AND validate_audit passes, applies it. Stops early if quota runs out.
    Returns per-audit outcomes for the UI.

    Each apply costs ~51 YouTube quota units (1 stats fetch + 50 update).
    DRY_RUN is honored by apply_audit_internal.
    """
    from app import quota

    APPLY_COST = 51

    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]
    if not video_ids:
        return {"applied": 0, "skipped": 0, "failed": 0, "results": []}

    # Latest audit per video — only consider 'pending' ones.
    audits = (
        supabase().table("audits")
        .select("id,video_id,status,created_at,suggested_title,suggested_description,suggested_tags")
        .in_("video_id", video_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    seen: set[str] = set()
    pending: list[dict] = []
    for a in audits:
        if a["video_id"] in seen:
            continue
        seen.add(a["video_id"])
        if a["status"] == "pending":
            pending.append(a)

    results: list[dict] = []
    applied = skipped = failed = 0

    for a in pending:
        if not quota.can_afford(APPLY_COST):
            results.append({
                "audit_id": a["id"], "video_id": a["video_id"],
                "outcome": "skipped", "reason": "quota_exhausted",
            })
            skipped += 1
            continue

        ok, reason = validate_audit(a)
        if not ok:
            supabase().table("audits").update({
                "status": "quarantined",
                "ai_reasoning": (a.get("ai_reasoning") or "") + f"\n[bulk-apply] quarantined: {reason}",
            }).eq("id", a["id"]).execute()
            results.append({
                "audit_id": a["id"], "video_id": a["video_id"],
                "outcome": "quarantined", "reason": reason,
            })
            skipped += 1
            continue

        try:
            res = apply_audit_internal(a["id"])
            results.append({
                "audit_id": a["id"], "video_id": a["video_id"],
                "outcome": res.get("status", "applied"),
            })
            applied += 1
        except HTTPException as e:
            results.append({
                "audit_id": a["id"], "video_id": a["video_id"],
                "outcome": "failed", "reason": str(e.detail),
            })
            failed += 1
        except Exception as e:
            log.exception("bulk-apply failed for audit %s", a["id"])
            results.append({
                "audit_id": a["id"], "video_id": a["video_id"],
                "outcome": "failed", "reason": str(e),
            })
            failed += 1

    return {
        "channel_id": channel_id,
        "total_pending": len(pending),
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


@router.post("/channels/{channel_id}/audits/reaudit-quarantined")
def reaudit_quarantined(channel_id: str):
    """Re-run audit on every video whose latest audit is 'quarantined'.

    Creates a fresh pending audit row for each, replacing the quarantined one
    in the UI once the new audit is processed.
    """
    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]
    if not video_ids:
        return {"reaudited": 0, "skipped": 0, "failed": 0, "results": []}

    audits = (
        supabase().table("audits")
        .select("id,video_id,status,created_at")
        .in_("video_id", video_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    # Latest audit per video
    latest: dict[str, dict] = {}
    for a in audits:
        if a["video_id"] not in latest:
            latest[a["video_id"]] = a

    quarantined_ids = [vid for vid, a in latest.items() if a["status"] == "quarantined"]

    results: list[dict] = []
    reaudited = skipped = failed = 0

    for vid in quarantined_ids:
        try:
            a = audit_video(vid)
            results.append({"video_id": vid, "outcome": "reaudited", "audit_id": a.get("id")})
            reaudited += 1
        except HTTPException as e:
            results.append({"video_id": vid, "outcome": "skipped", "reason": str(e.detail)})
            skipped += 1
        except Exception as e:
            log.exception("Reaudit-quarantined failed for %s", vid)
            results.append({"video_id": vid, "outcome": "failed", "reason": str(e)})
            failed += 1

    return {
        "channel_id": channel_id,
        "total_quarantined": len(quarantined_ids),
        "reaudited": reaudited,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


class BulkAuditIn(BaseModel):
    video_ids: list[str]


@router.post("/channels/{channel_id}/audits/run-bulk")
def run_bulk_audit(channel_id: str, body: BulkAuditIn):
    """Audit a user-selected list of videos. Each new audit is independent."""
    results: list[dict] = []
    audited = failed = 0
    # Validate the videos belong to this channel
    rows = (
        supabase().table("videos").select("id,channel_id,privacy_status")
        .in_("id", body.video_ids).execute()
    ).data or []
    by_id = {r["id"]: r for r in rows}
    for vid in body.video_ids:
        v = by_id.get(vid)
        if not v or v.get("channel_id") != channel_id:
            results.append({"video_id": vid, "outcome": "skipped", "reason": "not_in_channel"})
            continue
        if (v.get("privacy_status") or "public") != "public":
            results.append({"video_id": vid, "outcome": "skipped", "reason": "not_public"})
            continue
        try:
            a = audit_video(vid)
            results.append({"video_id": vid, "outcome": "audited", "audit_id": a.get("id")})
            audited += 1
        except HTTPException as e:
            results.append({"video_id": vid, "outcome": "failed", "reason": str(e.detail)})
            failed += 1
        except Exception as e:
            log.exception("Bulk audit failed for %s", vid)
            results.append({"video_id": vid, "outcome": "failed", "reason": str(e)})
            failed += 1
    return {"audited": audited, "failed": failed, "total": len(body.video_ids), "results": results}


@router.post("/audits/{audit_id}/revert")
def revert_audit(audit_id: int):
    """Restore a video's title/description/tags from the audit's *_before snapshot.

    Only valid for audits with status='applied' and stored before-state. Marks
    the audit as 'reverted' and pushes the prior metadata back to YouTube.
    """
    audit = supabase().table("audits").select("*").eq("id", audit_id).single().execute().data
    if not audit:
        raise HTTPException(404, "Audit not found")
    if audit.get("status") != "applied":
        raise HTTPException(400, "Only applied audits can be reverted")
    if audit.get("title_before") is None and audit.get("description_before") is None:
        raise HTTPException(400, "No before-state stored for this audit")

    video = supabase().table("videos").select("*").eq("id", audit["video_id"]).single().execute().data
    if not video:
        raise HTTPException(404, "Video not found")

    channel = supabase().table("channels").select("default_language").eq(
        "id", video["channel_id"]
    ).single().execute().data or {}
    lang = channel.get("default_language") or None

    snippet: dict = {
        "title": audit.get("title_before") or video.get("title"),
        "description": audit.get("description_before") or video.get("description"),
        "tags": audit.get("tags_before") or [],
        "categoryId": "27",
    }
    if lang:
        snippet["defaultLanguage"] = lang
        snippet["defaultAudioLanguage"] = lang
    payload = {"id": video["id"], "snippet": snippet, "status": {"selfDeclaredMadeForKids": True}}

    if settings.DRY_RUN:
        log.warning("[DRY_RUN] would revert video %s with %s", video["id"], payload)
        supabase().table("audits").update({"status": "reverted"}).eq("id", audit_id).execute()
        return {"status": "dry_run", "payload": payload}

    yt = youtube_for_channel(video["channel_id"])
    try:
        yt_videos_update(yt, video["channel_id"], payload, parts="snippet,status")
    except Exception as e:
        raise HTTPException(500, f"YouTube revert failed: {e}")

    now = datetime.now(timezone.utc).isoformat()
    supabase().table("audits").update({"status": "reverted"}).eq("id", audit_id).execute()
    supabase().table("videos").update({
        "title": snippet["title"],
        "description": snippet["description"],
        "tags": snippet["tags"],
        "last_fetched_at": now,
    }).eq("id", video["id"]).execute()
    return {"status": "reverted"}


@router.get("/quota-cost-preview")
def quota_cost_preview(action: str, n: int = 1):
    """Estimate quota cost for an upcoming bulk action. UI uses this for confirmations.

    actions:
      audit  → 0 YouTube quota (uses OpenRouter, not YouTube quota_log)
      apply  → 51 per video (1 stats + 50 update)
      sync   → 1 + 2 * ceil(n/50) (rough)
      refresh-stats → ceil(n/50)
    """
    from app import quota
    cost = 0
    if action == "audit":
        cost = 0  # transcript fetch + LLM, not YouTube quota
    elif action == "apply":
        cost = 51 * max(0, n)
    elif action == "sync":
        import math
        cost = 1 + 2 * max(1, math.ceil(max(1, n) / 50))
    elif action == "refresh-stats":
        import math
        cost = max(1, math.ceil(max(1, n) / 50))
    else:
        raise HTTPException(400, f"Unknown action: {action}")
    remaining = quota.units_remaining()
    return {
        "action": action,
        "n": n,
        "cost": cost,
        "remaining": remaining,
        "can_afford": remaining >= cost,
        "pct_of_remaining": round(100.0 * cost / remaining, 1) if remaining > 0 else None,
    }
