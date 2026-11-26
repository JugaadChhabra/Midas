"""The channel page's one read: what Midas is doing to this channel's videos.

`GET /channels/{id}/seo` → which levers can run here (and why not), today's
writes against the daily cap, the latest weekly verdict per lever, and every
intervention on the channel (Midas and team), trimmed to what the page shows:
no trajectories, no candidate lists. Read-only.
"""

from fastapi import APIRouter, Depends, HTTPException

from app import agent_tick, autopilot, backlinks, titles
from app.access import require_channel
from app.config import settings
from app.db import supabase
from app.rows import all_rows, rows_for_ids

router = APIRouter()

COLUMNS = ("id,video_id,lever,origin,arm,status,payload,applied_at,detected_at,"
           "created_at,measurement_status,measurement_result")


def lever_states(channel: dict) -> dict:
    """Whether each lever can write on the channel, and if not, the first
    reason, in words. Mirrors `agent_tick.backlinks_enabled`/`titles_open`."""
    cid = channel["id"]
    agent = bool(channel.get("agent_enabled"))
    lang = channel.get("default_language")

    if not agent:
        bl = "Midas isn't switched on for this channel"
    elif not settings.BACKLINK_APPLY_ENABLED:
        bl = "switched off for every channel"
    elif lang not in backlinks.HEADINGS:
        bl = "no heading written for this channel's language"
    elif agent_tick.backlinks_stopped(cid):
        bl = "stopped: it didn't help on this channel"
    else:
        bl = None

    if not agent:
        tl = "Midas isn't switched on for this channel"
    elif not settings.TITLE_APPLY_ENABLED:
        tl = "switched off for every channel"
    elif cid not in settings.TITLE_CHANNELS:
        tl = "not switched on for this channel"
    elif titles.stopped(cid):
        tl = "stopped: it didn't help on this channel"
    else:
        tl = None

    return {"backlinks": {"on": bl is None, "reason": bl},
            "title": {"on": tl is None, "reason": tl}}


_lever_states = lever_states  # old name, kept for tests/test_channel_seo.py


def trim(row: dict) -> dict:
    """One intervention as the page reads it."""
    p = row.get("payload") or {}
    m = row.get("measurement_result") or {}
    return {
        "id": row["id"], "video_id": row["video_id"], "lever": row["lever"],
        "origin": row["origin"], "arm": row["arm"], "status": row["status"],
        "applied_at": row.get("applied_at"), "detected_at": row.get("detected_at"),
        "created_at": row.get("created_at"),
        "measurement_status": row.get("measurement_status"),
        "title": p.get("title"), "title_before": p.get("title_before"),
        "path": p.get("path"),
        "targets": [{"video_id": t.get("video_id"), "title": t.get("title")}
                    for t in (p.get("targets") or []) if isinstance(t, dict)],
        "target_video_id": p.get("target_video_id"),
        "short_id": p.get("short_id"),
        "error": (p.get("error") or {}).get("reason"),
        "reverted_at": (p.get("revert") or {}).get("reverted_at"),
        "delta": m.get("delta"), "pre": m.get("pre"), "post": m.get("post"),
    }


def _latest_verdicts(channel_id: str) -> list[dict]:
    rows = all_rows(
        supabase().table("lever_verdicts")
        .select("lever,arm_scope,week_start,n_treated,n_holdout,lift,cumulative_lift,"
                "windows_judged,verdict,stop_rule_triggered")
        .eq("channel_id", channel_id).order("week_start", desc=True)
    )
    seen, out = set(), []
    for r in rows:
        key = (r["lever"], r["arm_scope"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


@router.get("/channels/{channel_id}/seo", dependencies=[Depends(require_channel)])
def channel_seo(channel_id: str):
    ch = (supabase().table("channels")
          .select("id,agent_enabled,default_language,autopilot_daily_cap")
          .eq("id", channel_id).execute().data or [None])[0]
    if ch is None:
        raise HTTPException(404, "channel_not_found")

    rows = all_rows(supabase().table("interventions").select(COLUMNS)
                    .eq("channel_id", channel_id))
    rows.sort(key=lambda r: (r.get("created_at") or "", r["id"]), reverse=True)
    ivs = [trim(r) for r in rows]

    ids = sorted({r["video_id"] for r in ivs}
                 | {t["video_id"] for r in ivs for t in r["targets"] if t["video_id"]})
    videos = {}
    if ids:
        for v in rows_for_ids(lambda chunk: supabase().table("videos")
                              .select("id,title,thumbnail_url,is_short").in_("id", chunk), ids):
            videos[v["id"]] = v

    return {
        "agent_enabled": bool(ch.get("agent_enabled")),
        "levers": lever_states(ch),
        "today": {"written": autopilot._applies_today(channel_id),
                  "cap": ch.get("autopilot_daily_cap")},
        "verdicts": _latest_verdicts(channel_id),
        "interventions": ivs,
        "videos": videos,
    }
