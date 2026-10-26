"""Slice 2 — the playlist test (spec Part 5, Part 2 §4, P3).

Can a curated `PL…` playlist earn `playlist_starts` at all? The test splits a
channel's existing playlists into treated and holdout halves, gives each
treated playlist one dose of up to PLAYLIST_TEST_MAX_ADDS warm, similar videos
(approved once by a person), and compares the two halves' weekly starts. A
one-off experiment, not a running lever. Its unit is a playlist, so it lives in
`playlist_arms`, not `interventions` (Part 5 finding 1): no video it touches
is held out of Slice 1's warm pool.

S2.1, the draw:

    eligible(channel_id)              -- the playlists the test can use
    assign_arm(playlist_id)           -- 'treated' | 'holdout', stable
    candidates(channel_id, playlist_id) -- the videos a treated playlist would get
    draw(channel_id)                  -- once per channel: arms + pending proposals
    preview(channel_id)               -- the same, writing nothing

The dose is written as pending `add` rows in `playlist_proposals` with
`decision_source = 'experiment'` and `arm_id`, reviewed in the dashboard's
existing proposals card (E3). Nothing here reaches YouTube.

Similarity is on B6 vectors only (`reembed.MODEL_VERSION`), against the
channel's calibrated `join_high`; thresholds are never recalibrated here.
Current members are the latest `playlist_assignments` action per pair being
`added`, as `reembed.calibrate_channel` reads them.
"""
from __future__ import annotations

import hashlib
from typing import NamedTuple

from app import warm
from app.backlinks import NO_THRESHOLDS, THRESHOLDS_OTHER_MODEL, _thresholds
from app.config import settings
from app.db import supabase
from app.embeddings import pooled_embeddings
from app.playlists import _cosine_sim
from app.reembed import MODEL_VERSION, _members
from app.rows import all_rows, rows_for_ids
from app.status_vocab import PlaylistArm, PlaylistArmStatus, PlaylistProposalSource

#: A playlist needs this many current members with a B6 vector to have a
#: centroid worth scoring against (as reembed.member_similarities).
MIN_EMBEDDED_MEMBERS = 3

#: Why `survey` skipped a playlist.
SERIES = "series"
TOO_FEW_EMBEDDED_MEMBERS = "too_few_embedded_members"


class AlreadyDrawn(Exception):
    """The channel already has `playlist_arms` rows: the test is drawn once."""


class Survey(NamedTuple):
    """`survey`'s answer: `eligible` rows are `{playlist_id, title,
    eligible_members, members, vectors}` (members: every current member;
    vectors: the embedded ones'); `skipped` rows `{playlist_id, title, reason}`."""

    eligible: list[dict]
    skipped: list[dict]


class Candidates(NamedTuple):
    """`candidates`' answer. `rows` are `{video_id, title, similarity,
    impressions}`, best first, at most PLAYLIST_TEST_MAX_ADDS.
    `skipped_unembedded` counts otherwise eligible videos with no B6 vector.
    `reason` is set when the thresholds were refused."""

    rows: list[dict]
    skipped_unembedded: int = 0
    reason: str | None = None
    join_high: float | None = None


def survey(channel_id: str) -> Survey:
    """The channel's playlists, split into eligible and skipped with a reason.

    Eligible: `role` not `series` (episode order must not move) and at least
    MIN_EMBEDDED_MEMBERS current members with a MODEL_VERSION vector.
    """
    playlists = all_rows(
        supabase().table("playlists").select("id,title,role").eq("channel_id", channel_id))
    members = _members(channel_id)
    vectors = pooled_embeddings(
        sorted({v for vids in members.values() for v in vids}), model_version=MODEL_VERSION)
    eligible, skipped = [], []
    for p in sorted(playlists, key=lambda p: p["id"]):
        base = {"playlist_id": p["id"], "title": p.get("title")}
        if p.get("role") == "series":
            skipped.append({**base, "reason": SERIES})
            continue
        vids = members.get(p["id"], [])
        vecs = [vectors[v] for v in vids if v in vectors]
        if len(vecs) < MIN_EMBEDDED_MEMBERS:
            skipped.append({**base, "reason": TOO_FEW_EMBEDDED_MEMBERS})
            continue
        eligible.append({**base, "eligible_members": len(vecs), "members": set(vids),
                         "vectors": vecs})
    return Survey(eligible, skipped)


def eligible(channel_id: str) -> list[dict]:
    """The channel's playlists the test can use, as `{playlist_id, title,
    eligible_members}` (`survey`'s eligible rows, without the vectors)."""
    return [{k: p[k] for k in ("playlist_id", "title", "eligible_members")}
            for p in survey(channel_id).eligible]


def _bucket(playlist_id: str) -> float:
    """A uniform point in [0, 1) fixed by playlist_id (sha256, never hash():
    that one is salted per process)."""
    digest = hashlib.sha256(playlist_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def assign_arm(playlist_id: str) -> str:
    """'holdout' for about PLAYLIST_HOLDOUT_PCT of playlists, 'treated' for the rest."""
    if _bucket(playlist_id) < settings.PLAYLIST_HOLDOUT_PCT:
        return PlaylistArm.HOLDOUT
    return PlaylistArm.TREATED


def _pool(channel_id: str) -> tuple[dict[str, int], list[dict], dict[str, list[float]]]:
    """(impressions, videos, vectors) of the channel's warm videos that could
    join any playlist: public (or NULL), not a Short, not an episode. A NULL
    `is_short` or `is_episode` is not yet known, and eligible (as warm_pool())."""
    impressions = warm.warm_impressions(channel_id)
    videos = [
        v for v in rows_for_ids(
            lambda c: (
                supabase().table("videos")
                .select("id,channel_id,title,privacy_status,is_short,is_episode")
                .in_("id", c)
            ),
            impressions,
        )
        if v["channel_id"] == channel_id
        and v.get("privacy_status") in (None, "public")
        and v.get("is_short") is not True
        and v.get("is_episode") is not True
    ]
    vectors = pooled_embeddings([v["id"] for v in videos], model_version=MODEL_VERSION)
    return impressions, videos, vectors


def _score(playlist: dict, join_high: float, pool) -> Candidates:
    impressions, videos, vectors = pool
    # Cosine ignores scale, so the sum stands in for the members' mean.
    centroid = [sum(col) for col in zip(*playlist["vectors"])]
    rows, skipped = [], 0
    for v in videos:
        if v["id"] in playlist["members"]:
            continue
        vector = vectors.get(v["id"])
        if vector is None:
            skipped += 1
            continue
        similarity = _cosine_sim(centroid, vector)
        if similarity >= join_high:
            rows.append({"video_id": v["id"], "title": v.get("title"),
                         "similarity": similarity, "impressions": impressions[v["id"]]})
    rows.sort(key=lambda r: (-r["impressions"], -r["similarity"], r["video_id"]))
    return Candidates(rows[:settings.PLAYLIST_TEST_MAX_ADDS], skipped_unembedded=skipped,
                      join_high=join_high)


def _join_high(channel_id: str) -> tuple[float | None, str | None]:
    """(join_high, None), or (None, reason) when the thresholds are refused."""
    thresholds = _thresholds(channel_id)
    if thresholds.get("join_high") is None:
        return None, NO_THRESHOLDS
    if thresholds.get("model_version") != MODEL_VERSION:
        return None, THRESHOLDS_OTHER_MODEL
    return thresholds["join_high"], None


def candidates(channel_id: str, playlist_id: str) -> Candidates:
    """The videos a treated `playlist_id` would be proposed: on its channel,
    warm (`warm.warm_impressions`), public, not a Short, not an episode, not
    already a member, and at least the channel's `join_high` similar to the
    centroid of its members' B6 vectors. Ranked by impressions, then
    similarity, then id. A video may be a candidate for more than one playlist.

    A playlist `survey` wouldn't make eligible gets no rows.
    """
    join_high, reason = _join_high(channel_id)
    if reason:
        return Candidates([], reason=reason)
    playlist = next((p for p in survey(channel_id).eligible
                     if p["playlist_id"] == playlist_id), None)
    if playlist is None:
        return Candidates([], join_high=join_high)
    return _score(playlist, join_high, _pool(channel_id))


def _already_drawn(channel_id: str) -> bool:
    return bool((
        supabase().table("playlist_arms").select("id")
        .eq("channel_id", channel_id).limit(1).execute()
    ).data)


def _plan(channel_id: str) -> dict:
    """What `draw` would write: per eligible playlist its arm, status and
    videos (none for a holdout arm), plus the skipped playlists."""
    plan = {"channel_id": channel_id, "already_drawn": _already_drawn(channel_id),
            "refused": None, "arms": [], "skipped": []}
    join_high, reason = _join_high(channel_id)
    if reason:
        plan["refused"] = reason
        return plan
    found = survey(channel_id)
    plan["skipped"] = found.skipped
    pool = _pool(channel_id) if found.eligible else ({}, [], {})
    for p in found.eligible:
        arm = assign_arm(p["playlist_id"])
        if arm == PlaylistArm.HOLDOUT:
            videos, status = [], PlaylistArmStatus.HOLDOUT
        else:
            videos = _score(p, join_high, pool).rows
            status = PlaylistArmStatus.PLANNED if videos else PlaylistArmStatus.NO_DOSE
        plan["arms"].append({"playlist_id": p["playlist_id"], "title": p["title"],
                             "arm": arm, "status": status,
                             "eligible_members": p["eligible_members"], "videos": videos})
    return plan


def _summary(plan: dict) -> dict:
    arms = plan["arms"]
    return {
        "channel_id": plan["channel_id"],
        "refused": plan["refused"],
        "playlists": len(arms) + len(plan["skipped"]),
        "arms": {
            "treated": sum(a["arm"] == PlaylistArm.TREATED for a in arms),
            "holdout": sum(a["arm"] == PlaylistArm.HOLDOUT for a in arms),
            "no_dose": sum(a["status"] == PlaylistArmStatus.NO_DOSE for a in arms),
        },
        "proposals": sum(len(a["videos"]) for a in arms),
        "skipped": plan["skipped"],
    }


def draw(channel_id: str) -> dict:
    """Draw the channel's playlist test, once.

    Raises AlreadyDrawn if the channel has `playlist_arms` rows. Writes nothing
    when the thresholds are refused (`refused` says why). Otherwise writes one
    `playlist_arms` row per eligible playlist: a treated one `planned`, with
    its candidates as pending `experiment` `add` proposals (`no_dose` if it got
    none); a holdout one `holdout`, with none. Returns the counts and the
    skipped playlists with their reasons.
    """
    plan = _plan(channel_id)
    if plan["already_drawn"]:
        raise AlreadyDrawn(f"{channel_id} already has playlist_arms rows")
    if plan["refused"]:
        return _summary(plan)
    for a in plan["arms"]:
        [arm] = supabase().table("playlist_arms").insert({
            "channel_id": channel_id, "playlist_id": a["playlist_id"], "arm": a["arm"],
            "status": a["status"], "eligible_members": a["eligible_members"],
            "proposal_ids": [],
        }).execute().data
        if not a["videos"]:
            continue
        proposals = supabase().table("playlist_proposals").insert([
            {"video_id": v["video_id"], "playlist_id": a["playlist_id"],
             "video_title": v["title"], "playlist_title": a["title"], "action": "add",
             "similarity": v["similarity"],
             "decision_source": PlaylistProposalSource.EXPERIMENT,
             "status": "pending", "arm_id": arm["id"]}
            for v in a["videos"]
        ]).execute().data
        supabase().table("playlist_arms").update(
            {"proposal_ids": [p["id"] for p in proposals]}).eq("id", arm["id"]).execute()
    return _summary(plan)


def preview(channel_id: str) -> dict:
    """What `draw` would write, writing nothing: `draw`'s counts and skipped
    playlists, whether the channel is already drawn, and under `plan` per
    eligible playlist its arm, status and the videos it would get (with
    similarity and impressions; none for a holdout arm)."""
    plan = _plan(channel_id)
    return {**_summary(plan), "already_drawn": plan["already_drawn"], "plan": plan["arms"]}
