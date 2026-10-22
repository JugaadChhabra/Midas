"""Phase B · B4 — warm_pool() (SQL) and app/warm.py (in-app) agree (#35);
Slice 1 · S1.4a adds the cooldown and once-per-experiment exclusions (#63).

The existing RPCs prove parity only live (test_autopilot_picker_parity_live.py),
which skips without credentials. This one runs the migration's function on a
throwaway local Postgres (initdb into a temp dir, Unix socket only, no TCP) and
the in-app twin on FakeSupabase, over the same rows, and compares. It touches
no real database. Skips if no Postgres server binaries are on PATH.

The tables are the subset of columns warm_pool() reads, typed as in the
migrations that create them. Both warm_pool() migrations run in order, so the
replacement's drop of the four-argument function is exercised too.
"""
from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app import warm
from tests.fakes import FakeSupabase

psycopg = pytest.importorskip("psycopg")

# A Unix socket to a server this test starts and stops.
pytestmark = pytest.mark.needs_socket

REPO = Path(__file__).resolve().parents[1]
MIGRATIONS = [REPO / "supabase/migrations/20261006040000_warm_pool_rpc.sql",
              REPO / "supabase/migrations/20261023000000_warm_pool_agent_exclusions.sql"]

SCHEMA = """
create role service_role;
create table videos (
    id text primary key, channel_id text not null,
    privacy_status text, is_episode boolean
);
create table reporting_reports_ingested (
    report_id text primary key, channel_id text, data_date date,
    report_type text not null default 'channel_reach_basic_a1'
);
create table video_reach_daily (
    id bigserial primary key, video_id text not null, channel_id text,
    date date, impressions bigint not null, ctr double precision not null,
    unique (video_id, date)
);
create table interventions (
    id bigserial primary key, video_id text not null references videos(id),
    channel_id text not null, lever text not null, origin text not null,
    arm text not null, status text not null, created_at timestamptz default now()
);
"""

FRONTIER = date(2026, 10, 4)


def day(n: int) -> str:
    return (FRONTIER - timedelta(days=n)).isoformat()


def ago(days: float) -> str:
    """A created_at `days` before now: SQL's now() and the app's clock agree to
    well under the gaps the ages below leave around TRIAGE_COOLDOWN_DAYS (7)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def intervention(video_id, *, lever="title", origin="midas", arm="treated",
                 status="judged", age_days=365, channel="c1"):
    return {"video_id": video_id, "channel_id": channel, "lever": lever, "origin": origin,
            "arm": arm, "status": status, "created_at": ago(age_days)}


@pytest.fixture(scope="module")
def pg():
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not (initdb and pg_ctl):
        pytest.skip("no Postgres server binaries (initdb, pg_ctl) on PATH")
    # Short path: a Unix socket path is limited to ~104 bytes on macOS.
    root = Path(tempfile.mkdtemp(prefix="midas-pg-", dir="/tmp"))
    data = root / "data"
    try:
        subprocess.run([initdb, "-D", str(data), "-A", "trust", "-U", "postgres"],
                       check=True, capture_output=True)
        subprocess.run([pg_ctl, "-D", str(data), "-l", str(root / "log"), "-w",
                        "-o", f"-k {root} -c listen_addresses='' -F", "start"],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        shutil.rmtree(root, ignore_errors=True)
        pytest.skip(f"could not start a throwaway Postgres: {e.stderr.decode()[-300:]}")
    try:
        with psycopg.connect(host=str(root), user="postgres", dbname="postgres",
                             autocommit=True) as conn:
            conn.execute(SCHEMA)
            for migration in MIGRATIONS:
                conn.execute(migration.read_text())
            yield conn
    finally:
        subprocess.run([pg_ctl, "-D", str(data), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


_SERIAL = {"video_reach_daily", "interventions"}


def _load(conn, tables: dict[str, list[dict]]) -> None:
    conn.execute("truncate interventions, video_reach_daily, reporting_reports_ingested, videos")
    for name in ("videos", "reporting_reports_ingested", "video_reach_daily", "interventions"):
        for row in tables[name]:
            # bigserial ids are the database's; the fake's are only paging keys.
            cols = [c for c in row if not (c == "id" and name in _SERIAL)]
            conn.execute(
                f"insert into {name} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})",
                [row[c] for c in cols],
            )


def _sql_pool(conn, channel_id: str) -> list[dict]:
    p = warm._rpc_params(channel_id)
    cur = conn.execute("select id, impressions from warm_pool(%s, %s, %s, %s, %s)",
                       [p["p_channel_id"], p["p_min_impressions"], p["p_window_days"],
                        p["p_measurement_window_days"], p["p_cooldown_days"]])
    return [{"id": i, "impressions": n} for i, n in cur.fetchall()]


def _inapp_pool(tables: dict[str, list[dict]], channel_id: str) -> list[dict]:
    sb = FakeSupabase(tables)
    with patch.object(warm, "supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch.object(warm.settings, "WARM_POOL_USE_RPC", False):
        return warm.ranked_pool(channel_id)


def _assert_parity(conn, tables, channels=("c1", "c2")):
    _load(conn, tables)
    pools = {}
    for ch in channels:
        sql, inapp = _sql_pool(conn, ch), _inapp_pool(tables, ch)
        assert sql == inapp, f"warm pool drift on {ch}:\n  sql={sql}\n  inapp={inapp}"
        pools[ch] = sql
    return pools


def _random_world(seed: int) -> dict[str, list[dict]]:
    """Two channels, holes in the ledger, every exclusion, ties in impressions.
    c1 is always certified; c2 isn't for odd seeds."""
    rng = random.Random(seed)
    tables = {"videos": [], "reporting_reports_ingested": [],
              "video_reach_daily": [], "interventions": []}
    for ch in ("c1", "c2"):
        covered = set(range(21))                          # certified...
        covered |= {n for n in range(21, 60) if rng.random() < 0.6}
        if ch == "c2" and seed % 2:
            covered.discard(rng.randrange(1, 21))         # ...or, on c2 for odd seeds, not
        for n in sorted(covered):
            tables["reporting_reports_ingested"].append(
                {"report_id": f"{ch}-reach-{n}", "channel_id": ch, "data_date": day(n),
                 "report_type": "channel_reach_basic_a1"})
        for n in range(0, 60, 3):                         # traffic reports: never reach days
            tables["reporting_reports_ingested"].append(
                {"report_id": f"{ch}-traffic-{n}", "channel_id": ch, "data_date": day(n),
                 "report_type": "channel_traffic_source_a3"})
        for i in range(150):
            vid = f"{ch}-v{i:03d}"
            if rng.random() < 0.9:                        # some reach rows have no video
                tables["videos"].append({
                    "id": vid, "channel_id": ch,
                    "privacy_status": rng.choice(["public", "public", "public", None,
                                                  "private", "unlisted"]),
                    "is_episode": rng.choice([None, None, False, True]),
                })
                # Interventions of every lever, origin, arm, status and age, up
                # to three per video; ages stay clear of the 7-day cooldown edge.
                for _ in range(rng.choice([0, 0, 0, 1, 1, 2, 3])):
                    tables["interventions"].append(intervention(
                        vid, channel=ch,
                        lever=rng.choice(["backlinks", "playlist", "short_link", "title"]),
                        origin=rng.choice(["midas", "human"]),
                        arm=rng.choice(["treated", "holdout", "n/a"]),
                        status=rng.choice(["planned", "applied", "measuring", "holdout",
                                           "judged", "cancelled", "declined",
                                           "insufficient_data"]),
                        age_days=rng.choice([0.1, 1, 3, 6.5, 7.5, 8, 30, 400]),
                    ))
            for n in rng.sample(range(60), rng.randrange(0, 12)):
                if n in covered:                          # rows only land with a report
                    tables["video_reach_daily"].append({
                        "video_id": vid, "channel_id": ch, "date": day(n),
                        # Multiples of 50 make impression ties likely.
                        "impressions": 50 * rng.randrange(0, 8), "ctr": 0.04,
                    })
    for i, r in enumerate(tables["video_reach_daily"], 1):
        r["id"] = i
    for i, r in enumerate(tables["interventions"], 1):
        r["id"] = i
    return tables


@pytest.mark.parametrize("seed", range(8))
def test_sql_and_python_agree_on_random_worlds(pg, seed):
    tables = _random_world(seed)
    pools = _assert_parity(pg, tables)
    assert pools["c1"], "a certified channel with no warm video proves little"
    assert bool(pools["c2"]) is (seed % 2 == 0)
    # Every world has closed Midas rows that only S1.4a's rules count: recent
    # ones, and backlinks rows of either arm, old ones included.
    closed = [i for i in tables["interventions"] if i["origin"] == "midas"
              and i["status"] not in ("planned", "applied", "measuring", "holdout")]
    recent = datetime.now(timezone.utc) - timedelta(days=7)
    assert any(datetime.fromisoformat(i["created_at"]) > recent for i in closed)
    assert any(i["lever"] == "backlinks" and i["arm"] != "n/a"
               and datetime.fromisoformat(i["created_at"]) < recent for i in closed)


def test_sql_and_python_agree_on_an_ingested_window_with_a_hole(pg):
    covered = list(range(21)) + list(range(31, 39))
    tables = {
        "videos": [{"id": v, "channel_id": "c1", "privacy_status": "public", "is_episode": None}
                   for v in ("behind_the_hole", "29th_day")],
        "reporting_reports_ingested": [
            {"report_id": f"r{n}", "channel_id": "c1", "data_date": day(n),
             "report_type": "channel_reach_basic_a1"} for n in covered],
        "video_reach_daily": [
            {"id": 1, "video_id": "behind_the_hole", "channel_id": "c1", "date": day(37),
             "impressions": 600, "ctr": 0.05},
            {"id": 2, "video_id": "29th_day", "channel_id": "c1", "date": day(38),
             "impressions": 600, "ctr": 0.05},
        ],
        "interventions": [],
    }
    pools = _assert_parity(pg, tables, channels=("c1",))
    assert [r["id"] for r in pools["c1"]] == ["behind_the_hole"]


def test_sql_and_python_agree_that_an_uncertified_channel_is_empty(pg):
    tables = {
        "videos": [{"id": "v", "channel_id": "c1", "privacy_status": "public", "is_episode": None}],
        "reporting_reports_ingested": [
            {"report_id": f"r{n}", "channel_id": "c1", "data_date": day(n),
             "report_type": "channel_reach_basic_a1"} for n in range(28) if n != 5],
        "video_reach_daily": [{"id": 1, "video_id": "v", "channel_id": "c1", "date": day(0),
                               "impressions": 5000, "ctr": 0.05}],
        "interventions": [],
    }
    assert _assert_parity(pg, tables, channels=("c1",)) == {"c1": []}


def _cooldown_and_experiment_world() -> dict[str, list[dict]]:
    ids = ["declined_recent", "holdout_recent", "planned_recent", "declined_old",
           "backlinks_treated_old", "backlinks_holdout_old", "backlinks_human",
           "playlist_old", "free"]
    return {
        "videos": [{"id": v, "channel_id": "c1", "privacy_status": "public", "is_episode": None}
                   for v in ids],
        "reporting_reports_ingested": [
            {"report_id": f"r{n}", "channel_id": "c1", "data_date": day(n),
             "report_type": "channel_reach_basic_a1"} for n in range(28)],
        "video_reach_daily": [
            {"id": i, "video_id": v, "channel_id": "c1", "date": day(0),
             "impressions": 1000 + i, "ctr": 0.05} for i, v in enumerate(ids, 1)],
        "interventions": [
            {"id": i, **row} for i, row in enumerate([
                intervention("declined_recent", status="declined", age_days=1),
                intervention("holdout_recent", lever="title", arm="holdout", status="holdout",
                             age_days=1),
                intervention("planned_recent", status="planned", age_days=1),
                intervention("declined_old", status="declined", age_days=8),
                intervention("backlinks_treated_old", lever="backlinks", status="judged",
                             age_days=400),
                intervention("backlinks_holdout_old", lever="backlinks", arm="holdout",
                             status="judged", age_days=400),
                intervention("backlinks_human", lever="backlinks", origin="human", arm="n/a",
                             status="applied", age_days=1),
                intervention("playlist_old", lever="playlist", status="judged", age_days=400),
            ], 1)
        ],
    }


def test_sql_and_python_agree_on_the_cooldown_and_once_per_experiment(pg):
    """Part 4 S1.4 "Pick": recent Midas rows of any status and Midas backlinks
    rows of either arm, at any age, exclude; human rows and old ones don't."""
    pools = _assert_parity(pg, _cooldown_and_experiment_world(), channels=("c1",))
    assert sorted(r["id"] for r in pools["c1"]) == [
        "backlinks_human", "declined_old", "free", "playlist_old"]


def test_the_old_four_argument_function_is_gone(pg):
    """Replaced, not overloaded: PostgREST can't pick between overloads."""
    cur = pg.execute("select pg_get_function_identity_arguments(oid) from pg_proc "
                     "where proname = 'warm_pool'")
    assert [r[0] for r in cur.fetchall()] == [
        "p_channel_id text, p_min_impressions bigint, p_window_days integer, "
        "p_measurement_window_days integer, p_cooldown_days integer"]
