import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import tracing
from app.config import settings
from app.db import supabase
from app.channel_audits import audits_for_channel, fetch_all
from app.content_type import is_episode
from app.apply_outcome import ApplyError, ApplyOutcome
from app.audit_suggestion import AuditSuggestion, house_format_spec
from app.status_vocab import (
    ACTIVE_MEASUREMENT_STATUSES,
    AuditStatus,
    MeasurementStatus,
    OutcomeDecision,
)
from app.openrouter import chat_json
# Keyframe extraction lives in app.keyframes but is not used by audits — it is
# reserved for thumbnail generation (Block D). Do not re-import without
# revisiting CONTENT_INTELLIGENCE_ROADMAP.md.
from app.transcripts import fetch_transcript, lang_display_name
from app.youtube_metadata import build_update_payload, SNIPPET_STATUS_PARTS
from app.youtube_client import (
    youtube_for_channel,
    yt_videos_update,
    TokenExpiredError,
)

log = logging.getLogger("midas.audits")

router = APIRouter(tags=["audits"])


# The auditor prompt. Its house-format section (title template, description
# skeleton, tag rule, and JSON schema) is rendered from the one referent in
# audit_suggestion so the ceilings it quotes can't drift from the ones
# rejection() enforces. Everything around it — role, content sources, the
# language rule, and the two closing rules — is audit-specific framing.
DEFAULT_PROMPT = f"""\
You are a YouTube SEO expert for nursery-rhyme / kids 3D-rhyme channels.
Audit this video's metadata and rewrite it to a FIXED house format.

CONTENT SOURCES
You will receive the current title/description/tags (often placeholder or
inadequate) and the video transcript when available (in any language — content
signal only). Treat the transcript as the primary source of truth for what the
rhyme is actually about. The current metadata is a starting point, not a
constraint — rewrite freely to reflect the real content.

LANGUAGE
The user message states the channel's configured regional language. Output is
BILINGUAL: an English layer AND a regional-language layer, exactly as laid out
below. Never let the transcript's language override the channel's configured
language.

{house_format_spec()}

Rules:
- Put the fully-formatted multi-line description (all 5 blocks, real newlines) in
  comparisons.description.suggested.
- Be specific and actionable, not generic. Preserve the channel's voice.
"""


class AuditConfigIn(BaseModel):
    raw_insights: str | None = None
    generated_prompt: str | None = None
    shorts_prompt: str | None = None
    reflection_mode: str | None = None


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
    if body.reflection_mode is not None:
        payload["reflection_mode"] = body.reflection_mode
    supabase().table("audit_configs").upsert(payload).execute()
    return {"ok": True}


@router.post("/channels/{channel_id}/audit-config/elaborate")
def elaborate(channel_id: str, body: AuditConfigIn):
    """Turn natural-language insights into a full audit prompt via LLM."""
    insights = (body.raw_insights or "").strip()
    if not insights:
        raise HTTPException(400, "raw_insights is required")

    elaboration_prompt = f"""\
You are helping a YouTube creator (nursery-rhyme / kids 3D-rhyme channel) codify their
audit criteria into a structured prompt that will be used to evaluate every video on
their channel.

The creator's notes (in their own words):
\"\"\"{insights}\"\"\"

Produce a single JSON object with one key: "generated_prompt".
Its value must be a complete, well-organized audit prompt suitable for an LLM. The
generated prompt MUST preserve this fixed house format verbatim (do not weaken, reorder,
or drop any of it):

{house_format_spec()}

Embed the creator's preferences and priorities directly into the prompt so the auditor
knows what they care about, but never at the expense of the house format above. Be
specific. Do not lose the creator's voice.
"""
    # Labelled: this runs from an operator-triggered endpoint, not inside an
    # operation span, so the span name is all the context a reader gets.
    result = chat_json(elaboration_prompt, model=settings.PROMPT_GEN_MODEL,
                       label="elaborate_audit_prompt")
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
) -> str:
    """Audit user message: language rule first, then metadata, transcript."""
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
            "VIDEO TRANSCRIPT: not available — base content judgment on metadata only.",
        ]

    lines += [
        "",
        "The current title and description may be placeholder or poorly written.",
        "Use the transcript as the primary signal for what the video is about.",
        "Generate metadata that reflects the actual content — do not just polish what's already there.",
        "",
        "Run the audit now and return only the JSON object.",
    ]
    return "\n".join(lines)


# Version of the decision question set that `decide()` will ask (Phase B). It
# does not exist yet; the placeholder is hashed now so bumping it changes the
# stamp the day the question set does.
DECISION_QUESTION_SET_VERSION = "none"


def _strategy_hash(inputs: dict) -> str:
    """Short, key-order-independent hash of the strategy inputs."""
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def strategy_version(prompt_version_id: int | None = None) -> tuple[str, dict]:
    """The strategy stamp for an audit: (`<STRATEGY_LABEL>-<short hash>`, inputs).

    The hash covers what actually produced the audit: the DEFAULT_PROMPT text,
    the audit's per-channel prompt_versions id, AUDIT_MODEL, WRITER_MODEL when
    that setting exists (Phase B), and the decision question-set version. All but
    the prompt-version id are fixed for the life of the process; that one is
    known only at audit time, so the version is derived per audit rather than
    once at startup. Pure: same inputs, same version.
    """
    inputs = {
        "label": settings.STRATEGY_LABEL,
        "default_prompt_sha256": hashlib.sha256(DEFAULT_PROMPT.encode("utf-8")).hexdigest(),
        "audit_model": settings.AUDIT_MODEL,
        "decision_question_set_version": DECISION_QUESTION_SET_VERSION,
        "prompt_version_id": prompt_version_id,
    }
    writer_model = getattr(settings, "WRITER_MODEL", None)
    if writer_model:
        inputs["writer_model"] = writer_model
    return f"{settings.STRATEGY_LABEL}-{_strategy_hash(inputs)}", inputs


_strategy_rows_ensured: set[str] = set()


def _stamp_strategy(prompt_version_id: int | None) -> tuple[str, dict]:
    """Derive the audit's strategy version and guarantee its audit_strategies row.

    The audits.strategy_version FK means an unregistered version would hard-fail
    EVERY audit insert fleet-wide, so each distinct version is registered on
    first use, once per process, with the real model and the hashed inputs.
    """
    version, inputs = strategy_version(prompt_version_id)
    if version in _strategy_rows_ensured:
        return version, inputs
    try:
        supabase().table("audit_strategies").upsert(
            {
                "version": version,
                "prompt_template": "code:app/audits.py DEFAULT_PROMPT + audit_configs.generated_prompt (per-channel)",
                "model": settings.AUDIT_MODEL,
                "config": inputs,
                "status": "champion",
                "notes": "auto-registered by _stamp_strategy (derived from config)",
            },
            on_conflict="version",
            # A version is a hash of its inputs, so an existing row already holds
            # them; never overwrite a real, curated row (or the seed row).
            ignore_duplicates=True,
        ).execute()
        _strategy_rows_ensured.add(version)
    except Exception as e:
        # Table missing (migration not applied yet) — insert below will fail
        # on the column anyway; log the real cause instead of masking it.
        log.warning("could not ensure audit_strategies row %s: %s", version, e)
    return version, inputs


def _live_prompt_version_id(channel_id: str) -> int | None:
    """The prompt_versions row currently marked live for a channel, if any.

    Best-effort: prompt attribution is telemetry, so a lookup failure must not
    fail the audit itself.
    """
    try:
        rows = (
            supabase().table("prompt_versions")
            .select("id")
            .eq("channel_id", channel_id)
            .eq("status", "live")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        log.warning("Could not resolve live prompt version for %s: %s", channel_id, e)
        return None


def _record_apply_measurability(rec: tracing.Recorder, channel: dict | None) -> None:
    """Record whether this apply can ever produce evidence.

    The single most important attribute in the whole instrumentation. The apply
    path only stamps `awaiting_window` when the channel has
    `measurement_enabled`, and on 2026-08-23 the only channel with autopilot on
    was the one channel with that flag off — 57 applies in a month, every one
    landing on the `not_applicable` default with no result, nothing in the logs
    saying so. It took reading an NDJSON export to find. With this attribute it
    is a one-day question.
    """
    enabled = bool((channel or {}).get("measurement_enabled"))
    rec.set(**{
        "apply.measurement_enabled": enabled,
        "apply.will_be_measured": enabled,
    })


def audit_video(
    video_id: str,
    prompt_override: str | None = None,
    status_override: str | None = None,
    prompt_version_id: int | None = None,
) -> dict:
    """Run a content-aware audit and insert a pending audit row.

    `prompt_version_id` attributes the audit to a specific prompt_versions row —
    pass it when supplying `prompt_override` (shadow audits use the candidate's
    version). Left None with no override, the channel's live version is resolved
    here, so every caller gets attribution without stamping it themselves.
    """
    with tracing.span("audit_video", video_id=video_id) as rec:
        v = supabase().table("videos").select("*").eq("id", video_id).single().execute().data
        if not v:
            raise HTTPException(404, "Video not found")
        if (v.get("privacy_status") or "public") != "public":
            raise HTTPException(
                400,
                f"Skipping audit: video is {v.get('privacy_status')} (only public videos are audited)",
            )
        # Shows "episodes" are excluded — the SEO flow writes nursery-rhyme
        # write-ups only. Classified live from the row's title/tags (the single
        # definition in app.content_type), so this holds even for rows synced
        # before videos.is_episode was backfilled. run_bulk_audit and
        # reaudit_quarantined catch this and record it as skipped.
        if is_episode(v.get("title"), v.get("tags")):
            raise HTTPException(
                400,
                "Skipping audit: episode content (the SEO flow audits nursery-rhyme content only)",
            )

        cfg = supabase().table("audit_configs").select("*").eq("channel_id", v["channel_id"]).execute().data
        cfg_row = cfg[0] if cfg else {}
        # `used_generated` gates prompt attribution below: prompt_version_id must
        # name the prompt that ACTUALLY ran. An empty generated_prompt silently
        # falls back to DEFAULT_PROMPT, and stamping the live version there labels
        # the audit with a prompt the model never saw.
        used_generated = False
        if prompt_override:
            audit_prompt = prompt_override
        elif v.get("is_short") and cfg_row.get("shorts_prompt"):
            audit_prompt = cfg_row["shorts_prompt"]
        elif cfg_row.get("generated_prompt"):
            audit_prompt = cfg_row["generated_prompt"]
            used_generated = True
        else:
            audit_prompt = DEFAULT_PROMPT

        if prompt_version_id is None and used_generated:
            prompt_version_id = _live_prompt_version_id(v["channel_id"])

        rec.set(**{
            "channel_id": v["channel_id"],
            "audit.is_short": bool(v.get("is_short")),
            "audit.prompt_source": (
                "override" if prompt_override
                else "shorts" if (v.get("is_short") and cfg_row.get("shorts_prompt"))
                else "generated" if cfg_row.get("generated_prompt")
                else "default"
            ),
            "audit.prompt_version_id": prompt_version_id,
        })

        channel = supabase().table("channels").select("default_language").eq(
            "id", v["channel_id"]
        ).single().execute().data or {}
        # No fabricated fallback. A channel with no content language once
        # defaulted to "en" here, which shipped 57 English-only audits to a
        # Haryanvi audience. The language is a required input, not a guess:
        # refuse rather than invent one. Autopilot never reaches this — a
        # language-less channel fails eligibility.can_audit — so this guards the
        # manual paths (run_audit, run_bulk_audit).
        channel_language = channel.get("default_language")
        if not channel_language:
            raise HTTPException(
                400,
                "Skipping audit: channel has no content language set "
                "(set channels.default_language before auditing)",
            )

        transcript, transcript_lang = fetch_transcript(video_id, channel_id=v["channel_id"])
        rec.set(**{
            "audit.transcript_available": transcript is not None,
            "audit.transcript_lang": transcript_lang,
        })

        user = _build_user_block(
            video=v,
            transcript=transcript,
            transcript_lang=transcript_lang,
            channel_language=channel_language,
        )
        result = chat_json(user, system=audit_prompt)

        # Decode + normalise (incl. the hashtag cap) behind one constructor. An
        # invalid suggestion still builds and still gets persisted — the apply path
        # quarantines it, and reaudit_quarantined reprocesses it later.
        suggestion = AuditSuggestion.from_llm(result)
        rec.set(**{
            "audit.suggestion_valid": suggestion.is_valid,
            "audit.rejection": suggestion.rejection(),
        })
        if not suggestion.is_valid:
            log.warning("Audit for %s is not applicable: %s", video_id, suggestion.rejection())
        strategy, _ = _stamp_strategy(prompt_version_id)
        row = {
            "video_id": video_id,
            "status": status_override or AuditStatus.PENDING,
            **suggestion.to_audit_row(),
            "transcript_available": transcript is not None,
            "transcript_lang": transcript_lang,
            # CIL §3.1: stamp every audit with the strategy that produced it so
            # measured outcomes stay attributable when Loop 3 arrives. Same reason
            # for prompt_version_id — stamped here, at the single insert site, so no
            # caller can forget it (_cohort_median_ctr_delta silently ignores NULLs).
            "strategy_version": strategy,
            "prompt_version_id": prompt_version_id,
        }
        inserted = supabase().table("audits").insert(row).execute()
        return inserted.data[0] if inserted.data else row


def validate_audit(audit: dict) -> tuple[bool, str | None]:
    """Return (ok, reason). Used before autopilot apply to refuse junk output.

    The ceilings live on AuditSuggestion; this rebuilds one from the persisted
    row and asks it, so the check can't drift from the one applied at generate
    time.
    """
    reason = AuditSuggestion.from_audit_row(audit).rejection()
    return reason is None, reason


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
    if audit["status"] == AuditStatus.APPLIED:
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

    # Route the merged values back through AuditSuggestion so a caller-supplied
    # override is normalised exactly like a generated one. This path used to
    # bypass the hashtag cap entirely and send >15 hashtags to YouTube, which
    # then ignores all of them.
    applied = AuditSuggestion.from_fields(
        title=(body and body.title) or audit.get("suggested_title") or video.get("title"),
        description=(
            (body and body.description)
            or audit.get("suggested_description")
            or video.get("description")
        ),
        tags=(body.tags if body and body.tags is not None else audit.get("suggested_tags")) or [],
    )
    new_title, new_description, new_tags = applied.title, applied.description, applied.tags

    # The metadata YouTube accepts — category, the content language adapted to a
    # code YouTube takes, and the made-for-kids declaration — is one contract,
    # built in app.youtube_metadata so apply and revert cannot disagree.
    payload = build_update_payload(
        video["id"], title=new_title, description=new_description,
        tags=new_tags, lang=lang,
    )

    if settings.DRY_RUN:
        log.warning("[DRY_RUN] would update video %s with %s", video["id"], payload)
        # Persist before-state even on dry-run so the UI can show what would have changed.
        supabase().table("audits").update(before_patch).eq("id", audit_id).execute()
        return {"status": "dry_run", "payload": payload}

    try:
        yt = youtube_for_channel(video["channel_id"])
    except TokenExpiredError:
        raise ApplyError(ApplyOutcome.TOKEN_EXPIRED)

    # No apply-time stats baseline. This used to spend a YouTube round trip (and a
    # quota unit) capturing view/like/comment counts so the performance page could
    # report "views gained since we changed it". That baseline is no longer
    # collected, so view_count_at_apply is NULL on every audit from here on and the
    # readers report no delta rather than inventing one from zero — see
    # tests/test_unmeasured_baseline.py. Rows applied before this keep their stored
    # baselines and still show real deltas.
    #
    # Loop 1's CTR measurement is untouched: it reads Reporting-API impressions over
    # symmetric pre/post windows, not these counters, which is the whole reason it
    # replaced view-velocity in the first place.

    # Classify YouTube's failure ONCE here (the only place the raw error exists) and
    # raise a typed ApplyError; callers switch on .outcome, not on the error text.
    try:
        yt_videos_update(yt, video["channel_id"], payload, parts=SNIPPET_STATUS_PARTS)
    except TokenExpiredError:
        raise ApplyError(ApplyOutcome.TOKEN_EXPIRED)
    except Exception as e:
        err_str = str(e)
        if "UPDATE_TITLE_NOT_ALLOWED_DURING_TEST_AND_COMPARE" in err_str:
            supabase().table("audits").update({
                "status": AuditStatus.BLOCKED_TEST_AND_COMPARE,
                **before_patch,
            }).eq("id", audit_id).execute()
            raise ApplyError(ApplyOutcome.TEST_AND_COMPARE)
        if "quotaExceeded" in err_str:
            # Leave audit as-is (pending) so it retries when quota resets.
            raise ApplyError(ApplyOutcome.QUOTA_EXCEEDED)
        supabase().table("audits").update({"status": AuditStatus.FAILED, **before_patch}).eq("id", audit_id).execute()
        raise ApplyError(ApplyOutcome.FAILED, f"YouTube update failed: {e}")

    now = datetime.now(timezone.utc).isoformat()
    # CIL §1.2/§1.3 — enter the measurement pipeline on measurement-enabled
    # channels. Entry only sets the state; window math, the dormant-video
    # not_applicable rule, and the verdict all live in app/measurement.py's
    # daily eval (reach CSVs for the apply date arrive days later anyway, so
    # nothing more CAN be decided at apply time).
    with tracing.span("apply_audit", video_id=video["id"], audit_id=audit_id) as rec:
        _record_apply_measurability(rec, channel)
        measurement_patch: dict = {}
        if (channel or {}).get("measurement_enabled"):
            measurement_patch = {
                "measurement_status": MeasurementStatus.AWAITING_WINDOW,
                "measurement_started_at": now,
            }
        supabase().table("audits").update({
            "status": AuditStatus.APPLIED,
            "applied_at": now,
            **before_patch,
            **measurement_patch,
        }).eq("id", audit_id).execute()
        supabase().table("videos").update({
            "title": new_title,
            "description": new_description,
            "tags": new_tags,
            "last_fetched_at": now,
        }).eq("id", video["id"]).execute()

    return {"status": AuditStatus.APPLIED, "payload": payload}


@router.post("/audits/{audit_id}/apply")
def apply_audit(audit_id: int, body: ApplyIn | None = None):
    """Push the audit's suggested metadata to YouTube. Respects DRY_RUN."""
    return apply_audit_internal(audit_id, body)


class ApplyPendingIn(BaseModel):
    # Optional subset. When omitted, every pending audit in the channel is applied
    # (the "Apply all pending" button). When present, only these videos' pending
    # audits are applied (the "Apply selected pending" button) — still scoped to
    # this channel, so ids from other channels are ignored.
    video_ids: list[str] | None = None


@router.post("/channels/{channel_id}/audits/apply-pending")
def apply_pending_audits(channel_id: str, body: ApplyPendingIn | None = None):
    """Bulk-apply pending audits for this channel.

    For each video in the channel (optionally narrowed to body.video_ids), finds
    the latest audit. If status='pending' AND validate_audit passes, applies it.
    Stops early if quota runs out. Returns per-audit outcomes for the UI.

    Each apply costs ~51 YouTube quota units (1 stats fetch + 50 update).
    DRY_RUN is honored by apply_audit_internal.
    """
    from app import quota

    APPLY_COST = quota.cost_of(*quota.APPLY)

    # Latest audit per video for this channel (join-scoped — no 1000-row
    # truncation); only 'pending' ones are applied below.
    q = audits_for_channel(
        channel_id,
        "id,video_id,status,created_at,suggested_title,suggested_description,suggested_tags",
    )
    if body and body.video_ids:
        q = q.in_("video_id", list(body.video_ids))
    # Page past the 1000-row cap: we need EVERY audit to dedup latest-per-video.
    audits = fetch_all(q.order("created_at", desc=True))
    seen: set[str] = set()
    pending: list[dict] = []
    for a in audits:
        if a["video_id"] in seen:
            continue
        seen.add(a["video_id"])
        if a["status"] == AuditStatus.PENDING:
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
                "status": AuditStatus.QUARANTINED,
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
    # Latest audit per video for this channel (join-scoped, fully paged —
    # need every audit to find each video's latest status).
    audits = fetch_all(
        audits_for_channel(channel_id, "id,video_id,status,created_at")
        .order("created_at", desc=True)
    )

    # Latest audit per video
    latest: dict[str, dict] = {}
    for a in audits:
        if a["video_id"] not in latest:
            latest[a["video_id"]] = a

    quarantined_ids = [vid for vid, a in latest.items() if a["status"] == AuditStatus.QUARANTINED]

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
    if audit.get("status") != AuditStatus.APPLIED:
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

    # Same contract as apply, built through the one owner. A revert restates the
    # whole snippet, so a code YouTube rejects here would strand the video on the
    # new metadata — which is exactly why both paths share the adaptation.
    payload = build_update_payload(
        video["id"],
        title=audit.get("title_before") or video.get("title"),
        description=audit.get("description_before") or video.get("description"),
        tags=audit.get("tags_before") or [],
        lang=lang,
    )

    if settings.DRY_RUN:
        log.warning("[DRY_RUN] would revert video %s with %s", video["id"], payload)
        supabase().table("audits").update(
            {"status": AuditStatus.REVERTED, "outcome_decision": OutcomeDecision.REVERTED}
        ).eq("id", audit_id).execute()
        return {"status": "dry_run", "payload": payload}

    from app import quota
    revert_cost = quota.cost(quota.Op.VIDEOS_UPDATE)
    if not quota.can_afford(revert_cost):
        raise HTTPException(
            409,
            f"quota_insufficient: revert needs {revert_cost} units, "
            f"{quota.units_remaining()} remaining today",
        )

    yt = youtube_for_channel(video["channel_id"])
    try:
        yt_videos_update(yt, video["channel_id"], payload, parts=SNIPPET_STATUS_PARTS)
    except Exception as e:
        raise HTTPException(500, f"YouTube revert failed: {e}")

    now = datetime.now(timezone.utc).isoformat()
    # Loop 1: record the human decision. A regression verdict reverted by an
    # operator is the exact signal Loop 2's playbook distiller feeds on.
    revert_patch: dict = {"status": AuditStatus.REVERTED, "outcome_decision": OutcomeDecision.REVERTED}
    if audit.get("measurement_status") in ACTIVE_MEASUREMENT_STATUSES:
        # Reverted BEFORE a verdict: the post window would now measure
        # post-revert metadata, so no verdict is derivable. Park it out of
        # the eval query (which also filters status='applied' as a second
        # guard) instead of leaving it in-flight forever.
        revert_patch["measurement_status"] = MeasurementStatus.NOT_APPLICABLE
        revert_patch["measurement_result"] = {
            "rationale": "reverted by operator before the measurement window closed"
        }
    supabase().table("audits").update(revert_patch).eq("id", audit_id).execute()
    reverted = payload["snippet"]
    supabase().table("videos").update({
        "title": reverted["title"],
        "description": reverted["description"],
        "tags": reverted["tags"],
        "last_fetched_at": now,
    }).eq("id", video["id"]).execute()
    return {"status": AuditStatus.REVERTED}


@router.get("/quota-cost-preview")
def quota_cost_preview(action: str, n: int = 1):
    """Estimate quota cost for an upcoming bulk action. UI uses this for confirmations.

    Every price comes from quota.UNIT_COST, so this estimate cannot drift from
    what the apply path will actually be charged. What lives here is the SHAPE
    of each action — which operations it makes and how many times — not what
    they cost.

    actions:
      audit  → no YouTube quota (OpenRouter + transcript fetch)
      apply  → one stats refresh + one update, per video
      sync   → the channel lookup, then a page walk and a details read per batch
      refresh-stats → one batched stats read per 50 ids
    """
    from app import quota
    if action == "audit":
        cost = 0  # transcript fetch + LLM, not YouTube quota
    elif action == "apply":
        cost = quota.cost_of(*quota.APPLY) * max(0, n)
    elif action == "sync":
        batches = quota.calls_for(n)
        cost = (
            quota.cost(quota.Op.CHANNELS_LIST)
            + quota.cost(quota.Op.PLAYLIST_ITEMS_LIST, batches)
            + quota.cost(quota.Op.VIDEOS_LIST, batches)
        )
    elif action == "refresh-stats":
        cost = quota.cost(quota.Op.VIDEOS_LIST, quota.calls_for(n))
    else:
        raise HTTPException(400, f"Unknown action: {action}")
    remaining = quota.units_remaining()
    return {
        "action": action,
        "n": n,
        "cost": cost,
        "remaining": remaining,
        "can_afford": quota.can_afford(cost),
        "pct_of_remaining": round(100.0 * cost / remaining, 1) if remaining > 0 else None,
    }
