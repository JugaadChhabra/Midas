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
existing proposals card (E3). Approving one there only queues it
(`playlists_router.decide_proposals`).

S2.2, the apply:

    run_apply()                       -- the daily `playlist_test_apply` job
    apply_channel(channel_id, budget) -- one channel's approved, unsent adds
    test_dates(channel_id)            -- (test_start, test_end), once dosed

The job is the test's only YouTube write: `playlistItems.insert`, at the top
in candidate rank (E2), behind PLAYLIST_APPLY_ENABLED and DRY_RUN, whole
playlists at a time under its JobBudget. Nothing removes, renames or creates.

Similarity is on B6 vectors only (`reembed.MODEL_VERSION`), against the
channel's calibrated `join_high`; thresholds are never recalibrated here.
Current members are the latest `playlist_assignments` action per pair being
`added`, as `reembed.calibrate_channel` reads them.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from typing import NamedTuple

from app import job_status, quota, warm
from app.apply_outcome import ApplyOutcome
from app.backlinks import NO_THRESHOLDS, THRESHOLDS_OTHER_MODEL, _thresholds
from app.backlinks_apply import _classified
from app.config import settings
from app.db import supabase
from app.embeddings import pooled_embeddings
from app.lever_measurement import _day
from app.playlists import _cosine_sim, _record_assignment
from app.reembed import MODEL_VERSION, _members
from app.rows import all_rows, rows_for_ids
from app.status_vocab import PlaylistArm, PlaylistArmStatus, PlaylistProposalSource
from app.youtube_client import youtube_for_channel, yt_playlist_items_insert

log = logging.getLogger("midas.playlist_test")

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


class Pool(NamedTuple):
    """The channel's videos that could join any of its playlists, read once per draw."""

    impressions: dict[str, int]
    videos: list[dict]
    vectors: dict[str, list[float]]


def _pool(channel_id: str) -> Pool:
    """The channel's warm videos that could join any playlist: public (or
    NULL), not a Short, not an episode. A NULL `is_short` or `is_episode` is
    not yet known, and eligible (as warm_pool())."""
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
    return Pool(impressions, videos, vectors)


def _score(playlist: dict, join_high: float, pool: Pool) -> Candidates:
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
    pool = _pool(channel_id) if found.eligible else Pool({}, [], {})
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


# ── S2.2, the apply ───────────────────────────────────────────────────────

#: A treated arm the job still works on.
_OPEN = (PlaylistArmStatus.PLANNED, PlaylistArmStatus.APPLYING)

#: playlist_proposals.apply_error.reason for an add YouTube took only appended,
#: because the playlist isn't sorted manually (Part 5 finding 7).
POSITION_REFUSED = "position_refused"

#: apply_channel's `stopped`: the job's budget or the ledger can't take the
#: next playlist whole.
BUDGET = "budget"

#: The job_status.item_error_verdict category.
ITEMS = "playlist adds"


def _attempts(proposal: dict) -> int:
    return (proposal.get("apply_error") or {}).get("attempts", 0)


def _sendable(proposal: dict) -> bool:
    """Approved, not yet sent, and not failed PLAYLIST_TEST_MAX_ATTEMPTS runs."""
    return (proposal["status"] == "approved" and not proposal.get("applied_at")
            and _attempts(proposal) < settings.PLAYLIST_TEST_MAX_ATTEMPTS)


def _ranked(arm: dict, proposals: list[dict]) -> list[dict]:
    """The arm's proposals in candidate rank (`proposal_ids` order)."""
    rank = {pid: i for i, pid in enumerate(arm.get("proposal_ids") or [])}
    return sorted(proposals, key=lambda p: (rank.get(p["id"], len(rank)), p["id"]))


def _position_refused(e: Exception) -> bool:
    """YouTube's 400 for a position on a playlist that isn't sorted manually
    (manualSortRequired): a 400 that names the position or the sort order."""
    status = getattr(getattr(e, "resp", None), "status", None)
    text = str(e).lower()
    return status == 400 and ("position" in text or "sort" in text)


def _insert(yt, channel_id: str, proposal: dict, position: int | None):
    """(playlist item id, apply_error note or None). A refused position is
    retried once, appended."""
    try:
        return yt_playlist_items_insert(yt, channel_id, proposal["playlist_id"],
                                        proposal["video_id"], position=position), None
    except Exception as e:
        if position is None or not _position_refused(e):
            raise
        note = {"reason": POSITION_REFUSED, "detail": str(e)}
    return yt_playlist_items_insert(yt, channel_id, proposal["playlist_id"],
                                    proposal["video_id"]), note


def _update(proposal: dict, fields: dict) -> None:
    supabase().table("playlist_proposals").update(fields).eq("id", proposal["id"]).execute()
    proposal.update(fields)


def _affordable(budget: quota.JobBudget, cost: int) -> bool:
    """The job's own budget, and the ledger above YT_QUOTA_COLLECTION_RESERVE
    (as autopilot._can_afford_apply)."""
    return budget.can_spend(cost) and quota.can_afford(
        cost, reserve=settings.YT_QUOTA_COLLECTION_RESERVE)


def _send(channel_id: str, yt, ranked: list[dict], counts: dict) -> str | None:
    """Send one arm's sendable adds at the top, in rank. Returns
    `youtube_quota_exceeded` when YouTube says so; raises ApplyError on a token
    error. Each failure is written to its proposal's `apply_error`. A
    quotaExceeded isn't counted as an errored add: it is a stop, not the add's
    failure."""
    ahead = 0
    # A position refused before, in this run or an earlier one, means the
    # playlist isn't sorted manually: append, without paying for the refusal again.
    append = any((p.get("apply_error") or {}).get("reason") == POSITION_REFUSED for p in ranked)
    for p in ranked:
        if p.get("applied_at"):
            ahead += 1
            continue
        if not _sendable(p):
            continue
        try:
            item_id, note = _insert(yt, channel_id, p, None if append else ahead)
        except Exception as e:
            err = _classified(e)
            if err.outcome is not ApplyOutcome.QUOTA_EXCEEDED:
                counts["attempted"] += 1
                counts["errored"] += 1
            # Quota and token errors aren't the add's fault: no attempt is used up.
            attempts = _attempts(p) + (err.outcome is ApplyOutcome.FAILED)
            _update(p, {"apply_error": {"reason": err.outcome.value, "detail": str(e),
                                        "attempts": attempts}})
            log.warning("playlist_test_apply %s: add %s (%s to %s) failed: %s",
                        channel_id, p["id"], p["video_id"], p["playlist_id"], e)
            if err.outcome is ApplyOutcome.QUOTA_EXCEEDED:
                return err.outcome.value
            if err.outcome is ApplyOutcome.TOKEN_EXPIRED:
                raise err
            continue
        counts["attempted"] += 1
        append = append or note is not None
        fields = {"applied_at": datetime.now(timezone.utc).isoformat(),
                  "playlist_item_id": item_id}
        if note:
            fields["apply_error"] = note
        _update(p, fields)
        _record_assignment(p["video_id"], p["playlist_id"], item_id, "added",
                           p.get("similarity"), PlaylistProposalSource.EXPERIMENT)
        counts["sent"] += 1
        ahead += 1
    return None


def _settle(arm: dict, ranked: list[dict]) -> None:
    """The arm's status from its proposals: `applying` once one add is sent;
    once no approved add is left unsent or retryable, `dosed` (some add landed)
    or `no_dose` (none did). An arm with nothing approved stays open while any
    proposal is pending (`no_dose` once all are rejected). `first_applied_at`,
    `last_applied_at` = the first and last success."""
    sent = sorted((p["applied_at"] for p in ranked if p.get("applied_at")),
                  key=lambda t: datetime.fromisoformat(str(t).replace("Z", "+00:00")))
    approved = any(p["status"] == "approved" for p in ranked)
    still_open = (any(_sendable(p) for p in ranked)
                  or (not approved and any(p["status"] == "pending" for p in ranked)))
    if still_open:
        status = PlaylistArmStatus.APPLYING if sent else arm["status"]
    else:
        status = PlaylistArmStatus.DOSED if sent else PlaylistArmStatus.NO_DOSE
    fields = {}
    if status != arm["status"]:
        fields["status"] = status
    if sent and not arm.get("first_applied_at"):
        fields["first_applied_at"] = sent[0]
    if sent and arm.get("last_applied_at") != sent[-1]:
        fields["last_applied_at"] = sent[-1]
    if fields:
        supabase().table("playlist_arms").update(fields).eq("id", arm["id"]).execute()
        arm.update(fields)


def apply_channel(channel_id: str, budget: quota.JobBudget) -> dict:
    """Send the channel's approved, unsent test adds, a treated playlist at a time.

    A playlist goes whole or not at all: if its adds' cost doesn't fit
    `budget` and the ledger above YT_QUOTA_COLLECTION_RESERVE, the channel
    stops with `stopped = 'budget'`, and so does the job. YouTube's
    quotaExceeded stops it too (`stopped = 'youtube_quota_exceeded'`); a token
    error raises ApplyError (the channel is skipped). Under DRY_RUN it logs what
    it would send and writes nothing. Returns `{attempted, errored, sent,
    stopped}`.
    """
    counts = {"attempted": 0, "errored": 0, "sent": 0, "stopped": None}
    arms = all_rows(
        supabase().table("playlist_arms").select("*")
        .eq("channel_id", channel_id).eq("arm", PlaylistArm.TREATED).in_("status", list(_OPEN)))
    by_arm: dict[int, list[dict]] = {}
    for p in rows_for_ids(
            lambda c: supabase().table("playlist_proposals").select("*").in_("arm_id", c),
            [a["id"] for a in arms]):
        by_arm.setdefault(p["arm_id"], []).append(p)
    yt = None
    for arm in sorted(arms, key=lambda a: a["id"]):
        ranked = _ranked(arm, by_arm.get(arm["id"], []))
        todo = [p for p in ranked if _sendable(p)]
        if settings.DRY_RUN:
            if todo:
                log.warning("[DRY_RUN] playlist_test_apply %s: would add %s to the top of %s",
                            channel_id, [p["video_id"] for p in todo], arm["playlist_id"])
            continue
        try:
            if todo:
                cost = quota.cost(quota.Op.PLAYLIST_ITEMS_INSERT, len(todo))
                if not _affordable(budget, cost):
                    log.info("playlist_test_apply: stopping for the day; %s needs %du for %d "
                             "adds, %s, %du left above the %du collection reserve",
                             arm["playlist_id"], cost, len(todo), budget,
                             quota.units_remaining(settings.YT_QUOTA_COLLECTION_RESERVE),
                             settings.YT_QUOTA_COLLECTION_RESERVE)
                    counts["stopped"] = BUDGET
                    return counts
                if yt is None:
                    yt = youtube_for_channel(channel_id)
                counts["stopped"] = _send(channel_id, yt, ranked, counts)
        finally:
            _settle(arm, ranked)
        if counts["stopped"]:
            return counts
    return counts


def _open_channels() -> list[str]:
    rows = all_rows(
        supabase().table("playlist_arms").select("channel_id")
        .eq("arm", PlaylistArm.TREATED).in_("status", list(_OPEN)))
    return sorted({r["channel_id"] for r in rows})


def run_apply() -> dict | None:
    """APScheduler entry point (`playlist_test_apply`, daily 11:00 UTC).

    Does nothing unless PLAYLIST_APPLY_ENABLED. Otherwise `apply_channel` for
    every channel with a treated arm still `planned` or `applying`, under one
    JobBudget("playlist_test_apply", PLAYLIST_TEST_DAILY_UNITS), until a
    playlist doesn't fit or YouTube says quotaExceeded. traffic_poll's failure
    model: a channel that raises (a token error included) fails the run once
    every channel has run; per-add errors are judged by
    job_status.item_error_verdict under `playlist adds`.
    """
    if not settings.PLAYLIST_APPLY_ENABLED:
        log.info("playlist_test_apply skipped: PLAYLIST_APPLY_ENABLED=false")
        return None
    budget = quota.JobBudget("playlist_test_apply", settings.PLAYLIST_TEST_DAILY_UNITS)
    crashed: dict[str, str] = {}
    partial_errors: dict[str, str] = {}
    with quota.spending(budget):
        for cid in _open_channels():
            try:
                counts = apply_channel(cid, budget)
            except Exception as e:
                log.exception("playlist_test_apply %s crashed: %s", cid, e)
                crashed[cid] = job_status.describe(e)
                continue
            failure, partial = job_status.item_error_verdict(
                {ITEMS: (counts["errored"], counts["attempted"])})
            if counts["stopped"] == ApplyOutcome.QUOTA_EXCEEDED.value:
                partial = "; ".join(filter(None, [partial, "youtube_quota_exceeded: stopped for the day"]))
            if failure:
                crashed[cid] = f"ItemsFailed: {failure}"
            elif partial:
                partial_errors[cid] = partial
            log.info("playlist_test_apply %s: %d sent, %d failed (%s)",
                     cid, counts["sent"], counts["errored"], budget)
            if counts["stopped"]:
                break
    if crashed:
        raise job_status.JobRunFailed("playlist_test_apply", crashed)
    return {"partial_errors": partial_errors} if partial_errors else None


def test_dates(channel_id: str) -> tuple[date, date] | None:
    """(test_start, test_end): the Pacific dates of the channel's first
    `first_applied_at` and last `last_applied_at` over its treated arms. None
    until the test is dosed (no treated arm `planned` or `applying`), and when
    no add ever landed. Holdout arms have no dates of their own."""
    arms = all_rows(
        supabase().table("playlist_arms").select("id,status,first_applied_at,last_applied_at")
        .eq("channel_id", channel_id).eq("arm", PlaylistArm.TREATED))
    if not arms or any(a["status"] in _OPEN for a in arms):
        return None
    firsts = [_day(a["first_applied_at"]) for a in arms if a.get("first_applied_at")]
    lasts = [_day(a["last_applied_at"]) for a in arms if a.get("last_applied_at")]
    if not firsts:
        return None
    return min(firsts), max(lasts)


# The module's name matches pytest's `*_test.py`, and this is no test.
test_dates.__test__ = False
