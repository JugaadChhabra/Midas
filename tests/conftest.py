"""Offline tests may not open sockets.

A test that reaches the real PostgREST is, by definition, resting on a patch point
that has stopped intercepting anything. That condition is silent — worse than
silent, because the code still runs: a test whose patch had drifted issued a live
UPDATE against the production `channels` table on every offline run, and passed,
because the update's result was never asserted. Another set reached the real
database and made the suite HANG rather than fail.

Blocking sockets turns both into an immediate, named failure. Tests that
legitimately need one (the PO-token preflight checks whether a port is listening)
opt out with @pytest.mark.needs_socket.

Live tests are exempt: they exist to talk to the real project, and are deselected
by default via -m "not live".
"""
import socket

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _blocked(self, address, *a, **kw):
    raise RuntimeError(
        f"offline test opened a socket to {address}. Either a patch point has "
        f"drifted and this test is hitting the real database, or the test needs "
        f"a socket on purpose — in which case mark it @pytest.mark.needs_socket."
    )


@pytest.fixture(autouse=True)
def _no_network(request):
    if request.node.get_closest_marker("needs_socket") or \
            request.node.get_closest_marker("live"):
        yield
        return
    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    try:
        yield
    finally:
        socket.socket.connect = _real_connect
        socket.socket.connect_ex = _real_connect_ex


@pytest.fixture(autouse=True)
def _fresh_backlink_pools():
    """app/agent_tick.py keeps each channel's backlink target pool for an hour;
    a test's fake database must not see the previous test's."""
    from app import agent_tick
    agent_tick._pools.clear()
    yield
    agent_tick._pools.clear()


# ── the signed-in client (team tracker #144) ────────────────────────────────
# Every route but app/session.py's PUBLIC_PATHS needs a session. Route tests
# sign in as an admin through rows in a FakeSupabase that stands in for the
# session store only (app_users, app_sessions); each test still patches its own
# module's `supabase` for the rows it is about.
ADMIN_TOKEN = "test-admin-session-token"
ADMIN_USER = {"id": 1, "email": "admin@example.com", "name": "Test Admin",
              "role": "admin", "is_active": True, "password_hash": "unused"}


@pytest.fixture
def authed_client():
    """A factory for a TestClient signed in as an active admin:
    `authed_client()` or `authed_client(raise_server_exceptions=False)`."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app import main, session
    from tests.fakes import FakeSupabase

    store = FakeSupabase({
        "app_users": [dict(ADMIN_USER)],
        "app_sessions": [{"token_hash": session.hash_token(ADMIN_TOKEN), "user_id": 1,
                          "expires_at": "2999-01-01T00:00:00+00:00"}],
    })

    def make(**kw):
        return TestClient(main.app, cookies={session.COOKIE: ADMIN_TOKEN}, **kw)

    with patch.object(session, "supabase", return_value=store):
        yield make
