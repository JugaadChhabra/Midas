"""An in-memory stand-in for the postgrest client, for tests.

Why this exists, given the 2026-07-22 review deliberately rejected a fakeable
data layer in favour of live tests: this is not that. There is no port in front
of Postgres and no second production adapter. This is a double for the query
BUILDER the tests were already imitating by hand, 140 chains of it, and the live
read-only tests are untouched.

The problem it solves is that a MagicMock chain fails in the wrong direction.
Configure `.select().eq().execute()` and let production add one `.order()`, and
the stub is bypassed: `.data` becomes a fresh MagicMock, `list()` of which is
empty, so the test keeps passing while asserting on zero rows. Four instances of
exactly that turned up in three days —

  * six tests that patched a module whose query had moved, reached the real
    database, and hung the suite instead of failing it;
  * a stub missing the `.order()` hop that `all_rows` appends, which let three
    assertions pass while reading nothing;
  * two source-scan guards that matched none of the code they were written to
    catch.

So: describe the ROWS, not the call sequence. Filters are interpreted, paging is
real, and an unstubbed table raises instead of quietly answering "no rows".

    sb = FakeSupabase({"channels": [{"id": "c1", "autopilot_enabled": True}]})
    with patch.object(mod, "supabase", return_value=sb):
        ...
    assert sb.writes == [("channels", "update", {...})]

Known divergences from the real client, deliberate:

  * `.single()` returns None on no rows; real postgrest raises PGRST116. The app
    reads `.single().execute().data` and checks for falsy, so None is the shape
    it is written against — but a test cannot use this double to prove behaviour
    on that error path.
  * No RLS, no embedded-resource joins (`videos!inner(...)`) beyond passing the
    column string through, and no type coercion: a filter value is compared to
    the stored value with `==`.
  * Ordering follows Postgres defaults — NULLs last ascending, first descending —
    because `all_rows` depends on a total order to page correctly.
"""

from __future__ import annotations

import re


class UnstubbedTable(AssertionError):
    """A query hit a table the test did not describe.

    Loud on purpose: answering "no rows" is what makes a mock-chain test pass
    while reading nothing.
    """


class Result:
    """What postgrest's execute() returns, as far as this codebase cares."""

    def __init__(self, data, count=None):
        self.data = data
        self.count = count


def _split_columns(spec: str) -> list[str]:
    """Split a postgrest select spec on top-level commas.

    `id,videos!inner(channel_id)` is two terms, not three — the comma inside the
    embedded resource belongs to it.
    """
    terms, depth, current = [], 0, ""
    for ch in spec:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            terms.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        terms.append(current.strip())
    return terms


def _projection(spec: str) -> list[str] | None:
    """Keys a select spec asks for, or None for everything.

    Projection is modelled because forgetting it is a real bug this codebase has
    already hit: a predicate filtered on a column the query never selected, so it
    matched nothing and the job went silently quiet. A double that returned every
    column regardless would hide exactly that.

    An embedded resource (`videos!inner(channel_id)`) is not joined — this double
    has no relationships. Its key is passed through instead, so a test can attach
    the joined shape to its fixture row and assert on it.
    """
    if spec.strip() == "*":
        return None
    keys = []
    for term in _split_columns(spec):
        base = term.split("(", 1)[0].split("!", 1)[0].strip()
        if base:
            keys.append(base)
    return keys


def _sort_key(column: str, desc: bool):
    # Postgres orders NULLs last ascending and first descending; all_rows relies
    # on a total order, so this has to match rather than approximate.
    def key(row):
        v = row.get(column)
        return (v is None, v) if not desc else (v is None, v)
    return key


class FakeQuery:
    """One query under construction. Filters accumulate; execute() applies them."""

    _OR_TERM = re.compile(r"^(?P<col>[\w.]+)\.(?P<op>eq)\.(?P<val>.+)$")

    def __init__(self, table: str, rows: list[dict], writes: list, columns: str = "*"):
        self._table = table
        self._rows = rows
        self._writes = writes
        self._columns = columns
        self._filters: list = []
        self._or_groups: list[list[tuple[str, object]]] = []
        self._order: list[tuple[str, bool]] = []
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None
        self._one = False
        self._count = None
        self._write: tuple[str, object] | None = None

    # ── filters ───────────────────────────────────────────────────────────
    def eq(self, column, value):
        self._filters.append(lambda r: r.get(column) == value)
        return self

    def neq(self, column, value):
        self._filters.append(lambda r: r.get(column) != value)
        return self

    def gt(self, column, value):
        self._filters.append(lambda r: r.get(column) is not None and r[column] > value)
        return self

    def gte(self, column, value):
        self._filters.append(lambda r: r.get(column) is not None and r[column] >= value)
        return self

    def lt(self, column, value):
        self._filters.append(lambda r: r.get(column) is not None and r[column] < value)
        return self

    def lte(self, column, value):
        self._filters.append(lambda r: r.get(column) is not None and r[column] <= value)
        return self

    def in_(self, column, values):
        allowed = list(values)
        self._filters.append(lambda r: r.get(column) in allowed)
        return self

    def is_(self, column, value):
        # PostgREST spells NULL checks as .is_("col", "null").
        want_null = value in ("null", None)
        self._filters.append(
            lambda r: (r.get(column) is None) if want_null else (r.get(column) is value))
        return self

    def not_(self, *_a, **_kw):
        raise NotImplementedError(
            "FakeQuery does not model .not_() yet — add it here rather than "
            "reaching for a MagicMock, or the next reader will not know it is "
            "unsupported")

    def or_(self, expression: str):
        """PostgREST's `or=(col.eq.x,col2.eq.y)`, as used by this codebase."""
        group = []
        for term in expression.split(","):
            m = self._OR_TERM.match(term.strip())
            if not m:
                raise NotImplementedError(
                    f"FakeQuery.or_ only models `col.eq.value` terms; got {term!r}")
            val = m["val"]
            val = True if val == "true" else False if val == "false" else val
            group.append((m["col"], val))
        self._or_groups.append(group)
        return self

    # ── shaping ───────────────────────────────────────────────────────────
    def order(self, column, desc=False, **_kw):
        self._order.append((column, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)     # inclusive both ends, like PostgREST
        return self

    def single(self):
        self._one = True
        return self

    def maybe_single(self):
        self._one = True
        return self

    # ── writes ────────────────────────────────────────────────────────────
    def insert(self, payload, **_kw):
        self._write = ("insert", payload)
        return self

    def upsert(self, payload, **kw):
        self._write = ("upsert", payload)
        self._upsert_on = kw.get("on_conflict")
        return self

    def update(self, payload, **_kw):
        self._write = ("update", payload)
        return self

    def delete(self, **_kw):
        self._write = ("delete", None)
        return self

    # ── execution ─────────────────────────────────────────────────────────
    def _matching(self) -> list[dict]:
        rows = self._rows
        for f in self._filters:
            rows = [r for r in rows if f(r)]
        for group in self._or_groups:
            rows = [r for r in rows
                    if any(r.get(col) == val for col, val in group)]
        for column, desc in reversed(self._order):
            rows = sorted(rows, key=_sort_key(column, desc), reverse=desc)
        return rows

    def execute(self):
        if self._write is not None:
            return self._execute_write()

        rows = self._matching()
        total = len(rows)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        if self._limit is not None:
            rows = rows[:self._limit]
        keys = _projection(self._columns)
        shaped = [self._project(r, keys) for r in rows]
        if self._one:
            return Result(shaped[0] if shaped else None)
        return Result(shaped, count=total if self._count == "exact" else None)

    @staticmethod
    def _project(row: dict, keys: list[str] | None) -> dict:
        if keys is None:
            return dict(row)
        return {k: row[k] for k in keys if k in row}

    def _execute_write(self):
        op, payload = self._write
        self._writes.append((self._table, op, payload))
        if op == "delete":
            for r in self._matching():
                self._rows.remove(r)
            return Result([])
        if op == "update":
            touched = self._matching()
            for r in touched:
                r.update(payload)
            return Result([dict(r) for r in touched])
        items = payload if isinstance(payload, list) else [payload]
        if op == "upsert":
            keys = [k.strip() for k in (self._upsert_on or "id").split(",")]
            for item in items:
                match = next(
                    (r for r in self._rows
                     if all(r.get(k) == item.get(k) for k in keys)), None)
                if match is not None:
                    match.update(item)
                else:
                    self._rows.append(dict(item))
        else:
            self._rows.extend(dict(i) for i in items)
        return Result([dict(i) for i in items])


class FakeTable:
    def __init__(self, name, rows, writes):
        self._name, self._rows, self._writes = name, rows, writes

    def select(self, columns="*", count=None, **_kw):
        q = FakeQuery(self._name, self._rows, self._writes, columns)
        q._count = count
        return q

    def insert(self, payload, **kw):
        return FakeQuery(self._name, self._rows, self._writes).insert(payload, **kw)

    def upsert(self, payload, **kw):
        return FakeQuery(self._name, self._rows, self._writes).upsert(payload, **kw)

    def update(self, payload, **kw):
        return FakeQuery(self._name, self._rows, self._writes).update(payload, **kw)

    def delete(self, **kw):
        return FakeQuery(self._name, self._rows, self._writes).delete(**kw)


class FakeSupabase:
    """Stands in for `app.db.supabase()`'s return value.

    `tables` maps table name to its rows. A query against any other table raises
    UnstubbedTable — the point of the whole exercise.
    """

    def __init__(self, tables: dict[str, list[dict]] | None = None,
                 rpc: dict[str, object] | None = None):
        self._tables = {name: [dict(r) for r in rows]
                        for name, rows in (tables or {}).items()}
        self._rpc = rpc or {}
        #: (table, op, payload) per write, in order.
        self.writes: list[tuple[str, str, object]] = []
        #: (name, params) per rpc call, in order.
        self.rpc_calls: list[tuple[str, object]] = []

    def table(self, name: str) -> FakeTable:
        if name not in self._tables:
            raise UnstubbedTable(
                f"query against unstubbed table {name!r}; tables described: "
                f"{sorted(self._tables)}. Add it to FakeSupabase(...) — an "
                f"empty answer here is how a test passes while reading nothing.")
        return FakeTable(name, self._tables[name], self.writes)

    def rpc(self, name: str, params=None):
        self.rpc_calls.append((name, params))
        if name not in self._rpc:
            raise UnstubbedTable(
                f"call to unstubbed rpc {name!r}; rpcs described: {sorted(self._rpc)}")
        result = self._rpc[name]
        data = result(params) if callable(result) else result
        return _Executed(data)

    def rows(self, table: str) -> list[dict]:
        """The current contents of a table — for asserting the effect of writes."""
        return [dict(r) for r in self._tables[table]]


class _Executed:
    """rpc() returns something already executable; .execute() just unwraps it."""

    def __init__(self, data):
        self._data = data

    def execute(self):
        return Result(self._data)
