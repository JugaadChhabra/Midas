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

These are pure functions: no database, no YouTube. The block holds no
model-written text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from app.audit_suggestion import DESCRIPTION_MAX
from app.config import settings

# The heading line per channel `default_language`. D3: the SEO team writes
# Marathi's (owner, 2026-10-23), added before rollout (S1.7). A language
# missing here makes `render` refuse; there is no English fallback.
HEADINGS: dict[str, str] = {}

_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
# One block line: a non-empty title, one space, a youtu.be link, nothing after.
_LINK_LINE_RE = re.compile(r"\S(?:.*\S)? https://youtu\.be/([A-Za-z0-9_-]{11})")


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
