import csv
import io
import statistics
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.db import supabase

router = APIRouter(tags=["performance"])


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


def _build_rows(channel_id: str, statuses: list[str] | None) -> list[dict]:
    """Pull audits filtered by status set and join video stats. Computes deltas,
    % change, engagement ratios, views/day since apply, and a regression flag."""
    q = (
        supabase().table("audits")
        .select("id,video_id,applied_at,created_at,status,"
                "suggested_title,suggested_description,suggested_tags,"
                "title_before,description_before,tags_before,"
                "view_count_at_apply,like_count_at_apply,comment_count_at_apply,"
                "ai_reasoning,issues_found")
        .order("applied_at", desc=True)
    )
    if statuses:
        q = q.in_("status", statuses)
    audits = (q.execute()).data or []
    if not audits:
        return []

    video_ids = list({a["video_id"] for a in audits})
    vids = (
        supabase().table("videos")
        .select("id,channel_id,title,thumbnail_url,view_count,like_count,comment_count,"
                "last_fetched_at,published_at")
        .in_("id", video_ids)
        .execute()
    ).data or []
    videos_by_id = {v["id"]: v for v in vids}

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

        # Pre-apply velocity = views_at_apply / age_at_apply (views/day before audit).
        # Post-apply velocity = delta_views / days_since_apply (views/day after audit).
        # Velocity lift = (after - before) / before * 100. Only computed with ≥7d post-apply.
        before_velocity = None
        after_velocity = None
        velocity_lift_pct = None
        regression = False
        pub = _parse_iso(v.get("published_at"))
        ap = _parse_iso(a.get("applied_at"))
        if pub and ap and view_at > 0:
            age_at_apply_days = max(1.0, (ap - pub).total_seconds() / 86400.0)
            before_velocity = round(view_at / age_at_apply_days, 2)
        if days and days >= 7 and before_velocity and before_velocity > 0 and views_per_day is not None:
            after_velocity = views_per_day
            velocity_lift_pct = round(((after_velocity - before_velocity) / before_velocity) * 100.0, 1)
        if before_velocity and views_per_day is not None and days and days > 1:
            if before_velocity > 0 and views_per_day < 0.5 * before_velocity:
                regression = True

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
            "before_velocity": before_velocity,
            "after_velocity": after_velocity,
            "velocity_lift_pct": velocity_lift_pct,
            "regression": regression,
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
    rows = _build_rows(channel_id, statuses)

    if not rows:
        return {
            "count": 0,
            "applied_count": 0,
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

    # Velocity metrics — only rows with ≥7 days post-apply data
    velocity_rows = [r for r in applied if r.get("velocity_lift_pct") is not None]
    median_velocity_lift = None
    win_rate = None
    outcome_distribution = {"accelerated": 0, "flat": 0, "regression": 0, "total": 0}
    if velocity_rows:
        lifts = [r["velocity_lift_pct"] for r in velocity_rows]
        median_velocity_lift = round(statistics.median(lifts), 1)
        accelerated = [r for r in velocity_rows if r["velocity_lift_pct"] > 10]
        flat = [r for r in velocity_rows if -10 <= r["velocity_lift_pct"] <= 10]
        regressed = [r for r in velocity_rows if r["velocity_lift_pct"] < -10]
        win_rate = round(100.0 * len(accelerated) / len(velocity_rows), 1)
        outcome_distribution = {
            "accelerated": len(accelerated),
            "flat": len(flat),
            "regression": len(regressed),
            "total": len(velocity_rows),
        }

    def _cohort(predicate) -> dict:
        sub = [r for r in applied if predicate(r)]
        if not sub:
            return {"n": 0, "avg_delta_views": 0, "avg_pct_views": None, "avg_velocity_lift": None}
        d = [r["delta_views"] for r in sub]
        p = [r["pct_views"] for r in sub if r["pct_views"] is not None]
        vl = [r["velocity_lift_pct"] for r in sub if r.get("velocity_lift_pct") is not None]
        return {
            "n": len(sub),
            "avg_delta_views": round(sum(d) / len(d), 1),
            "avg_pct_views": round(sum(p) / len(p), 2) if p else None,
            "avg_velocity_lift": round(sum(vl) / len(vl), 1) if vl else None,
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

    # Best lever by avg velocity lift among changed cohorts
    lever_lifts = {
        "title": (cohorts["title_changed"]["avg_velocity_lift"] or 0),
        "description": (cohorts["description_changed"]["avg_velocity_lift"] or 0),
        "tags": (cohorts["tags_changed"]["avg_velocity_lift"] or 0),
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
        "regression_count": sum(1 for r in applied if r["regression"]),
        "median_velocity_lift": median_velocity_lift,
        "win_rate": win_rate,
        "outcome_distribution": outcome_distribution,
        "best_lever": best_lever,
        "best_lever_lift": lever_lifts.get(best_lever) if best_lever else None,
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
        "title_changed", "description_changed", "tags_changed", "regression",
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
