"""Read-only live parity guard: the dashboard RPC must agree with the in-app
legacy aggregation, field-for-field, on the real Supabase data.

This is the automatic form of the manual cross-check done when the RPC shipped.
It exists so the legacy path can eventually be deleted *safely*: while both paths
live, this proves they don't drift — and it is the thing that would catch a
subtle RPC bug in the UTC time-window fields (applied_today / applied_7d /
delta_views_7d) the moment real applies make them non-zero.

SELECT-only, no writes. Skips when no live credentials are configured.
"""
import pytest

from app.config import settings
from app.dashboard import _aggregate_rpc, _aggregate_legacy, _STAT_KEYS

pytestmark = pytest.mark.live


def _has_creds() -> bool:
    return bool((settings.SUPABASE_URL or "").strip() and (settings.SUPABASE_SERVICE_KEY or "").strip())


@pytest.fixture(scope="module", autouse=True)
def _require_creds():
    if not _has_creds():
        pytest.skip("no live Supabase credentials in the environment")


def test_rpc_matches_legacy_on_live_data():
    rpc_stats, rpc_cut, rpc_up = _aggregate_rpc()
    leg_stats, leg_cut, leg_up = _aggregate_legacy()

    assert (rpc_cut, rpc_up) == (leg_cut, leg_up), (
        f"shorts totals drift: rpc=({rpc_cut},{rpc_up}) legacy=({leg_cut},{leg_up})"
    )

    # legacy omits all-zero channels; the RPC returns a row per channel — union and
    # treat a missing channel as all-zero so both sides compare fairly.
    empty = {k: 0 for k in _STAT_KEYS}
    diffs = []
    for cid in set(rpc_stats) | set(leg_stats):
        r = rpc_stats.get(cid, empty)
        legrow = leg_stats.get(cid, empty)
        for k in _STAT_KEYS:
            if (r.get(k) or 0) != (legrow.get(k) or 0):
                diffs.append(f"  {cid[:14]}.{k}: rpc={r.get(k)} legacy={legrow.get(k)}")

    assert not diffs, "dashboard RPC vs legacy drift:\n" + "\n".join(diffs)
