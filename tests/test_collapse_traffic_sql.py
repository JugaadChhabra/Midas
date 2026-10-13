"""The one-off scripts/collapse_traffic_detail.sql and traffic_poll's ingestion
rule agree (B1 retention, owner 2026-10-13).

Runs the real script through psql against a throwaway local Postgres (initdb into
a temp dir, Unix socket only), on random rows, and compares the table it leaves
with `traffic_poll.collapse_unread_detail` over the same rows. Skips without
Postgres server binaries and psql on PATH.
"""
from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app import traffic_poll as tp

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.needs_socket

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/collapse_traffic_detail.sql"
MIGRATION = REPO / "supabase/migrations/20261006000000_video_traffic_source_daily.sql"

SCHEMA = """
create role service_role;
create table channels (id text primary key);
create table videos (id text primary key, channel_id text not null);
create table reporting_reports_ingested (report_id text primary key);
"""

OURS = ["ourA", "ourB", "ourC", "q2kEmaYSaGY"]


@pytest.fixture(scope="module")
def pg():
    initdb, pg_ctl, psql = shutil.which("initdb"), shutil.which("pg_ctl"), shutil.which("psql")
    if not (initdb and pg_ctl and psql):
        pytest.skip("no Postgres binaries (initdb, pg_ctl, psql) on PATH")
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
            conn.execute(MIGRATION.read_text())
            conn.execute("insert into channels values ('c1'), ('c2')")
            for v in OURS:
                conn.execute("insert into videos values (%s, 'c1')", [v])
            yield root, psql, conn
    finally:
        subprocess.run([pg_ctl, "-D", str(data), "-m", "immediate", "stop"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


def _random_rows(seed: int) -> list[dict]:
    rnd = random.Random(seed)
    details = {
        7: OURS + ["x1", "x2", "x3", ""],
        14: ["PLdOc4aI4TeAo", "RDq2kEmaYSaGY", "RDourA", "RDx1", "RDAMVMHY7LepEngtg", "my-likes"],
        3: ["", "b1"], 5: ["", "nursery rhymes"], 32: ["x1", "ourB"],
    }
    rows = {}
    for _ in range(400):
        stype = rnd.choice(list(details))
        key = (rnd.choice(["v1", "v2", "v3"]), rnd.choice(["2026-10-09", "2026-10-10"]),
               stype, rnd.choice(details[stype]))
        rows[key] = {"video_id": key[0], "channel_id": "c1", "date": key[1], "source_type": stype,
                     "source_detail": key[3], "views": rnd.randint(0, 50),
                     "engaged_views": rnd.randint(0, 20),
                     "watch_time_minutes": rnd.randint(0, 400) / 4, "report_id": f"r{key[1]}"}
    return list(rows.values())


def _table(conn) -> dict:
    cur = conn.execute("select video_id, date::text, source_type, source_detail, views, engaged_views, "
                       "watch_time_minutes from video_traffic_source_daily")
    return {r[:4]: r[4:] for r in cur.fetchall()}


def _run_script(root, psql) -> None:
    subprocess.run([psql, "-h", str(root), "-U", "postgres", "-d", "postgres",
                    "-v", "ON_ERROR_STOP=1", "-q", "-f", str(SCRIPT)],
                   check=True, capture_output=True)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_script_leaves_what_ingestion_would_have_written(pg, seed):
    root, psql, conn = pg
    conn.execute("truncate video_traffic_source_daily")
    rows = _random_rows(seed)
    for r in rows:
        conn.execute(
            "insert into video_traffic_source_daily (video_id, channel_id, date, source_type, "
            "source_detail, views, engaged_views, watch_time_minutes, report_id) "
            "values (%(video_id)s, %(channel_id)s, %(date)s, %(source_type)s, %(source_detail)s, "
            "%(views)s, %(engaged_views)s, %(watch_time_minutes)s, %(report_id)s)", r)

    _run_script(root, psql)

    want = {(r["video_id"], r["date"], r["source_type"], r["source_detail"]):
            (r["views"], r["engaged_views"], r["watch_time_minutes"])
            for r in tp.collapse_unread_detail(rows, set(OURS))}
    assert _table(conn) == want

    # A second run changes nothing.
    _run_script(root, psql)
    assert _table(conn) == want
