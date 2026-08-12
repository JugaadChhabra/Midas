"""The double is test infrastructure, so a bug in it weakens everything above it.

Two things get pinned here. First, that it behaves like postgrest on the parts
this codebase uses — filters, ordering, inclusive ranges. Second, and more
importantly, that it FAILS where a MagicMock chain would silently succeed: an
unstubbed table raises rather than answering "no rows".
"""
import pytest

from app.rows import all_rows, PAGE_SIZE
from tests.fakes import FakeSupabase, UnstubbedTable


def _sb(**tables):
    return FakeSupabase(tables)


# ── the whole point ───────────────────────────────────────────────────────

def test_an_unstubbed_table_raises_rather_than_answering_empty():
    sb = _sb(channels=[{"id": "c1"}])
    with pytest.raises(UnstubbedTable, match="videos"):
        sb.table("videos").select("id").execute()


def test_the_error_says_what_was_described():
    sb = _sb(channels=[], audits=[])
    with pytest.raises(UnstubbedTable, match=r"audits.*channels|channels.*audits"):
        sb.table("nope").select("*").execute()


def test_an_unstubbed_rpc_raises_too():
    sb = _sb(channels=[])
    with pytest.raises(UnstubbedTable, match="dashboard_summary"):
        sb.rpc("dashboard_summary", {}).execute()


def test_an_extra_filter_narrows_the_result_instead_of_bypassing_the_stub():
    """The MagicMock failure mode, inverted. Adding a filter a test did not
    anticipate changes WHICH rows come back — it does not silently return none.
    """
    sb = _sb(channels=[{"id": "c1", "on": True}, {"id": "c2", "on": False}])
    got = sb.table("channels").select("id").eq("on", True).order("id").execute().data
    assert got == [{"id": "c1"}]


# ── filters ───────────────────────────────────────────────────────────────

ROWS = [
    {"id": 1, "name": "a", "n": 10, "flag": True, "opt": None},
    {"id": 2, "name": "b", "n": 20, "flag": False, "opt": "x"},
    {"id": 3, "name": "c", "n": 30, "flag": True, "opt": None},
]


def _ids(result):
    return [r["id"] for r in result.data]


def test_eq_and_neq():
    sb = _sb(t=ROWS)
    assert _ids(sb.table("t").select("*").eq("flag", True).execute()) == [1, 3]
    assert _ids(sb.table("t").select("*").neq("flag", True).execute()) == [2]


def test_comparisons():
    sb = _sb(t=ROWS)
    assert _ids(sb.table("t").select("*").gt("n", 10).execute()) == [2, 3]
    assert _ids(sb.table("t").select("*").gte("n", 20).execute()) == [2, 3]
    assert _ids(sb.table("t").select("*").lt("n", 30).execute()) == [1, 2]
    assert _ids(sb.table("t").select("*").lte("n", 10).execute()) == [1]


def test_a_null_never_satisfies_a_comparison():
    """Matching SQL: NULL > 5 is not true. Comparing None to an int in Python
    would raise, which would be a false failure rather than a false pass."""
    sb = _sb(t=[{"id": 1, "n": None}])
    assert _ids(sb.table("t").select("*").gt("n", 5).execute()) == []


def test_in_and_is_null():
    sb = _sb(t=ROWS)
    assert _ids(sb.table("t").select("*").in_("id", [1, 3]).execute()) == [1, 3]
    assert _ids(sb.table("t").select("*").is_("opt", "null").execute()) == [1, 3]


def test_or_matches_any_term():
    sb = _sb(t=[
        {"id": 1, "a": True, "b": False},
        {"id": 2, "a": False, "b": True},
        {"id": 3, "a": False, "b": False},
    ])
    got = sb.table("t").select("*").or_("a.eq.true,b.eq.true").execute()
    assert _ids(got) == [1, 2]


def test_or_rejects_syntax_it_does_not_model():
    """Better an explicit NotImplementedError than a filter that quietly does
    nothing — which is the class of bug this double exists to remove."""
    sb = _sb(t=ROWS)
    with pytest.raises(NotImplementedError):
        sb.table("t").select("*").or_("n.gt.5")


def test_filters_compose():
    sb = _sb(t=ROWS)
    got = sb.table("t").select("*").eq("flag", True).gt("n", 10).execute()
    assert _ids(got) == [3]


# ── shaping ───────────────────────────────────────────────────────────────

def test_order_ascending_puts_nulls_last_like_postgres():
    sb = _sb(t=[{"id": 1, "v": None}, {"id": 2, "v": "a"}, {"id": 3, "v": "b"}])
    assert _ids(sb.table("t").select("*").order("v").execute()) == [2, 3, 1]


def test_order_descending_puts_nulls_first_like_postgres():
    sb = _sb(t=[{"id": 1, "v": None}, {"id": 2, "v": "a"}, {"id": 3, "v": "b"}])
    assert _ids(sb.table("t").select("*").order("v", desc=True).execute()) == [1, 3, 2]


def test_range_is_inclusive_at_both_ends():
    """all_rows asks for range(offset, offset + page_size - 1) and expects a full
    page; exclusive ends would silently drop a row per page."""
    sb = _sb(t=[{"id": i} for i in range(10)])
    assert _ids(sb.table("t").select("*").order("id").range(0, 2).execute()) == [0, 1, 2]
    assert _ids(sb.table("t").select("*").order("id").range(3, 4).execute()) == [3, 4]


def test_limit_truncates():
    sb = _sb(t=ROWS)
    assert len(sb.table("t").select("*").limit(2).execute().data) == 2


def test_single_returns_a_row_not_a_list():
    sb = _sb(t=ROWS)
    assert sb.table("t").select("*").eq("id", 2).single().execute().data["name"] == "b"


def test_single_on_no_rows_is_none():
    """A documented divergence: real postgrest raises PGRST116 here. The app reads
    `.single().execute().data` and tests it for falsy, so None is the shape it is
    written against — but that error path cannot be proven with this double."""
    sb = _sb(t=ROWS)
    assert sb.table("t").select("*").eq("id", 99).single().execute().data is None


def test_count_exact_reports_the_pre_range_total():
    """all_rows_parallel needs the total, not the page length."""
    sb = _sb(t=[{"id": i} for i in range(7)])
    res = sb.table("t").select("*", count="exact").order("id").range(0, 1).execute()
    assert len(res.data) == 2
    assert res.count == 7


def test_select_projects_to_the_named_columns():
    """Modelled because forgetting it is a bug this repo has already had: a
    predicate filtered on a column the query never selected, matched nothing, and
    the job went quiet. A double returning every column would hide it."""
    sb = _sb(t=[{"id": 1, "name": "a", "secret": "s"}])
    assert sb.table("t").select("id,name").execute().data == [{"id": 1, "name": "a"}]


def test_select_star_returns_everything():
    sb = _sb(t=[{"id": 1, "name": "a"}])
    assert sb.table("t").select("*").execute().data == [{"id": 1, "name": "a"}]


def test_an_embedded_resource_is_passed_through_not_joined():
    """This double has no relationships. The test supplies the joined shape and
    the double preserves it, which is enough for channel-scoped queries."""
    sb = _sb(audits=[{"id": 1, "videos": {"channel_id": "c1"}}])
    got = sb.table("audits").select("id,videos!inner(channel_id)").execute().data
    assert got == [{"id": 1, "videos": {"channel_id": "c1"}}]


def test_a_projected_column_the_row_lacks_is_simply_absent():
    sb = _sb(t=[{"id": 1}])
    assert sb.table("t").select("id,missing").execute().data == [{"id": 1}]


def test_rows_are_copies_so_a_caller_cannot_mutate_the_store():
    sb = _sb(t=[{"id": 1, "n": 10}])
    got = sb.table("t").select("*").execute().data
    got[0]["n"] = 999
    assert sb.rows("t")[0]["n"] == 10


# ── writes ────────────────────────────────────────────────────────────────

def test_insert_records_and_lands():
    sb = _sb(t=[])
    sb.table("t").insert({"id": 1}).execute()
    assert sb.writes == [("t", "insert", {"id": 1})]
    assert sb.rows("t") == [{"id": 1}]


def test_update_applies_to_the_filtered_rows_only():
    sb = _sb(t=[{"id": 1, "s": "a"}, {"id": 2, "s": "a"}])
    sb.table("t").update({"s": "b"}).eq("id", 1).execute()
    assert sb.rows("t") == [{"id": 1, "s": "b"}, {"id": 2, "s": "a"}]


def test_upsert_replaces_on_the_conflict_key():
    sb = _sb(t=[{"id": 1, "n": 1}])
    sb.table("t").upsert({"id": 1, "n": 2}, on_conflict="id").execute()
    assert sb.rows("t") == [{"id": 1, "n": 2}]


def test_upsert_inserts_when_nothing_conflicts():
    sb = _sb(t=[{"id": 1, "n": 1}])
    sb.table("t").upsert({"id": 2, "n": 5}, on_conflict="id").execute()
    assert len(sb.rows("t")) == 2


def test_upsert_honours_a_composite_conflict_key():
    sb = _sb(t=[{"v": "x", "start": "d1", "n": 1}])
    sb.table("t").upsert({"v": "x", "start": "d1", "n": 9},
                         on_conflict="v,start").execute()
    assert sb.rows("t") == [{"v": "x", "start": "d1", "n": 9}]


def test_delete_removes_the_filtered_rows():
    sb = _sb(t=[{"id": 1}, {"id": 2}])
    sb.table("t").delete().eq("id", 1).execute()
    assert sb.rows("t") == [{"id": 2}]


def test_writes_are_recorded_in_order():
    sb = _sb(t=[{"id": 1}])
    sb.table("t").update({"a": 1}).eq("id", 1).execute()
    sb.table("t").insert({"id": 2}).execute()
    assert [(w[0], w[1]) for w in sb.writes] == [("t", "update"), ("t", "insert")]


# ── it survives the real paging code ──────────────────────────────────────

def test_all_rows_pages_through_the_double():
    """The seam that mattered: all_rows appends its own .order() and walks with
    .range(). A hand-built chain that missed either hop returned an empty
    MagicMock and passed. Here the paging genuinely runs."""
    sb = _sb(t=[{"id": i} for i in range(PAGE_SIZE + 250)])
    got = all_rows(sb.table("t").select("id"))
    assert len(got) == PAGE_SIZE + 250
    assert [r["id"] for r in got] == list(range(PAGE_SIZE + 250))


def test_all_rows_returns_distinct_rows_across_pages():
    """The bug OFFSET paging actually had in this repo: without a total order a
    full walk returned more rows than distinct ids."""
    sb = _sb(t=[{"id": i, "grp": i % 3} for i in range(PAGE_SIZE + 10)])
    got = all_rows(sb.table("t").select("id,grp"))
    assert len({r["id"] for r in got}) == len(got)


def test_a_filtered_paged_read_still_filters():
    sb = _sb(t=[{"id": i, "keep": i % 2 == 0} for i in range(PAGE_SIZE + 100)])
    got = all_rows(sb.table("t").select("id").eq("keep", True))
    assert len(got) == (PAGE_SIZE + 100) // 2
