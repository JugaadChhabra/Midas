import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.db import supabase
from app.openrouter import chat_json
from app.youtube_client import (
    youtube_for_channel,
    yt_videos_list_stats,
    yt_videos_update,
)

log = logging.getLogger("midas.audits")

router = APIRouter(tags=["audits"])


DEFAULT_PROMPT = """\
You are a YouTube SEO and content optimization expert. Audit this video's metadata.

The user will provide the title, description, tags, view stats, and (when available) the
actual thumbnail image attached to the message. ANALYZE THE THUMBNAIL IMAGE DIRECTLY when present:
describe what you actually see (composition, faces, text legibility, colors, focal point) — do
NOT say "no information provided" if an image is attached.

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


@router.get("/channels/{channel_id}/audit-config")
def get_config(channel_id: str):
    res = supabase().table("audit_configs").select("*").eq("channel_id", channel_id).execute()
    if res.data:
        return res.data[0]
    return {"channel_id": channel_id, "raw_insights": "", "generated_prompt": DEFAULT_PROMPT}


@router.post("/channels/{channel_id}/audit-config")
def save_config(channel_id: str, body: AuditConfigIn):
    payload = {
        "channel_id": channel_id,
        "raw_insights": body.raw_insights or "",
        "generated_prompt": body.generated_prompt or DEFAULT_PROMPT,
    }
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


def audit_video(video_id: str) -> dict:
    """Run an audit and insert a pending audit row. Used by /videos/{id}/audit and autopilot."""
    v = supabase().table("videos").select("*").eq("id", video_id).single().execute().data
    if not v:
        raise HTTPException(404, "Video not found")

    cfg = supabase().table("audit_configs").select("*").eq("channel_id", v["channel_id"]).execute().data
    audit_prompt = (cfg[0]["generated_prompt"] if cfg else None) or DEFAULT_PROMPT

    # Use stable URL pattern (no expiring sqp token) for vision input.
    stable_thumb_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    def _build_user_block(thumb_attached: bool) -> str:
        return f"""\
VIDEO METADATA:
Title: {v.get('title')}
Description: {(v.get('description') or '')[:1500]}
Tags: {', '.join(v.get('tags') or [])}
Views: {v.get('view_count')}
Likes: {v.get('like_count')}
Published: {v.get('published_at')}
Thumbnail: {'attached as image' if thumb_attached else 'not available'}

Run the audit now and return only the JSON object.
"""
    try:
        result = chat_json(
            _build_user_block(True),
            system=audit_prompt,
            image_urls=[stable_thumb_url],
        )
    except RuntimeError as e:
        msg = str(e)
        if "fetching image" in msg or "image" in msg.lower() and "url" in msg.lower():
            # Vision provider couldn't fetch the thumbnail — retry text-only.
            import logging
            logging.getLogger("midas.audits").warning(
                "Thumbnail fetch failed for %s, falling back to text-only audit", video_id
            )
            result = chat_json(_build_user_block(False), system=audit_prompt)
        else:
            raise

    comparisons = result.get("comparisons") or {}
    row = {
        "video_id": video_id,
        "status": "pending",
        "suggested_title": (comparisons.get("title") or {}).get("suggested"),
        "suggested_description": (comparisons.get("description") or {}).get("suggested"),
        "suggested_tags": (comparisons.get("tags") or {}).get("suggested") or [],
        "thumbnail_feedback": (comparisons.get("thumbnail") or {}).get("suggested"),
        "issues_found": {"comparisons": comparisons, "issues": result.get("issues") or []},
        "ai_reasoning": result.get("reasoning"),
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

    yt = youtube_for_channel(video["channel_id"])

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
    except Exception as e:
        log.warning("Failed to fetch baseline stats for %s: %s", video["id"], e)

    try:
        yt_videos_update(yt, video["channel_id"], payload, parts="snippet,status")
    except Exception as e:
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
