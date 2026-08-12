"""reporting_poll skips non-measurement channels (video_reach_daily bloat fix).

The rule itself now lives in app.eligibility (Job.REACH) — see
tests/test_eligibility.py. What this file still asserts is that the POLLER
honours it end to end, which is the behaviour that mattered when the flag was
introduced and is worth keeping independent of where the predicate lives.
"""
from unittest.mock import MagicMock, patch

import app.eligibility as el
import app.reporting_poll as rp


def _sb():
    sb = MagicMock()
    # eligibility pages via all_rows: .select().eq()[.or_()].order().range().execute()
    first_eq = sb.table.return_value.select.return_value.eq.return_value
    first_eq.order.return_value.range.return_value.execute.return_value.data = []
    first_eq.or_.return_value.order.return_value.range.return_value \
        .execute.return_value.data = []
    return sb, first_eq


def test_gates_on_the_measurement_optin_when_flag_on():
    """Either flag opts a channel in: measurement_enabled channels consume the
    reach/ctr backfill, and reach_warmup channels are accruing the coverage
    needed to certify CTR *before* measurement is switched on."""
    sb, first_eq = _sb()
    with patch.object(el.settings, "REPORTING_MEASURED_CHANNELS_ONLY", True), \
         patch.object(el, "supabase", return_value=sb):
        rp.poll_reporting()
    first_eq.or_.assert_called_once_with(
        "measurement_enabled.eq.true,reach_warmup.eq.true")


def test_polls_all_authorized_when_flag_off():
    sb, first_eq = _sb()
    with patch.object(el.settings, "REPORTING_MEASURED_CHANNELS_ONLY", False), \
         patch.object(el, "supabase", return_value=sb):
        rp.poll_reporting()
    first_eq.or_.assert_not_called()   # no opt-in filter
