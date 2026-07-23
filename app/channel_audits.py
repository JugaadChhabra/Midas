"""Channel-scoped access to the `audits` table.

`audits` has no `channel_id` column, so consumers historically pulled every one
of a channel's video ids and filtered audits with `.in_(video_ids)`. Unpaginated,
that `select("id")` silently truncates at Supabase's 1000-row page cap — so on
channels with >1000 videos, audits past the first 1000 were dropped (wrong
perf reports, missed pending applies, undercounted cap gates).

This module hides the correct form: an embedded inner-join to `videos`, filtered
by `videos.channel_id`, which scopes by channel with no truncation and no
separate all-video-ids round-trip. Callers keep full control of columns, status
filters, ordering and limits by chaining onto the returned query.
"""
from app.db import supabase


def audits_for_channel(channel_id: str, columns: str, video_columns: str = "channel_id"):
    """A postgrest query over `audits` scoped to one channel via `videos!inner`.

    Chain `.eq()/.gte()/.order()/.limit()/.execute()` as usual. Every returned
    row carries the embedded join under key ``"videos"`` (e.g. ``{"channel_id": …}``);
    ignore it, or widen ``video_columns`` to pull extra fields (like the title) in
    the same round-trip.

    Example:
        rows = (
            audits_for_channel(cid, "id,video_id,status,created_at")
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        ).data or []
    """
    return (
        supabase().table("audits")
        .select(f"{columns},videos!inner({video_columns})")
        .eq("videos.channel_id", channel_id)
    )
