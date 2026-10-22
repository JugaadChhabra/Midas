"""Slice 1 — the backlinks lever (spec Part 4, Part 2 §2.3, §3.4).

A backlink is a link in a video's description to another of our videos. Midas
adds them only as one code-rendered block, the canonical backlink block (S1.2,
Part 2 §3.4), so the block can be found again, replaced and measured, and a
human's own links are never touched:

    First line of the description
    <heading in the channel's language>
    <target title> https://youtu.be/<id>
    ...

    rest of the description

`render` puts the block directly after the first line (D2: above "Show more"),
replacing any block already there; `find` and `strip` locate and remove it by
its exact heading line and the `youtu.be` lines under it, nothing looser. A
blank line separates the block from the text after it, so a human's link line
that used to sit under the first line isn't read as one of the block's.

Which videos to link to is S1.1 (Part 2 §2.3, P2), and reads the database:

    siblings(channel_id)   -- our channels that already send it suggested views
    candidates(video)      -- ranked link targets, on its channel or a sibling

Similarity is on B6's vectors only (`reembed.MODEL_VERSION`), against the
source channel's calibrated `join_low`: no fallback to the production
EMBED_MODEL vectors or to title overlap, since two recipes in one comparison
is the B6 mistake again. A sibling's videos appear once it is re-embedded.

The block functions are pure: no database, no YouTube. The block holds no
model-written text. `find` can't tell a human's line in the block's shape added
directly under the block from one of its own; a caller that knows the targets
it rendered (the intervention's payload) compares them with `find`'s.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, NamedTuple

from app import reach, warm
from app.audit_suggestion import DESCRIPTION_MAX
from app.config import settings
from app.db import supabase
from app.embeddings import pooled_embeddings
from app.human_edits import video_links
from app.playlists import _cosine_sim
from app.reembed import MODEL_VERSION
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID
from app.rows import all_rows, rows_for_ids

# The heading line per channel `default_language`. D3: the SEO team writes
# Marathi's (owner, 2026-10-23), added before rollout (S1.7). A language
# missing here makes `render` refuse; there is no English fallback.
HEADINGS: dict[str, str] = {}

_VIDEO_ID = r"[A-Za-z0-9_-]{11}"
_VIDEO_ID_RE = re.compile(_VIDEO_ID)
# One block line: a non-empty title, one space, a youtu.be link, nothing after.
_LINK_LINE_RE = re.compile(rf"\S(?:.*\S)? https://youtu\.be/({_VIDEO_ID})")


class RenderRefused(ValueError):
    """`render` won't produce this block (no heading, too many targets, too long…)."""


@dataclass(frozen=True)
class Block:
    """A canonical block found in a description.

    `description[start:end]` is the heading line through the last link line,
    without the newlines around it.
    """

    language: str
    video_ids: tuple[str, ...]
    start: int
    end: int


def _lines(description: str | None) -> list[str]:
    return description.split("\n") if description else []


def _find_lines(lines: list[str]) -> tuple[int, int, str, tuple[str, ...]] | None:
    """(first, past-last, language, ids) of the first block, by line index."""
    languages = {heading: lang for lang, heading in HEADINGS.items()}
    for i, line in enumerate(lines):
        if line not in languages:
            continue
        ids = []
        j = i + 1
        while j < len(lines) and (m := _LINK_LINE_RE.fullmatch(lines[j])):
            ids.append(m.group(1))
            j += 1
        if ids:
            return i, j, languages[line], tuple(ids)
    return None


def find(description: str | None) -> Block | None:
    """The first canonical block in the description, or None.

    A heading line with no link line under it isn't a block.
    """
    lines = _lines(description)
    found = _find_lines(lines)
    if found is None:
        return None
    i, j, language, ids = found
    start = sum(len(line) + 1 for line in lines[:i])
    end = start + len("\n".join(lines[i:j]))
    return Block(language=language, video_ids=ids, start=start, end=end)


def strip(description: str | None) -> str:
    """The description with every canonical block, and the blank line after
    each, removed. `strip(render(d, …)) == d`."""
    lines = _lines(description)
    while (found := _find_lines(lines)) is not None:
        i, j, _, _ = found
        if j < len(lines) and lines[j] == "":
            j += 1
        del lines[i:j]
    return "\n".join(lines)


def _link_line(target: Mapping) -> tuple[str, str]:
    video_id = target.get("video_id")
    if not isinstance(video_id, str) or not _VIDEO_ID_RE.fullmatch(video_id):
        raise RenderRefused(f"target video_id {video_id!r} is not a YouTube video id")
    # One line, and no '#': a hashtag in a title would add one to the description.
    title = " ".join(str(target.get("title") or "").replace("#", "").split())
    if not title:
        raise RenderRefused(f"target {video_id} has no title")
    return video_id, f"{title} https://youtu.be/{video_id}"


def render(description: str | None, targets: Iterable[Mapping], language: str | None) -> str:
    """The description with a canonical block for `targets` directly after its
    first line, replacing any block it already has.

    `targets` are dicts with `video_id` and `title` (S1.1's candidate rows), in
    link order. Raises RenderRefused for a language with no heading, no targets,
    more than BACKLINK_MAX (the caller keeps the top BACKLINK_MAX; nothing is
    trimmed here), a duplicate or malformed target, or a result over
    DESCRIPTION_MAX characters. The block adds no hashtag, so a description
    `cap_description_hashtags` leaves alone it still leaves alone.
    """
    heading = HEADINGS.get(language)
    if not heading:
        raise RenderRefused(f"no backlink heading for language {language!r}")
    if "#" in heading:
        raise RenderRefused(f"the {language!r} heading has a hashtag")
    targets = list(targets)
    if not targets:
        raise RenderRefused("no targets")
    if len(targets) > settings.BACKLINK_MAX:
        raise RenderRefused(f"{len(targets)} targets, over BACKLINK_MAX = {settings.BACKLINK_MAX}")
    ids, links = zip(*(_link_line(t) for t in targets))
    if len(set(ids)) != len(ids):
        raise RenderRefused(f"duplicate target in {list(ids)}")

    lines = _lines(strip(description))
    head, rest = lines[:1], lines[1:]
    out = "\n".join(head + [heading, *links] + ([""] + rest if rest else []))
    if len(out) > DESCRIPTION_MAX:
        raise RenderRefused(f"description would be {len(out)} characters, over {DESCRIPTION_MAX}")
    return out


# ── S1.1: siblings and candidates ─────────────────────────────────────────

#: The sibling window: the channel's latest this-many ingested traffic
#: data-days (Part 2 §2.3), counted as B4 counts reach days.
SIBLING_WINDOW_DAYS = 28
_SUGGESTED = 7

#: Why `candidates` returned none before looking at targets, for the caller's log.
NO_THRESHOLDS = "no_thresholds"
THRESHOLDS_OTHER_MODEL = "thresholds_other_model_version"
SOURCE_NOT_EMBEDDED = "source_not_embedded"


class Candidates(NamedTuple):
    """`candidates`' answer.

    `rows` are `{video_id, channel_id, title, similarity, impressions}`, best
    first, at most 2 × BACKLINK_MAX. `skipped_unembedded` counts the source or
    otherwise eligible targets with no B6 vector. `reason` is set when the
    source got none without targets being considered.
    """

    rows: list[dict]
    skipped_unembedded: int = 0
    reason: str | None = None


def siblings(channel_id: str) -> list[dict]:
    """Our other channels whose videos sent this channel's videos at least
    SIBLING_MIN_VIEWS suggested views over its latest SIBLING_WINDOW_DAYS
    ingested traffic data-days, as `{channel_id, views}`, most views first.

    Read from the channel's own `video_traffic_source_daily`: a type-7 row
    keeps its detail only when the referring video is ours (traffic_poll
    `keeps_detail`). A channel counts only if it is itself in
    TRAFFIC_INGEST_CHANNELS: a link to it is measured from its own report
    (Part 4 finding 1).
    """
    covered = reach.coverage(channel_id, report_type=TRAFFIC_REPORT_TYPE_ID)
    if not covered:
        return []
    window = set(sorted(covered, reverse=True)[:SIBLING_WINDOW_DAYS])

    by_referrer: dict[str, int] = defaultdict(int)
    for r in all_rows(
        supabase().table("video_traffic_source_daily")
        .select("source_detail,date,views")
        .eq("channel_id", channel_id)
        .eq("source_type", _SUGGESTED)
        .neq("source_detail", "")
        .gte("date", min(window))
        .lte("date", max(window))
    ):
        if r["date"] in window:
            by_referrer[r["source_detail"]] += r["views"]

    channel_of = {
        v["id"]: v["channel_id"] for v in rows_for_ids(
            lambda c: supabase().table("videos").select("id,channel_id").in_("id", c),
            by_referrer,
        )
    }
    by_channel: dict[str, int] = defaultdict(int)
    for vid, views in by_referrer.items():
        ch = channel_of.get(vid)
        if ch and ch != channel_id and ch in settings.TRAFFIC_INGEST_CHANNELS:
            by_channel[ch] += views
    out = [{"channel_id": ch, "views": n} for ch, n in by_channel.items()
           if n >= settings.SIBLING_MIN_VIEWS]
    out.sort(key=lambda r: r["channel_id"])
    out.sort(key=lambda r: r["views"], reverse=True)
    return out


def _thresholds(channel_id: str) -> dict:
    rows = (
        supabase().table("channels").select("playlist_thresholds")
        .eq("id", channel_id).limit(1).execute()
    ).data or []
    return (rows[0].get("playlist_thresholds") if rows else None) or {}


def candidates(video: Mapping, *, sibling_ids: Iterable[str] | None = None) -> Candidates:
    """Link targets for the source `video` (a `videos` row with `id`,
    `channel_id`, `description`), ranked by similarity, ties by impressions.

    A target is on the source's channel or a sibling (`siblings`, unless the
    caller passes `sibling_ids`); public, not a Short, not the source, and not
    already linked from its description; warm on its own channel (B4's
    measure, `warm.warm_impressions`); and at least the source channel's
    `join_low` similar to it on B6 vectors. A NULL privacy or `is_short` is
    not yet known, and eligible (as warm_pool()).
    """
    source_id, channel_id = video["id"], video["channel_id"]
    thresholds = _thresholds(channel_id)
    if thresholds.get("join_low") is None:
        return Candidates([], reason=NO_THRESHOLDS)
    if thresholds.get("model_version") != MODEL_VERSION:
        return Candidates([], reason=THRESHOLDS_OTHER_MODEL)
    source_vector = pooled_embeddings([source_id], model_version=MODEL_VERSION).get(source_id)
    if source_vector is None:
        return Candidates([], skipped_unembedded=1, reason=SOURCE_NOT_EMBEDDED)

    if sibling_ids is None:
        sibling_ids = [s["channel_id"] for s in siblings(channel_id)]
    # Keyed by video, so only these channels' videos are looked at.
    impressions: dict[str, int] = {}
    for ch in dict.fromkeys([channel_id, *sibling_ids]):
        impressions.update(warm.warm_impressions(ch))

    linked = video_links(video.get("description"))
    eligible = [
        v for v in rows_for_ids(
            lambda c: (
                supabase().table("videos")
                .select("id,channel_id,title,privacy_status,is_short")
                .in_("id", c)
            ),
            impressions,
        )
        if v["id"] != source_id
        and v["id"] not in linked
        and v.get("privacy_status") in (None, "public")
        and v.get("is_short") is not True
    ]

    vectors = pooled_embeddings([v["id"] for v in eligible], model_version=MODEL_VERSION)
    rows, skipped = [], 0
    for v in eligible:
        vector = vectors.get(v["id"])
        if vector is None:
            skipped += 1
            continue
        # To the stored thresholds' precision (reembed.calibrate_channel).
        similarity = round(_cosine_sim(source_vector, vector), 4)
        if similarity >= thresholds["join_low"]:
            rows.append({"video_id": v["id"], "channel_id": v["channel_id"],
                         "title": v.get("title"), "similarity": similarity,
                         "impressions": impressions[v["id"]]})
    rows.sort(key=lambda r: (-r["similarity"], -r["impressions"], r["video_id"]))
    return Candidates(rows[:2 * settings.BACKLINK_MAX], skipped_unembedded=skipped)
