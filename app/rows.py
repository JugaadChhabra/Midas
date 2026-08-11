"""Reading rows out of Supabase without losing any.

PostgREST caps **every** response at ~1000 rows regardless of the range you ask
for, and separately caps the URL length of an `in_()` list. Both truncate
silently: you get rows back, just not all of them. This is the most-repeated
bug in the codebase — the channel dashboard was showing 1000 of 5186 videos,
`refresh_stats` was refreshing the first 1000 and no more, and the performance
page was hiding 36% of its audits.

The knowledge used to live in `fetch_all`'s docstring with four consumers,
while eight other call sites re-derived the same loop under four different
names (`PAGE`, `ROW_PAGE`, `METRIC_ROW_PAGE`, a bare `999`) and five more
never paged at all.

Two functions, so neither cap has to be remembered:

    all_rows(query)                 -- every row matching a query
    rows_for_ids(build, ids)        -- every row for a list of ids

An unpaged read is still available — it is just spelled `.limit(n).execute()`,
which says out loud that the result is bounded.
"""
from __future__ import annotations

from typing import Callable

#: PostgREST's per-response row cap. Requesting a wider range does not raise;
#: it returns the first PAGE_SIZE rows.
PAGE_SIZE = 1000

#: Ids per `in_()` call, bounded so the query string stays far from any
#: URL-length limit. This alone does NOT bound the response: one id can match
#: many rows (a video has many audits), so each chunk is still paged.
IN_CHUNK = 500

#: Column appended as the last sort key so paging is deterministic. Every table
#: these helpers read has an `id` primary key except reporting_reports_ingested,
#: which passes order_by="report_id".
#:
#: WHY this is not optional: OFFSET paging assumes every page sees the same row
#: order, and a query with no ORDER BY makes no such promise. Postgres runs with
#: synchronize_seqscans=on, so a sequential scan JOINS an already-running scan of
#: the same table at its current position instead of starting at the beginning.
#: Each page is a separate statement, so the pages get differently-rotated row
#: orders and OFFSET then skips some rows and repeats others. Measured on the
#: dashboard's parallel read of `videos`: 49,144 rows returned, ~31,000 distinct
#: — and a different ~18,000 lost on every run. The row count still looked right,
#: which is why nothing caught it.
ORDER_KEY = "id"


def all_rows(query, page_size: int = PAGE_SIZE, *, order_by: str = ORDER_KEY) -> list:
    """Execute `query`, paging until the rows run out.

    `query` is an unexecuted postgrest builder; `.range()` is applied here, so
    do not set it yourself. A `.limit()` already on the query wins over paging
    and makes this equivalent to a single bounded read.

    `order_by` is appended as the final sort key (see ORDER_KEY). Any `.order()`
    the caller already set still sorts first; this only breaks ties, which is
    what makes the paging deterministic.
    """
    query = query.order(order_by)
    rows: list = []
    offset = 0
    while True:
        chunk = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return rows


def all_rows_parallel(build_query: Callable[..., object], *,
                      page_size: int = PAGE_SIZE, max_workers: int = 5,
                      order_by: str = ORDER_KEY) -> list:
    """`all_rows`, but fetching the pages concurrently.

    Costs one extra `count="exact"` on the first request to learn the total,
    then fetches the remaining pages in parallel. Worth it only for a large
    table on a latency-sensitive path — the dashboard reads the whole `videos`
    table (~20 pages) on every load. Prefer `all_rows` everywhere else: it
    issues no COUNT and no threads.

    Safe because supabase clients are per-thread (see app/db.py), so each
    worker gets its own hardened client.

    `build_query` is called with the keyword arguments for `.select()`:

        all_rows_parallel(lambda **kw: supabase().table("videos").select(COLS, **kw))
    """
    from concurrent.futures import ThreadPoolExecutor

    # Ordering matters more here than in all_rows: the pages are fetched over
    # DIFFERENT connections, so without a total order they are guaranteed to see
    # different scan positions rather than merely allowed to.
    first = build_query(count="exact").order(order_by).range(0, page_size - 1).execute()
    rows: list = list(first.data or [])
    total = first.count if first.count is not None else len(rows)
    if total <= page_size:
        return rows

    offsets = list(range(page_size, total, page_size))

    def _page(off: int) -> list:
        return (build_query().order(order_by)
                .range(off, off + page_size - 1).execute().data or [])

    with ThreadPoolExecutor(max_workers=min(max_workers, len(offsets))) as ex:
        for page in ex.map(_page, offsets):
            rows.extend(page)
    return rows


def rows_for_ids(build_query: Callable[[list], object], ids, chunk: int = IN_CHUNK,
                 *, order_by: str = ORDER_KEY) -> list:
    """Every row for `ids`, fetched in bounded `in_()` chunks.

    `build_query` receives one chunk of ids and returns an unexecuted builder:

        rows_for_ids(
            lambda c: supabase().table("videos").select("id,title").in_("id", c),
            video_ids,
        )

    Each chunk is itself paged: chunking bounds the *query string*, not the
    response, and one id can match many rows (a video has many audits), so a
    single chunk can still exceed PAGE_SIZE.

    Returns [] for an empty id list without issuing a query — the caller does
    not have to guard for it. Order across chunks is not meaningful; sort or
    index the result if you need one.
    """
    ids = list(ids)
    if not ids:
        return []
    out: list = []
    for i in range(0, len(ids), chunk):
        out.extend(all_rows(build_query(ids[i:i + chunk]), order_by=order_by))
    return out
