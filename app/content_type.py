"""Content-type classification for videos.

The Midas SEO flow writes nursery-rhyme write-ups only. YouTube's Data API v3
exposes no flag distinguishing a Shows "episode" from an ordinary upload (same
gap as Shorts — see ``app.sync.is_actually_short``), so, like ``is_short``, we
classify from a signal we *do* have. Here that signal is the title / tag pattern.

This module is the SINGLE definition of "is this an episode":

  * ``sync_channel`` stamps ``videos.is_episode`` from it at ingest,
  * the autopilot picker filters on that stored column (cheap, SQL-friendly),
  * ``audit_video`` calls ``is_episode`` directly as a defensive guard, so a row
    synced before the column was backfilled is still skipped.

Ships INERT: with no pattern configured below, every video classifies as a
non-episode and behaviour is unchanged. Fill in the identifier to activate.
"""
from __future__ import annotations

import re

# ─── FILL THIS IN ─────────────────────────────────────────────────────────────
# The identifier that marks a video as a Shows "episode" (excluded from the SEO
# flow) rather than nursery-rhyme content. Set ONE or BOTH; leaving both blank
# keeps classification inert — every video is treated as non-episode.
#
#   EPISODE_TITLE_PATTERN — a regex searched (case-insensitively) against the
#       video title, e.g. r"\bepisode\b" or r"^S\d+E\d+".
#   EPISODE_TAGS — tags that mark an episode; compared case-insensitively.
#
# The excluded content is the "Taarak Mehta Ka Ooltah Chashmah 3D Gujarati
# Series" show. "Taarak Mehta" is the channel's IP and appears in nearly every
# title (rhymes included), so it does NOT distinguish an episode — the word
# "episode" does. Match it case-insensitively at a word start, so "Episode 12",
# "Episodes", and "Episode-3" all count while ordinary rhyme titles do not.
EPISODE_TITLE_PATTERN: str | None = r"\bepisode"
EPISODE_TAGS: frozenset[str] = frozenset()
# ──────────────────────────────────────────────────────────────────────────────

_title_re = re.compile(EPISODE_TITLE_PATTERN, re.IGNORECASE) if EPISODE_TITLE_PATTERN else None
_episode_tags_lower = frozenset(t.lower() for t in EPISODE_TAGS)


def is_episode(title: str | None, tags: list[str] | None) -> bool:
    """Whether a video is a Shows episode, and so excluded from the SEO flow.

    Nursery-rhyme content gets audited; episodes do not. Classification is by
    title / tag pattern because the Data API exposes no episode flag. Pure and
    cheap (no I/O), so callers may recompute it inline rather than reading the
    denormalised ``videos.is_episode`` column.
    """
    if _title_re is not None and title and _title_re.search(title):
        return True
    if _episode_tags_lower and tags:
        if any((t or "").lower() in _episode_tags_lower for t in tags):
            return True
    return False
