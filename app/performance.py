import csv
import io
import statistics
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.channel_audits import audits_for_channel, fetch_all
from app.db import supabase
from app.status_vocab import MEASURED_STATUSES, AuditStatus

router = APIRouter(tags=["performance"])

# Loop 1 verdicts that count as evidence. `not_applicable` means the audit was
# never measured, not that it was neutral.


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(iso: str | None) -> float | None:
    dt = _parse_iso(iso)
    if not dt:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400.0, 2)


def _pct(delta: float, base: float) -> float | None:
    if base <= 0:
        return None
    return round(100.0 * delta / base, 2)


def _build_rows(channel_id: str, statuses: list[str] | None,
                include_reasoning: bool = True) -> list[dict]:
    """Pull this channel's audits and join video stats. Computes raw deltas,
    % change, engagement ratios, views/day since apply, and carries Loop 1's
    measured CTR verdict.

    The raw view numbers are descriptive facts and are reported as-is. What is
    NOT computed here any more is a derived verdict from them: `before_velocity`
    used a video's lifetime average views/day as the pre-change baseline, which
    is inflated on any decaying view curve (median 25.8x too high, measured over
    439 audits with a real pre-apply window). That made `velocity_lift_pct` and
    the `regression` flag meaningless, and flagged nearly every audit as a
    regression. Verdicts now come from measurement.py's CTR windows.

    Column selection is deliberately lean:
      - `issues_found` is NEVER selected — it's a large JSON blob that this
        function does not read (it never appeared in the returned row), yet it
        cost ~2s per call. Dropping it is pure win with no behaviour change.
      - `ai_reasoning` is display-only (shown in the row's expandable diff). The
        summary endpoint returns no rows, so it passes include_reasoning=False
        to skip that column entirely.
    """
    cols = ("id,video_id,applied_at,created_at,status,"
            "suggested_title,suggested_description,suggested_tags,"
            "title_before,description_before,tags_before,"
            "view_count_at_apply,like_count_at_apply,comment_count_at_apply,"
            "measurement_status,measurement_result")
    if include_reasoning:
        cols += ",ai_reasoning"
    # Channel-scoped at the query via videos!inner, and paged: this used to
    # select the whole audits table and filter by channel in Python, which
    # silently truncated at Supabase's 1000-row cap.
    q = audits_for_channel(channel_id, cols).order("applied_at", desc=True)
    if statuses:
        q = q.in_("status", statuses)
    audits = fetch_all(q)
    if not audits:
        return []

    # Chunk the video fetch: one .in_() over >1000 ids caps the RESPONSE at
    # Supabase's 1000-row limit, so every audit whose video fell outside that
    # first page was silently dropped from the page (1269 of 1985 rows shown on
    # the live channel). Chunking bounds both the response and the URL length.
    video_ids = list({a["video_id"] for a in audits})
    videos_by_id: dict[str, dict] = {}
    for i in range(0, len(video_ids), 500):
        for v in (
            supabase().table("videos")
            # published_at is no longer needed — it only fed the removed
            # velocity baseline. Dropping it keeps the payload lean.
            .select("id,channel_id,title,thumbnail_url,view_count,like_count,"
                    "comment_count,last_fetched_at")
            .in_("id", video_ids[i:i + 500])
            .execute().data or []
        ):
            videos_by_id[v["id"]] = v

    rows: list[dict] = []
    for a in audits:
        v = videos_by_id.get(a["video_id"])
        if not v or v.get("channel_id") != channel_id:
            continue
        view_now = v.get("view_count") or 0
        like_now = v.get("like_count") or 0
        comment_now = v.get("comment_count") or 0
        view_at = a.get("view_count_at_apply") or 0
        like_at = a.get("like_count_at_apply") or 0
        comment_at = a.get("comment_count_at_apply") or 0

        d_views = view_now - view_at
        d_likes = like_now - like_at
        d_comments = comment_now - comment_at
        days = _days_since(a.get("applied_at"))

        title_changed = (a.get("title_before") or "") != (a.get("suggested_title") or "")
        desc_changed = (a.get("description_before") or "") != (a.get("suggested_description") or "")
        tags_before = a.get("tags_before") or []
        tags_after = a.get("suggested_tags") or []
        tags_changed = list(tags_before or []) != list(tags_after or [])

        # Engagement ratios
        eng_at = ((like_at + comment_at) / view_at * 100.0) if view_at > 0 else None
        eng_now = ((like_now + comment_now) / view_now * 100.0) if view_now > 0 else None

        # Views/day since apply (if applied)
        views_per_day = None
        if days and days > 0:
            views_per_day = round(d_views / days, 1)

        # Loop 1's verdict for this audit, if the measurement window has closed.
        # `neutral` can legitimately carry no delta (pre-CTR was zero, or post
        # impressions were under the floor) — the verdict still stands.
        m_result = a.get("measurement_result") or {}
        m_status = a.get("measurement_status")
        m_delta = m_result.get("ctr_delta_relative")
        ctr_delta_pct = round(m_delta * 100.0, 1) if m_delta is not None else None
        # The measured window pair, for the before/after chart. These are real
        # rates over matched windows, which is what the old before/after view
        # bars only pretended to be.
        _pre_ctr = (m_result.get("pre_window") or {}).get("ctr")
        _post_ctr = (m_result.get("post_window") or {}).get("ctr")
        ctr_before_pct = round(_pre_ctr * 100.0, 2) if _pre_ctr is not None else None
        ctr_after_pct = round(_post_ctr * 100.0, 2) if _post_ctr is not None else None

        rows.append({
            "audit_id": a["id"],
            "video_id": a["video_id"],
            "status": a["status"],
            "title_now": v.get("title"),
            "thumbnail_url": v.get("thumbnail_url"),
            "applied_at": a.get("applied_at"),
            "created_at": a.get("created_at"),
            "days_since_apply": days,
            "title_before": a.get("title_before"),
            "title_after": a.get("suggested_title"),
            "description_before": a.get("description_before"),
            "description_after": a.get("suggested_description"),
            "tags_before": tags_before,
            "tags_after": tags_after,
            "title_changed": title_changed,
            "description_changed": desc_changed,
            "tags_changed": tags_changed,
            "ai_reasoning": a.get("ai_reasoning"),
            "view_count_at_apply": view_at,
            "like_count_at_apply": like_at,
            "comment_count_at_apply": comment_at,
            "view_count_now": view_now,
            "like_count_now": like_now,
            "comment_count_now": comment_now,
            "delta_views": d_views,
            "delta_likes": d_likes,
            "delta_comments": d_comments,
            "pct_views": _pct(d_views, view_at),
            "pct_likes": _pct(d_likes, like_at),
            "pct_comments": _pct(d_comments, comment_at),
            "engagement_at_apply_pct": round(eng_at, 3) if eng_at is not None else None,
            "engagement_now_pct": round(eng_now, 3) if eng_now is not None else None,
            "views_per_day_since_apply": views_per_day,
            "measurement_status": m_status,
            "ctr_delta_pct": ctr_delta_pct,
            "ctr_before_pct": ctr_before_pct,
            "ctr_after_pct": ctr_after_pct,
            "stats_last_fetched": v.get("last_fetched_at"),
        })
    return rows


@router.get("/channels/{channel_id}/performance")
def channel_performance(channel_id: str, status: str | None = Query(default=None)):
    """status: comma-separated list. Default = applied (back-compat). Pass 'all' for any status."""
    if not status:
        statuses = ["applied"]
    elif status == "all":
        statuses = None
    else:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
    return _build_rows(channel_id, statuses)


@router.get("/channels/{channel_id}/performance/summary")
def performance_summary(channel_id: str, status: str | None = Query(default="applied")):
    """KPI strip + cohort breakdowns for the performance page header."""
    if status == "all":
        statuses = None
    else:
        statuses = [s.strip() for s in (status or "applied").split(",") if s.strip()]
    # Summary returns aggregates only — no per-row diff is rendered — so skip the
    # display-only ai_reasoning column.
    rows = _build_rows(channel_id, statuses, include_reasoning=False)

    if not rows:
        return {
            "count": 0,
            "applied_count": 0,
            "measured_count": 0,
            "ctr_measured_count": 0,
            "total_delta_views": 0,
            "total_delta_likes": 0,
            "total_delta_comments": 0,
            "avg_pct_views": None,
            "positive_pct_share": None,
            "regression_count": 0,
            "cohorts": {},
        }

    applied = [r for r in rows if r["status"] == "applied"]
    deltas = [r["delta_views"] for r in applied]
    pct_list = [r["pct_views"] for r in applied if r["pct_views"] is not None]
    positive = [d for d in deltas if d > 0]
    avg_pct = round(sum(pct_list) / len(pct_list), 2) if pct_list else None

    # Measured outcomes — only audits whose CTR window has closed. Everything
    # else is `not_applicable` (never measured) and carries no evidence, so it
    # is excluded from the verdict stats rather than counted as neutral.
    measured = [r for r in applied if r.get("measurement_status") in MEASURED_STATUSES]
    median_ctr_delta = None
    win_rate = None
    outcome_distribution = {"win": 0, "neutral": 0, "regression": 0, "total": 0}
    ctr_deltas: list[float] = []
    if measured:
        # NB: this list is deliberately NOT called `deltas`. It used to be, which
        # rebound the view-delta list above it — so `total_delta_views` returned
        # a sum of CTR percentages and `positive_pct_share` divided a count of
        # positive view deltas by a count of CTR rows, yielding 2160%.
        ctr_deltas = [r["ctr_delta_pct"] for r in measured if r.get("ctr_delta_pct") is not None]
        median_ctr_delta = round(statistics.median(ctr_deltas), 1) if ctr_deltas else None
        counts = {k: sum(1 for r in measured if r["measurement_status"] == k)
                  for k in MEASURED_STATUSES}
        win_rate = round(100.0 * counts["win"] / len(measured), 1)
        outcome_distribution = {**counts, "total": len(measured)}

    def _cohort(predicate) -> dict:
        sub = [r for r in applied if predicate(r)]
        if not sub:
            return {"n": 0, "avg_delta_views": 0, "avg_pct_views": None, "avg_ctr_delta_pct": None}
        d = [r["delta_views"] for r in sub]
        p = [r["pct_views"] for r in sub if r["pct_views"] is not None]
        c = [r["ctr_delta_pct"] for r in sub if r.get("ctr_delta_pct") is not None]
        return {
            "n": len(sub),
            "avg_delta_views": round(sum(d) / len(d), 1),
            "avg_pct_views": round(sum(p) / len(p), 2) if p else None,
            "avg_ctr_delta_pct": round(sum(c) / len(c), 1) if c else None,
        }

    cohorts = {
        "title_changed": _cohort(lambda r: r["title_changed"]),
        "title_unchanged": _cohort(lambda r: not r["title_changed"]),
        "description_changed": _cohort(lambda r: r["description_changed"]),
        "description_unchanged": _cohort(lambda r: not r["description_changed"]),
        "tags_changed": _cohort(lambda r: r["tags_changed"]),
        "tags_unchanged": _cohort(lambda r: not r["tags_changed"]),
        "all_changed": _cohort(lambda r: r["title_changed"] and r["description_changed"] and r["tags_changed"]),
    }

    # Best lever by avg measured CTR change among changed cohorts
    lever_lifts = {
        "title": (cohorts["title_changed"]["avg_ctr_delta_pct"] or 0),
        "description": (cohorts["description_changed"]["avg_ctr_delta_pct"] or 0),
        "tags": (cohorts["tags_changed"]["avg_ctr_delta_pct"] or 0),
    }
    best_lever = max(lever_lifts, key=lever_lifts.get) if any(v > 0 for v in lever_lifts.values()) else None

    return {
        "count": len(rows),
        "applied_count": len(applied),
        "total_delta_views": sum(deltas),
        "total_delta_likes": sum(r["delta_likes"] for r in applied),
        "total_delta_comments": sum(r["delta_comments"] for r in applied),
        "avg_pct_views": avg_pct,
        "positive_pct_share": round(100.0 * len(positive) / len(deltas), 1) if deltas else None,
        "regression_count": outcome_distribution["regression"],
        "measured_count": outcome_distribution["total"],
        # How many of the measured rows actually carry a CTR delta. The median
        # and the lever averages are computed over this, not over
        # measured_count — the page was citing the larger number.
        "ctr_measured_count": len(ctr_deltas),
        "median_ctr_delta_pct": median_ctr_delta,
        "win_rate": win_rate,
        "outcome_distribution": outcome_distribution,
        "best_lever": best_lever,
        "best_lever_ctr_delta_pct": lever_lifts.get(best_lever) if best_lever else None,
        "cohorts": cohorts,
    }


@router.get("/channels/{channel_id}/performance.csv")
def performance_csv(channel_id: str, status: str | None = Query(default="applied")):
    if status == "all":
        statuses = None
    else:
        statuses = [s.strip() for s in (status or "applied").split(",") if s.strip()]
    rows = _build_rows(channel_id, statuses)
    cols = [
        "audit_id", "video_id", "status", "title_now", "applied_at", "days_since_apply",
        "view_count_at_apply", "view_count_now", "delta_views", "pct_views",
        "like_count_at_apply", "like_count_now", "delta_likes", "pct_likes",
        "comment_count_at_apply", "comment_count_now", "delta_comments", "pct_comments",
        "engagement_at_apply_pct", "engagement_now_pct", "views_per_day_since_apply",
        "title_changed", "description_changed", "tags_changed",
        "measurement_status", "ctr_delta_pct",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="performance-{channel_id}.csv"'},
    )
