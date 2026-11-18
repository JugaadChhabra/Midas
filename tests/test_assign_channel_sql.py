"""The assign_channel() SQL function must close the open row and open the new one
in one transaction (team tracker 08, #149).

The HTTP tests stub the RPC in FakeSupabase (tests/test_team_assignments.py), so
nothing offline runs this SQL. This is the offline guard, in the style of
tests/test_dashboard_summary_baseline_sql.py: it reads whichever migration most
recently defines the function and asserts the properties the API relies on, so
someone redefining it by copying a draft can't silently drop one:

  * one plpgsql function body (a function call is one transaction under
    PostgREST), not separate statements the client would have to sequence;
  * the open row is locked (`for update`) and closed at the new start before
    the new row is inserted, so the partial unique index never sees two open
    rows and no day is credited twice or to nobody;
  * a start before the open row's start is refused (no back-dating in v1);
  * execute is revoked from public and granted to service_role, like the other
    functions.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
SIGNATURE = "assign_channel(text, bigint, date, bigint)"


def _sql(pattern: str) -> list[tuple[str, str]]:
    return sorted((p.name, p.read_text()) for p in MIGRATIONS.glob("*.sql")
                  if re.search(pattern, p.read_text(), re.I))


def _latest_definition() -> tuple[str, str]:
    """(filename, function body) of the newest migration defining assign_channel()."""
    defining = _sql(r"create or replace function assign_channel\b")
    assert defining, "no migration defines assign_channel()"
    name, sql = defining[-1]       # timestamp-prefixed, so lexical == chronological
    m = re.search(r"create or replace function assign_channel\b(.*?)\$\$;", sql, re.S | re.I)
    assert m, f"{name}: assign_channel() has no $$-quoted body"
    return name, m.group(1)


def _code(body: str) -> str:
    """The body without `--` comments, lower-cased, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", body)).lower()


def test_the_function_is_one_plpgsql_body_with_the_four_parameters():
    name, body = _latest_definition()
    code = _code(body)
    assert "language plpgsql" in code, f"{name}: assign_channel() must be plpgsql"
    for param in ("p_channel_id text", "p_team_member_id bigint",
                  "p_starts_on date", "p_assigned_by bigint"):
        assert param in code, f"{name}: assign_channel() lacks parameter {param!r}"
    assert "security definer" not in code, (
        f"{name}: assign_channel() runs as its caller (service_role); a security "
        f"definer function would bypass the grants for no reason.")


def test_the_open_row_is_locked_then_closed_before_the_new_row_is_inserted():
    name, body = _latest_definition()
    code = _code(body)

    lock = re.search(r"where channel_id = p_channel_id and ends_on is null for update", code)
    close = re.search(r"update channel_assignments set ends_on = p_starts_on", code)
    insert = re.search(r"insert into channel_assignments", code)
    assert lock, f"{name}: the open row isn't selected `for update`"
    assert close, f"{name}: the open row isn't closed at the new start (ends_on = p_starts_on)"
    assert insert, f"{name}: no new row is inserted"
    assert lock.start() < close.start() < insert.start(), (
        f"{name}: lock, close and insert must run in that order; inserting first "
        f"trips the one-open-row index (or, without it, opens two rows).")


def test_a_start_before_the_open_rows_start_raises():
    name, body = _latest_definition()
    code = _code(body)
    assert re.search(r"if p_starts_on < v_open\.starts_on then raise exception", code), (
        f"{name}: assign_channel() must refuse a start before the open row's start, "
        f"else the closed row gets ends_on < starts_on and ranges overlap.")


def test_execute_is_granted_to_service_role_only():
    name, sql = _sql(r"create or replace function assign_channel\b")[-1]
    flat = re.sub(r"\s+", " ", sql).lower()
    assert f"revoke execute on function {SIGNATURE} from public" in flat, name
    assert f"grant execute on function {SIGNATURE} to service_role" in flat, name


def test_one_open_assignment_per_channel_is_an_index():
    found = _sql(r"on channel_assignments \(channel_id\)\s+where ends_on is null")
    assert found, "no partial unique index keeps one open assignment per channel"
    name, sql = found[-1]
    assert re.search(r"create unique index[^;]*on channel_assignments \(channel_id\)\s+"
                     r"where ends_on is null", sql, re.I), name
