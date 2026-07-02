"""Phase 0.5 — daily Reporting API poll (closes Gap 1: impressions/CTR).

For every channel with `analytics_authorized=true`:

  1. Ensure the channel's `channel_reach_basic_a1` reporting job exists
     (find-or-create; creation respects DRY_RUN — see reporting_client).
  2. List the job's generated report files; ingest every one not already in
     the `reporting_reports_ingested` ledger. Each CSV lands as per-video
     daily rows in `video_reach_daily` (upsert on video_id+date — YouTube
     can reissue a corrected report for a data-day; latest ingest wins).
  3. Backfill `video_metrics.impressions` / `ctr` for weekly windows whose
     EVERY data-day is covered by an ingested report. Partial windows are
     never written — a half-covered window would understate impressions and
     poison Loop 1's CTR baseline comparison.

Window CTR is the impression-weighted aggregate, not a mean of daily CTRs:
    ctr = sum(impressions_d * ctr_d) / sum(impressions_d)
(clicks reconstructed per day, then re-divided — a low-traffic day's noisy
CTR shouldn't count as much as a high-traffic day's).

A video absent from a covered day's CSV genuinely had 0 impressions that day
(verified: the CSV only lists videos with >=1 impression). So over a fully
covered window, a video with no daily rows gets impressions=0 and ctr NULL
(0/0 is no signal, not zero CTR).

Failure model mirrors metrics_poll: per-report and per-channel exceptions are
isolated; TokenExpiredError skips the channel until re-consent.

Quota: Reporting API pool is separate from the Data API 10k/day budget.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app.analytics_client import AnalyticsNotAuthorizedError
from app.db import supabase
from app.reporting_client import (
    download_report_csv,
    ensure_reach_job,
    list_reports,
    parse_reach_csv,
    report_data_date,
    reporting_for_channel,
)
from app.youtube_client import TokenExpiredError

log = logging.getLogger("midas.reporting_poll")

# Supabase upsert batch size — keeps request payloads well under limits.
_UPSERT_CHUNK = 500
# Only backfill video_metrics windows ending within this many trailing days.
# Older windows either predate reach data entirely or were already filled;
# bounding the scan keeps the daily job cheap as video_metrics grows.
_BACKFILL_LOOKBACK_DAYS = 90


def _ledger_state(channel_id: str) -> tuple[set[str], set[str]]:
    """One paginated ledger read → (ingested report ids, covered data-days)."""
    ids: set[str] = set()
    dates: set[str] = set()
    offset = 0
    PAGE = 1000
    while True:
        page = (
            supabase().table("reporting_reports_ingested")
            .select("report_id,data_date")
            .eq("channel_id", channel_id)
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        ids.update(r["report_id"] for r in page)
        dates.update(r["data_date"] for r in page)
        if len(page) < PAGE:
            break
        offset += PAGE
    return ids, dates


def _ingest_report(handle, channel_id: str, job_id: str, report: dict) -> int:
    """Download + land one report CSV. Returns rows written.

    Reissue handling: YouTube can emit a CORRECTED report for a data-day
    already ingested under a different report id. Latest-wins is enforced in
    both directions — the upsert overwrites videos present in the new CSV,
    and the delete below removes daily rows the correction no longer lists
    (a video corrected down to 0 impressions would otherwise keep its stale
    row forever). If the day was previously ingested, any video_metrics
    windows containing it are re-NULLed so the backfill pass recomputes them
    from corrected data — without this, already-filled windows would keep
    baselining Loop 1 on superseded numbers.
    """
    data_date = report_data_date(report).isoformat()
    prior = (
        supabase().table("reporting_reports_ingested")
        .select("report_id")
        .eq("channel_id", channel_id)
        .eq("data_date", data_date)
        .neq("report_id", report["id"])
        .execute()
        .data or []
    )

    csv_text = download_report_csv(handle, channel_id, report["downloadUrl"])
    rows = parse_reach_csv(csv_text)
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = [
        {
            "video_id": r["video_id"],
            "channel_id": channel_id,
            "date": r["date"],
            "impressions": r["impressions"],
            "ctr": r["ctr"],
            "report_id": report["id"],
            # Explicit so a reissue overwrite refreshes the timestamp (the
            # column default only fires on insert).
            "fetched_at": now_iso,
        }
        for r in rows
    ]
    for i in range(0, len(payload), _UPSERT_CHUNK):
        supabase().table("video_reach_daily").upsert(
            payload[i : i + _UPSERT_CHUNK], on_conflict="video_id,date"
        ).execute()

    # Sweep rows for this day that the current report did not (re)write.
    # Rows for a date can only originate from a report of that same data-day,
    # so report_id != current means superseded.
    supabase().table("video_reach_daily").delete().eq("channel_id", channel_id).eq(
        "date", data_date
    ).neq("report_id", report["id"]).execute()

    if prior:
        log.info(
            "reissued report for %s data-day %s (supersedes %s); re-NULLing "
            "overlapping video_metrics windows for recompute",
            channel_id, data_date, [p["report_id"] for p in prior],
        )
        supabase().table("video_metrics").update(
            {"impressions": None, "ctr": None}
        ).eq("channel_id", channel_id).lte("window_start", data_date).gte(
            "window_end", data_date
        ).execute()

    # Ledger row LAST — if the process dies mid-ingest, the report is retried
    # next run and every step above is idempotent.
    supabase().table("reporting_reports_ingested").upsert(
        {
            "report_id": report["id"],
            "job_id": job_id,
            "channel_id": channel_id,
            "data_date": data_date,
            "row_count": len(payload),
        },
        on_conflict="report_id",
    ).execute()
    return len(payload)


def _window_days(start: str, end: str) -> list[str]:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


def _backfill_windows(channel_id: str, covered: set[str]) -> dict:
    """Fill video_metrics.impressions/ctr where the window is fully covered."""
    if not covered:
        return {"windows_checked": 0, "rows_filled": 0}

    # UTC-anchored like metrics_poll._window_dates — the whole reach pipeline
    # reasons in UTC data-days; a process-local date would shift the lookback
    # boundary by ±1 day depending on server TZ.
    today_utc = datetime.now(timezone.utc).date()
    cutoff = (today_utc - timedelta(days=_BACKFILL_LOOKBACK_DAYS)).isoformat()

    # Candidate rows: recent windows still missing impressions.
    rows: list[dict] = []
    offset = 0
    PAGE = 1000
    while True:
        page = (
            supabase().table("video_metrics")
            .select("id,video_id,window_start,window_end")
            .eq("channel_id", channel_id)
            .is_("impressions", "null")
            .gte("window_end", cutoff)
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    if not rows:
        return {"windows_checked": 0, "rows_filled": 0}

    # Group by window so coverage is checked once per window, and the daily
    # reach rows for a window are fetched once (not once per video).
    windows: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        windows.setdefault((r["window_start"], r["window_end"]), []).append(r)

    filled = 0
    skipped_windows = 0
    for (w_start, w_end), members in windows.items():
        days = _window_days(w_start, w_end)
        missing = [d for d in days if d not in covered]
        if missing:
            # Not fully covered yet; retried next run. Logged (rather than
            # silently skipped) because a data-day YouTube never emits a
            # report for — e.g. days before a late-created job's backfill
            # horizon — would pin these windows NULL until they age past
            # the lookback cutoff, and that should be diagnosable.
            skipped_windows += 1
            log.info(
                "backfill %s: window %s→%s pending, missing data-days %s",
                channel_id, w_start, w_end, missing,
            )
            continue

        # Pull the window's daily reach rows for this channel (paginated).
        daily: list[dict] = []
        offset = 0
        while True:
            page = (
                supabase().table("video_reach_daily")
                .select("video_id,impressions,ctr")
                .eq("channel_id", channel_id)
                .gte("date", w_start)
                .lte("date", w_end)
                .range(offset, offset + PAGE - 1)
                .execute()
                .data or []
            )
            daily.extend(page)
            if len(page) < PAGE:
                break
            offset += PAGE

        agg: dict[str, dict] = {}
        for d in daily:
            a = agg.setdefault(d["video_id"], {"impressions": 0, "clicks": 0.0})
            a["impressions"] += d["impressions"]
            a["clicks"] += d["impressions"] * d["ctr"]

        # One UPDATE per row: ~1 round-trip per video per window. Fine at the
        # current fleet size (a window fills once, then drops out of the
        # NULL-impressions candidate set). If this becomes the slow step,
        # batch by grouping rows on identical (impressions, ctr) pairs and
        # updating with .in_("id", [...]) — an upsert-based batch is unsafe
        # here because a conflict-miss insert would trip NOT NULL columns.
        for m in members:
            a = agg.get(m["video_id"])
            impressions = a["impressions"] if a else 0
            # 0 impressions over a certified-covered window is a REAL zero
            # (unlike Analytics "no row" = no observation); ctr stays NULL
            # because 0/0 is no signal, not 0% CTR.
            ctr = (a["clicks"] / a["impressions"]) if a and a["impressions"] > 0 else None
            supabase().table("video_metrics").update(
                {"impressions": impressions, "ctr": ctr}
            ).eq("id", m["id"]).execute()
            filled += 1

    return {
        "windows_checked": len(windows),
        "windows_pending_coverage": skipped_windows,
        "rows_filled": filled,
    }


def _poll_channel(channel_id: str) -> dict:
    handle = reporting_for_channel(channel_id)
    job_id = ensure_reach_job(handle, channel_id)
    if job_id is None:
        # DRY_RUN with no existing job — nothing to ingest yet.
        return {"job": None, "reports_new": 0, "rows_ingested": 0}

    reports = list_reports(handle, channel_id, job_id)
    seen, covered = _ledger_state(channel_id)
    new = [r for r in reports if r["id"] not in seen]
    # Oldest data-day first, so coverage grows contiguously and a mid-run
    # crash leaves the older (more backfill-relevant) days ingested.
    new.sort(key=report_data_date)

    rows_ingested = 0
    reports_err = 0
    for report in new:
        try:
            rows_ingested += _ingest_report(handle, channel_id, job_id, report)
            # Only successfully ingested days extend coverage — counting a
            # failed report's day would let the backfill certify a window
            # against data that never landed.
            covered.add(report_data_date(report).isoformat())
        except TokenExpiredError:
            raise
        except Exception as e:
            reports_err += 1
            log.warning(
                "reach report ingest failed for %s report %s: %s",
                channel_id, report.get("id"), e,
            )

    backfill = _backfill_windows(channel_id, covered)
    return {
        "job": job_id,
        "reports_listed": len(reports),
        "reports_new": len(new),
        "reports_err": reports_err,
        "rows_ingested": rows_ingested,
        **backfill,
    }


def poll_reporting() -> None:
    """APScheduler entry point. One pass over all re-consented channels."""
    channels = (
        supabase().table("channels")
        .select("id")
        .eq("analytics_authorized", True)
        .execute()
        .data or []
    )
    if not channels:
        log.info("reporting_poll: no channels with analytics_authorized=true; nothing to do")
        return

    for ch in channels:
        cid = ch["id"]
        try:
            counts = _poll_channel(cid)
            log.info("reporting_poll %s: %s", cid, counts)
        except AnalyticsNotAuthorizedError:
            log.info("reporting_poll %s: analytics_authorized flipped to false; skipped", cid)
        except TokenExpiredError:
            log.warning("reporting_poll %s: OAuth token expired; skipping until re-consent", cid)
        except Exception as e:
            log.exception("reporting_poll %s crashed: %s", cid, e)
