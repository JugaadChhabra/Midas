"""Slice 3 · S3.2 — the title lever's writer and its checks (spec Part 6 S3.2, Part 2 §2.4, §3.3, P5; #116).

    channel_context(channel_id)      -- what every video of a channel shares: its
                                        warm long videos' reach, their median CTR,
                                        the ceiling, the top performers
    context(video, *, channel=None)  -- what the writer is told about one video
    write_candidates(context)        -- one writer call: TITLE_CANDIDATES titles
    check(title, video)              -- the code checks (Part 2 §2.4); first failure
    pipeline(video)                  -- the pipeline path: the first passing
                                        candidate, one retry with the failures
    title_path(video_id)             -- pipeline or agent, by hash
    strategy_version(path)           -- the A6 stamp for a title, registered
    title_answers(channel_id, n)     -- the pool's first n videos triage would
                                        send to titles (the preview, the bake-off)
    preview(channel_id, n, path=)    -- arm, path and the pipeline's candidates
                                        for them, recording nothing

The title is aimed at browse and suggested views (P5): it is read beside a
thumbnail on the home page or next to another video, not in a search list.
Only the title changes; the write is app/titles_apply.py. Nothing here writes
to YouTube, and nothing but `strategy_version` writes to the database (its
`audit_strategies` row). With `cache_only`, the transcript comes from the cache
alone, so the preview and the bake-off (scripts/preview_titles.py,
scripts/title_bakeoff.py) write nothing and call no YouTube.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import statistics
from collections import defaultdict
from typing import NamedTuple

from app import agent_tick, decide, interventions, reach, warm
from app.audit_suggestion import TITLE_MAX
from app.audits import _strategy_hash
from app.config import settings
from app.db import supabase
from app.openrouter import chat_json
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID
from app.rows import all_rows, rows_for_ids
from app.status_vocab import InterventionArm, InterventionLever
from app.transcripts import _cache_read, fetch_transcript, lang_display_name

log = logging.getLogger("midas.titles")

#: The two paths a treated title takes (Part 6 S3.3), stored as `payload.path`.
PIPELINE = "pipeline"
AGENT = "agent"
PATHS = (PIPELINE, AGENT)

#: How much of the description the writer sees (as the audit, `_build_user_block`).
DESCRIPTION_CHARS = 1500
#: Search terms and top performers the writer sees.
SEARCH_TERMS = 10
TOP_PERFORMERS = 5
#: Browse (3) and suggested (7): the views a title is for (P5, Part 6 finding 3).
BROWSE_SUGGESTED = (3, 7)
SEARCH = 5

#: A character of the channel language's script, per language in
#: backlinks.HEADINGS other than `en` (which has no script check).
SCRIPTS: dict[str, tuple[str, str]] = {
    "mr": ("Devanagari", "\u0900-\u097F"),
    "hi": ("Devanagari", "\u0900-\u097F"),
    "bgc": ("Devanagari", "\u0900-\u097F"),
    "gu": ("Gujarati", "\u0A80-\u0AFF"),
    "pa": ("Gurmukhi", "\u0A00-\u0A7F"),
    "ta": ("Tamil", "\u0B80-\u0BFF"),
    "ml": ("Malayalam", "\u0D00-\u0D7F"),
    "kn": ("Kannada", "\u0C80-\u0CFF"),
    "te": ("Telugu", "\u0C00-\u0C7F"),
}
_URL_RE = re.compile(r"https?://|www\.|youtu\.be/|youtube\.com/", re.IGNORECASE)

#: The writer's system prompt; `{title_max}` and `{candidates}` are filled in
#: by `system_prompt()`.
TITLE_PROMPT = """\
You write the title of one YouTube video on a kids' nursery-rhyme channel.
Only the title changes: the thumbnail, description and tags stay as they are.

Where the title is read: on the YouTube home page, and in the list of videos
next to another video, beside the thumbnail. A parent scrolling past decides
in a glance whether to tap. It is not read in a list of search results, so
write for that glance, not for search keywords.

Rules:
- Keep the rhyme's name, in the channel's language and in its script.
- If the current title has a series name, keep it.
- Use plain words a parent recognises, not a list of keywords.
- Add no hashtags: no more "#" than the current title has.
- No links.
- At most {title_max} characters.
- Each candidate must differ from the current title.

You are told the current title, the start of the description, the transcript
when there is one, the channel's language, the video's click-through rate
beside the channel's median, where its views come from, the search terms that
bring viewers to it, and the channel's titles that get the most browse and
suggested views per impression.

Write {candidates} candidates, best first, each with a one-line reason.
Return only JSON: {{"candidates": [{{"title": "...", "reason": "..."}}, ...]}}"""


def system_prompt() -> str:
    return TITLE_PROMPT.format(title_max=TITLE_MAX, candidates=settings.TITLE_CANDIDATES)


class ChannelContext(NamedTuple):
    """What every title context on one channel shares.

    `reach`: {video_id: (impressions, CTR)} over the warm window for the
    channel's warm long videos (`warm.warm_impressions` minus `is_short` true);
    `median_ctr` their median CTR (None when none has one); `ceiling` the
    `ceil(0.01 × n)` most-impressed of them plus any over TITLE_MAX_IMPRESSIONS
    (F2); `top_performers` the warm long videos with the most browse +
    suggested views per impression, best first, `{video_id, title,
    views_per_impression}`.
    """
    channel_id: str
    language: str | None
    reach: dict[str, tuple[int, float | None]]
    median_ctr: float | None
    ceiling: frozenset[str]
    top_performers: list[dict]


def _warm_long(channel_id: str) -> dict[str, int]:
    impressions = warm.warm_impressions(channel_id)
    shorts = {
        v["id"] for v in rows_for_ids(
            lambda c: supabase().table("videos").select("id,is_short").in_("id", c),
            list(impressions))
        if v.get("is_short") is True
    }
    return {v: n for v, n in impressions.items() if v not in shorts}


def _window(channel_id: str, n: int, report_type: str | None = None) -> set[str]:
    covered = (reach.coverage(channel_id, report_type=report_type) if report_type
               else reach.coverage(channel_id))
    return set(sorted(covered, reverse=True)[:n])


def _ctrs(channel_id: str, ids: list[str]) -> dict[str, tuple[int, float | None]]:
    window = _window(channel_id, settings.WARM_WINDOW_DAYS)
    if not window or not ids:
        return {}
    by_video: dict[str, list[dict]] = defaultdict(list)
    for r in rows_for_ids(
        lambda c: supabase().table("video_reach_daily")
        .select("video_id,date,impressions,ctr").in_("video_id", c)
        .gte("date", min(window)).lte("date", max(window)),
        ids,
    ):
        if r["date"] in window:
            by_video[r["video_id"]].append(r)
    return {v: reach.weighted_ctr(by_video.get(v, [])) for v in ids}


def _ceiling(impressions: dict[str, int]) -> frozenset[str]:
    ranked = sorted(impressions, key=lambda v: (-impressions[v], v))
    top = ranked[:math.ceil(0.01 * len(ranked))]
    over = [v for v, n in impressions.items() if n > settings.TITLE_MAX_IMPRESSIONS]
    return frozenset(top) | frozenset(over)


def _top_performers(channel_id: str, impressions: dict[str, int], n: int) -> list[dict]:
    window = _window(channel_id, agent_tick.CONTEXT_DAYS, TRAFFIC_REPORT_TYPE_ID)
    if not window or not impressions:
        return []
    views: dict[str, int] = defaultdict(int)
    for r in rows_for_ids(
        lambda c: supabase().table("video_traffic_source_daily")
        .select("video_id,date,views").in_("video_id", c)
        .in_("source_type", list(BROWSE_SUGGESTED))
        .gte("date", min(window)).lte("date", max(window)),
        list(impressions),
    ):
        if r["date"] in window:
            views[r["video_id"]] += r["views"]
    rate = {v: views[v] / impressions[v] for v in views if impressions.get(v)}
    best = sorted(rate, key=lambda v: (-rate[v], v))[:n]
    titles = {v["id"]: v.get("title") for v in rows_for_ids(
        lambda c: supabase().table("videos").select("id,title").in_("id", c), best)}
    return [{"video_id": v, "title": titles.get(v), "views_per_impression": round(rate[v], 4)}
            for v in best if titles.get(v)]


def channel_context(channel_id: str) -> ChannelContext:
    """The channel's shared title context (ChannelContext). Reads only."""
    impressions = _warm_long(channel_id)
    ctrs = _ctrs(channel_id, list(impressions))
    rates = [ctr for _, ctr in ctrs.values() if ctr is not None]
    return ChannelContext(
        channel_id=channel_id,
        language=agent_tick._language(channel_id),
        reach=ctrs,
        median_ctr=statistics.median(rates) if rates else None,
        ceiling=_ceiling(impressions),
        # One spare, so a video's own row can be left out of its context.
        top_performers=_top_performers(channel_id, impressions, TOP_PERFORMERS + 1),
    )


def _search_terms(video: dict) -> list[dict]:
    """The video's top SEARCH_TERMS type-5 terms by views over the channel's
    latest CONTEXT_DAYS ingested traffic data-days."""
    window = _window(video["channel_id"], agent_tick.CONTEXT_DAYS, TRAFFIC_REPORT_TYPE_ID)
    if not window:
        return []
    views: dict[str, int] = defaultdict(int)
    for r in all_rows(
        supabase().table("video_traffic_source_daily")
        .select("source_detail,date,views")
        .eq("video_id", video["id"]).eq("source_type", SEARCH)
        .gte("date", min(window)).lte("date", max(window))
    ):
        if r["date"] in window and r.get("source_detail"):
            views[r["source_detail"]] += r["views"]
    best = sorted(views, key=lambda t: (-views[t], t))[:SEARCH_TERMS]
    return [{"term": t, "views": views[t]} for t in best]


def _transcript(video: dict, cache_only: bool) -> str | None:
    if not cache_only:
        return fetch_transcript(video["id"], video["channel_id"])[0]
    try:
        row = _cache_read(video["id"])
    except Exception as e:
        log.warning("titles %s: transcript cache read failed: %s", video["id"], e)
        return None
    return row.get("text") if row and row.get("available") else None


def context(video: dict, *, channel: ChannelContext | None = None,
            cache_only: bool = False) -> dict:
    """What the writer is told about `video` (a `videos` row with id,
    channel_id, title, description). `channel` is the channel's
    `channel_context`, read here when not passed. Reads only, except that a
    live transcript fetch caches its result (`fetch_transcript`); `cache_only`
    reads the cache alone."""
    channel = channel or channel_context(video["channel_id"])
    impressions, ctr = agent_tick._reach(video)
    return {
        "video_id": video["id"],
        "title": video.get("title") or "",
        "description": (video.get("description") or "")[:DESCRIPTION_CHARS],
        "transcript": _transcript(video, cache_only),
        "default_language": channel.language,
        "impressions": impressions,
        "ctr": ctr,
        "channel_median_ctr": channel.median_ctr,
        "traffic_mix_28d": agent_tick._traffic_mix(video),
        "search_terms": _search_terms(video),
        "top_performers": [t for t in channel.top_performers
                           if t["video_id"] != video["id"]][:TOP_PERFORMERS],
    }


def _pct(ctr: float | None) -> str:
    return "unknown" if ctr is None else f"{ctr * 100:.2f}%"


def _user_block(ctx: dict, failures: list[dict] | None = None) -> str:
    lines = [
        f"Channel language: {ctx['default_language']} "
        f"({lang_display_name(ctx['default_language'])})",
        f"Current title: {ctx['title']}",
        f"Description (first {DESCRIPTION_CHARS} characters): {ctx['description']}",
        f"Click-through rate, last 28 days: {_pct(ctx['ctr'])} on {ctx['impressions']} "
        f"impressions; channel median {_pct(ctx['channel_median_ctr'])}",
        "Views by source, last 28 days: "
        + (", ".join(f"{k} {v}" for k, v in ctx["traffic_mix_28d"].items()) or "none"),
        "Search terms that bring viewers (views): "
        + (", ".join(f"{t['term']} ({t['views']})" for t in ctx["search_terms"]) or "none"),
        "The channel's titles with the most browse and suggested views per impression:",
        *([f"- {t['title']} ({t['views_per_impression']})" for t in ctx["top_performers"]]
          or ["- none"]),
        "Transcript: " + (ctx["transcript"] or "not available"),
    ]
    if failures:
        lines += ["", "Your previous candidates failed these checks; write new ones that pass:",
                  *[f"- {f['title']!r}: {f['failure']}" for f in failures]]
    return "\n".join(lines)


def _candidates(reply) -> list[dict]:
    """The reply's candidates as `{title, reason}`, in its order; [] when the
    reply isn't `{"candidates": [{"title": str, ...}, ...]}`."""
    items = reply.get("candidates") if isinstance(reply, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for c in items[:settings.TITLE_CANDIDATES]:
        if isinstance(c, dict) and isinstance(c.get("title"), str):
            reason = c.get("reason")
            out.append({"title": c["title"], "reason": reason if isinstance(reason, str) else ""})
    return out


def write_candidates(ctx: dict, *, model: str | None = None,
                     failures: list[dict] | None = None) -> list[dict]:
    """One writer call: up to TITLE_CANDIDATES `{title, reason}`, best first;
    [] for a malformed reply. `failures` (`{title, failure}`) are a previous
    attempt's, for the retry (Part 2 §2.4)."""
    reply = chat_json(_user_block(ctx, failures), model=model or settings.WRITER_MODEL,
                      system=system_prompt(), label="titles.write")
    return _candidates(reply)


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


def check(title: str, video: dict) -> str | None:
    """The first code check (Part 2 §2.4) `title` fails for `video` (its
    current `title` and `default_language`), or None."""
    current = video.get("title") or ""
    if not title.strip() or len(title) > TITLE_MAX:
        return f"length: {len(title)} characters, not 1-{TITLE_MAX}"
    if _fold(title) == _fold(current):
        return "unchanged: the same as the current title"
    language = video.get("default_language")
    if language != "en":
        script = SCRIPTS.get(language)
        if script is None:
            return f"script: no script known for language {language!r}"
        if not re.search(f"[{script[1]}]", title):
            return f"script: no {script[0]} character"
    if title.count("#") > current.count("#"):
        return f"hashtags: {title.count('#')} '#', the current title has {current.count('#')}"
    if _URL_RE.search(title):
        return "url: contains a link"
    return None


class Written(NamedTuple):
    """The pipeline's result: `title` and its `reason`, or None for both with
    `failures` saying why; `candidates` every candidate asked for, with its
    `check` (None = passed) and `attempt` (1, or 2 for the retry)."""
    title: str | None
    reason: str | None
    candidates: list[dict]
    failures: list[str]


def pipeline(video: dict, *, channel: ChannelContext | None = None, model: str | None = None,
             cache_only: bool = False) -> Written:
    """The pipeline path: `write_candidates`, then the first candidate passing
    `check`; none passing → one retry told the failures; still none → no title,
    with the reasons."""
    ctx = context(video, channel=channel, cache_only=cache_only)
    subject = {**video, "default_language": ctx["default_language"]}
    asked: list[dict] = []
    failures: list[dict] | None = None
    for attempt in (1, 2):
        found = write_candidates(ctx, model=model, failures=failures)
        failures = []
        for c in found:
            failure = check(c["title"], subject)
            asked.append({**c, "check": failure, "attempt": attempt})
            if failure is None:
                return Written(c["title"], c["reason"], asked, [])
            failures.append({"title": c["title"], "failure": failure})
        if not found:
            failures.append({"title": "", "failure": "malformed reply: no candidates"})
    reasons = [f"attempt {c['attempt']}: {c['title']!r}: {c['check']}" for c in asked]
    return Written(None, None, asked, reasons or ["malformed reply: no candidates"])


def title_path(video_id: str) -> str:
    """`agent` for about TITLE_AGENT_PCT of videos, by sha256 of
    `video_id + "|title-path"`, else `pipeline` (Part 6 S3.3, F5)."""
    digest = hashlib.sha256(f"{video_id}|title-path".encode()).digest()
    return AGENT if int.from_bytes(digest[:8], "big") / 2**64 < settings.TITLE_AGENT_PCT \
        else PIPELINE


def strategy_inputs(path: str) -> tuple[str, dict]:
    """(`<STRATEGY_LABEL>-<short hash>`, inputs) for a title on `path`. Pure."""
    if path not in PATHS:
        raise ValueError(f"unknown title path {path!r}")
    inputs = {
        "lever": "title",
        "path": path,
        "prompt_sha256": hashlib.sha256(system_prompt().encode("utf-8")).hexdigest(),
        "writer_model": settings.WRITER_MODEL,
        "decision_question_set_version": decide.QUESTION_SET_VERSION,
    }
    return f"{settings.STRATEGY_LABEL}-{_strategy_hash(inputs)}", inputs


_strategy_rows_ensured: set[str] = set()


def strategy_version(path: str) -> str:
    """The A6 stamp for a title on `path`, its `audit_strategies` row
    registered once per process (as `audits._stamp_strategy`)."""
    version, inputs = strategy_inputs(path)
    if version in _strategy_rows_ensured:
        return version
    try:
        supabase().table("audit_strategies").upsert(
            {
                "version": version,
                "prompt_template": "code:app/titles.py TITLE_PROMPT",
                "model": settings.WRITER_MODEL,
                "config": inputs,
                "status": "champion",
                "notes": "auto-registered by titles.strategy_version (derived from config)",
            },
            on_conflict="version",
            ignore_duplicates=True,
        ).execute()
        _strategy_rows_ensured.add(version)
    except Exception as e:
        log.warning("could not ensure audit_strategies row %s: %s", version, e)
    return version


def would_title(video_id: str, channel: ChannelContext) -> bool:
    """Whether triage would answer `title` for the video, until S3.3's rule
    exists: a warm long video (no Short), CTR below the channel median, not
    over the ceiling."""
    impressions_ctr = channel.reach.get(video_id)
    return (impressions_ctr is not None and impressions_ctr[1] is not None
            and channel.median_ctr is not None and impressions_ctr[1] < channel.median_ctr
            and video_id not in channel.ceiling)


def title_answers(channel_id: str, n: int) -> tuple[ChannelContext, list[dict]]:
    """The channel context and the first `n` videos of the warm pool, in pick
    order (`warm.warm_pool`, with its explore share, as `agent_tick.preview`),
    that triage would send to titles. Reads only."""
    channel = channel_context(channel_id)
    out = []
    for picked in warm.warm_pool(channel_id):
        if len(out) >= n:
            break
        if not would_title(picked["id"], channel):
            continue
        video = agent_tick._video(picked["id"])
        if video is not None:
            out.append(video)
    return channel, out


def preview(channel_id: str, n: int, *, path: str = PIPELINE) -> list[dict]:
    """The pool's first `n` title answers: each with its arm and path, and for
    a treated video on `path` the pipeline's result (`written`), or
    `agent not built` for the agent until S3.4. Writes nothing, calls no
    YouTube and no decide() (no decision row), reads transcripts from the
    cache only."""
    if path not in PATHS:
        raise ValueError(f"unknown title path {path!r}")
    channel, videos = title_answers(channel_id, n)
    out = []
    for video in videos:
        impressions, ctr = channel.reach[video["id"]]
        item = {"video_id": video["id"], "title": video.get("title"), "answer": "title",
                "impressions": impressions, "ctr": ctr,
                "channel_median_ctr": channel.median_ctr,
                "arm": interventions.assign_arm(video["id"], InterventionLever.TITLE),
                "path": None, "written": None, "note": None, "error": None}
        if item["arm"] == InterventionArm.TREATED:
            item["path"] = title_path(video["id"])
            if item["path"] != path:
                item["note"] = f"on the {item['path']} path"
            elif path == AGENT:
                item["note"] = "agent not built"
            else:
                try:
                    item["written"] = pipeline(video, channel=channel, cache_only=True)
                except Exception as e:
                    item["error"] = f"{type(e).__name__}: {e}"
        out.append(item)
    return out
