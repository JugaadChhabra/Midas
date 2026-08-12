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
