"""The 1000-row cap is handled once, and no module re-solves it.

Supabase truncates every response at ~1000 rows and separately caps the URL
length of an in_() list. Both fail silently. Before app/rows.py the knowledge
lived in one docstring with four consumers while eight other sites re-derived
the loop under four different names and five more never paged at all — the
channel dashboard showed 1000 of 5186 videos.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.rows import IN_CHUNK, ORDER_KEY, PAGE_SIZE, all_rows, rows_for_ids

APP = Path(__file__).resolve().parents[1] / "app"


class _Query:
    """A postgrest builder stub that serves `total` rows through .range()."""

    def __init__(self, total, page_size=PAGE_SIZE):
        self.total = total
        self.page_size = page_size
        self.ranges: list[tuple[int, int]] = []
        self.orders: list[str] = []

    def order(self, column, **kw):
        self.orders.append(column)
        return self

    def range(self, lo, hi):
        self.ranges.append((lo, hi))
        served = [{"i": n} for n in range(lo, min(hi + 1, self.total))]
        # A real server never returns more than page_size in one response.
        self._served = served[: self.page_size]
        return self

    def execute(self):
        r = MagicMock()
        r.data = self._served
        return r


# ── all_rows ──────────────────────────────────────────────────────────────

def test_returns_everything_past_the_cap():
    q = _Query(2500)
    assert len(all_rows(q)) == 2500


def test_pages_in_page_size_steps():
    q = _Query(2500)
    all_rows(q)
    assert q.ranges == [(0, 999), (1000, 1999), (2000, 2999)]


def test_a_short_page_ends_the_walk():
    q = _Query(10)
    assert len(all_rows(q)) == 10
    assert len(q.ranges) == 1        # no speculative extra round-trip


def test_exactly_one_full_page_probes_once_more():
    """A full page is indistinguishable from a truncated one — must re-ask."""
    q = _Query(PAGE_SIZE)
    assert len(all_rows(q)) == PAGE_SIZE
    assert len(q.ranges) == 2


def test_empty_result():
    q = _Query(0)
    assert all_rows(q) == []


def test_none_data_is_treated_as_empty():
    q = MagicMock()
    q.order.return_value.range.return_value.execute.return_value.data = None
    assert all_rows(q) == []


# ── deterministic paging ──────────────────────────────────────────────────

def test_paging_appends_a_total_order():
    """OFFSET paging assumes every page sees the same row order, and a query
    with no ORDER BY promises nothing. Postgres runs synchronize_seqscans=on, so
    a scan joins an already-running scan of the same table mid-way; consecutive
    pages then get differently-rotated orders and OFFSET skips and repeats rows.
    Measured on the dashboard's read of `videos`: 49,144 rows, ~31k distinct."""
    q = _Query(2500)
    all_rows(q)
    assert q.orders == [ORDER_KEY]


def test_the_order_key_is_overridable():
    """reporting_reports_ingested is keyed by report_id, not id."""
    q = _Query(10)
    all_rows(q, order_by="report_id")
    assert q.orders == ["report_id"]


def test_the_order_key_is_appended_not_substituted():
    """A caller's own .order() must still sort first — this only breaks ties."""
    q = _Query(10).order("created_at", desc=True)
    all_rows(q)
    assert q.orders == ["created_at", ORDER_KEY]


# ── rows_for_ids ──────────────────────────────────────────────────────────

def test_chunks_the_id_list():
    seen = []

    def build(chunk):
        seen.append(list(chunk))
        b = MagicMock()
        b.order.return_value.range.return_value.execute.return_value.data = [
            {"id": i} for i in chunk
        ]
        return b

    out = rows_for_ids(build, [f"v{n}" for n in range(1200)])
    assert len(out) == 1200
    assert [len(c) for c in seen] == [IN_CHUNK, IN_CHUNK, 200]


def test_each_chunk_is_itself_paged():
    """Chunking bounds the query string, not the response: one id can match
    many rows (a video has many audits), so a chunk can still exceed the cap."""
    def build(chunk):
        return _Query(2500)      # one chunk, 2500 matching rows

    out = rows_for_ids(build, ["v1", "v2"])
    assert len(out) == 2500


def test_empty_ids_issues_no_query():
    build = MagicMock()
    assert rows_for_ids(build, []) == []
    build.assert_not_called()


def test_chunk_size_is_bounded():
    """Bounds the query string. The response is bounded by paging, not by this."""
    assert 0 < IN_CHUNK <= PAGE_SIZE


# ── nobody re-solves it ───────────────────────────────────────────────────

_LOCAL_PAGE_CONST = re.compile(r"^\s*(?:PAGE|ROW_PAGE|METRIC_ROW_PAGE)\s*=\s*\d{3,}", re.M)
_HAND_ROLLED_RANGE = re.compile(r"\.range\(\s*offset\s*,\s*offset\s*\+")


def _app_sources():
    for p in sorted(APP.rglob("*.py")):
        if p.name == "rows.py" or "shorts" in p.parts:
            continue
        yield p


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_declares_its_own_paging_constant(path):
    hits = _LOCAL_PAGE_CONST.findall(path.read_text())
    assert not hits, (
        f"{path.name} declares its own page size {hits} — use app.rows.all_rows "
        "so the cap is handled in one place"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_hand_rolls_the_paging_loop(path):
    assert not _HAND_ROLLED_RANGE.search(path.read_text()), (
        f"{path.name} hand-rolls the offset/range paging loop — use "
        "app.rows.all_rows"
    )


# ── all_rows_parallel ─────────────────────────────────────────────────────

def test_parallel_fetches_every_page():
    from app.rows import all_rows_parallel
    TOTAL = 4500

    def build(**kw):
        q = _Query(TOTAL)
        q._count = TOTAL if kw.get("count") == "exact" else None
        orig = q.execute

        def execute():
            r = orig()
            r.count = q._count
            return r
        q.execute = execute
        return q

    assert len(all_rows_parallel(build)) == TOTAL


def test_parallel_single_page_skips_the_fan_out():
    from app.rows import all_rows_parallel
    calls = []

    def build(**kw):
        calls.append(kw)
        q = _Query(10)
        orig = q.execute

        def execute():
            r = orig()
            r.count = 10
            return r
        q.execute = execute
        return q

    assert len(all_rows_parallel(build)) == 10
    assert calls == [{"count": "exact"}]     # no extra requests
