"""Slice 3 · S3.4 — the title agent's tools (spec Part 6 S3.4, Part 2 §3.2; #119).

Each tool reads about the run's video only (the `Subject`: the video, its
channel's `titles.ChannelContext`, and whether transcripts come from the cache
alone), is capped, returns a small dict, and never calls YouTube. The model
passes only the arguments in a tool's schema; the loop passes the subject.

    get_video                    -- title, description start, language, reach
    get_transcript               -- at most TRANSCRIPT_MAX_CHARS
    get_traffic_mix              -- views by source over 28 traffic data-days
    get_search_terms             -- the top SEARCH_TERMS search terms
    get_channel_top_performers   -- TOP_PERFORMERS best or worst warm long
                                    videos by browse + suggested views per impression
    get_title_history            -- the video's audits and title interventions
    write_candidates             -- the writer (titles.write_candidates)

`submit_title` and `decline` end the run; their schemas are here, the loop
handles them (it checks a submitted title). `call` runs a tool by name and
turns any failure into `{"error": "..."}`, so a tool never raises into the loop.
"""
from __future__ import annotations

from typing import NamedTuple

from app import agent_tick, titles
from app.config import settings
from app.db import supabase
from app.status_vocab import InterventionLever

#: Search terms and top performers a tool returns (Part 6 S3.4).
SEARCH_TERMS = 25
TOP_PERFORMERS = 10
#: Title history rows, newest first.
HISTORY = 10

SUBMIT_TITLE = "submit_title"
DECLINE = "decline"
TERMINAL = (SUBMIT_TITLE, DECLINE)


class Subject(NamedTuple):
    """The run's video (a `videos` row with `default_language` added), its
    channel's title context, and `cache_only` for transcripts."""
    video: dict
    channel: titles.ChannelContext
    cache_only: bool = False


def _schema(name: str, description: str, properties: dict | None = None,
            required: tuple[str, ...] = ()) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {},
                       "required": list(required)}}}


def _round(ctr: float | None) -> float | None:
    return None if ctr is None else round(ctr, 4)


def get_video(s: Subject) -> dict:
    video = s.video
    impressions, ctr = s.channel.reach.get(video["id"]) or agent_tick._reach(video)
    return {"video_id": video["id"], "title": video.get("title") or "",
            "description": (video.get("description") or "")[:titles.DESCRIPTION_CHARS],
            "default_language": s.channel.language,
            "impressions_28d": impressions, "ctr_28d": _round(ctr),
            "channel_median_ctr": _round(s.channel.median_ctr)}


GET_VIDEO = _schema(
    "get_video", "The video's current title, the start of its description, the channel's "
    "language, and its impressions and click-through rate over the last 28 days beside the "
    "channel's median.")


def get_transcript(s: Subject) -> dict:
    text = titles._transcript(s.video, s.cache_only)
    if not text:
        return {"available": False}
    return {"available": True, "text": text[:settings.TRANSCRIPT_MAX_CHARS]}


GET_TRANSCRIPT = _schema("get_transcript", "The video's transcript, when there is one.")


def get_traffic_mix(s: Subject) -> dict:
    return {"views_by_source_28d": agent_tick._traffic_mix(s.video)}


GET_TRAFFIC_MIX = _schema(
    "get_traffic_mix", "The video's views by traffic source over the last 28 days.")


def get_search_terms(s: Subject) -> dict:
    return {"search_terms": titles._search_terms(s.video, SEARCH_TERMS)}


GET_SEARCH_TERMS = _schema(
    "get_search_terms", f"The top {SEARCH_TERMS} YouTube search terms that brought viewers "
    "to the video over the last 28 days, with their views.")


def get_channel_top_performers(s: Subject, order: str = "best") -> dict:
    if order not in ("best", "worst"):
        return {"error": f"order must be 'best' or 'worst', not {order!r}"}
    impressions = {v: n for v, (n, _) in s.channel.reach.items() if v != s.video["id"]}
    return {"order": order, "videos": titles._top_performers(
        s.channel.channel_id, impressions, TOP_PERFORMERS, worst=order == "worst")}


GET_CHANNEL_TOP_PERFORMERS = _schema(
    "get_channel_top_performers", f"The channel's {TOP_PERFORMERS} warm long videos with the "
    "most (best) or fewest (worst) browse + suggested views per impression over the last 28 "
    "days, with their titles.",
    {"order": {"type": "string", "enum": ["best", "worst"]}})


def get_title_history(s: Subject) -> dict:
    vid = s.video["id"]
    audits = (supabase().table("audits")
              .select("created_at,title_before,suggested_title,status,measurement_status")
              .eq("video_id", vid).order("created_at", desc=True).limit(HISTORY)
              .execute()).data or []
    rows = (supabase().table("interventions")
            .select("created_at,origin,status,payload,measurement_result")
            .eq("video_id", vid).eq("lever", InterventionLever.TITLE)
            .order("created_at", desc=True).limit(HISTORY).execute()).data or []
    history = [{"kind": "audit", "created_at": a.get("created_at"),
                "title_before": a.get("title_before"), "title": a.get("suggested_title"),
                "status": a.get("status"), "measurement_status": a.get("measurement_status")}
               for a in audits]
    history += [{"kind": "title_intervention", "created_at": r.get("created_at"),
                 "origin": r.get("origin"), "status": r.get("status"),
                 "title": (r.get("payload") or {}).get("title"),
                 "delta": (r.get("measurement_result") or {}).get("delta")}
                for r in rows]
    history.sort(key=lambda h: h["created_at"] or "", reverse=True)
    return {"history": history[:HISTORY]}


GET_TITLE_HISTORY = _schema(
    "get_title_history", f"What was done to this video's title before, newest first (at most "
    f"{HISTORY}): past rewrites and their outcomes.")


def write_candidates(s: Subject) -> dict:
    ctx = titles.context(s.video, channel=s.channel, cache_only=s.cache_only)
    return {"candidates": titles.write_candidates(ctx)}


WRITE_CANDIDATES = _schema(
    "write_candidates", f"Ask a writer model for {settings.TITLE_CANDIDATES} title "
    "candidates, best first, each with a reason. They are not checked.")

SUBMIT_TITLE_SCHEMA = _schema(
    SUBMIT_TITLE, "End the run with the new title. Code checks it; a failing title gets the "
    "failure back once.",
    {"title": {"type": "string"}, "reasoning": {"type": "string"}}, ("title", "reasoning"))
DECLINE_SCHEMA = _schema(
    DECLINE, "End the run leaving the title as it is.",
    {"reason": {"type": "string"}}, ("reason",))

#: name -> function, for the non-terminal tools.
TOOLS = {
    "get_video": get_video,
    "get_transcript": get_transcript,
    "get_traffic_mix": get_traffic_mix,
    "get_search_terms": get_search_terms,
    "get_channel_top_performers": get_channel_top_performers,
    "get_title_history": get_title_history,
    "write_candidates": write_candidates,
}

#: Every tool's schema, sent on every turn.
SCHEMAS = [GET_VIDEO, GET_TRANSCRIPT, GET_TRAFFIC_MIX, GET_SEARCH_TERMS,
           GET_CHANNEL_TOP_PERFORMERS, GET_TITLE_HISTORY, WRITE_CANDIDATES,
           SUBMIT_TITLE_SCHEMA, DECLINE_SCHEMA]


def call(name: str, s: Subject, args: dict) -> dict:
    """Run the non-terminal tool `name` with the model's `args`; any failure
    (unknown tool, bad arguments, a tool that raises) comes back as
    `{"error": "..."}`."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        return fn(s, **args)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
