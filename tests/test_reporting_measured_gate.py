"""reporting_poll skips non-measurement channels (video_reach_daily bloat fix)."""
from unittest.mock import MagicMock, patch

import app.reporting_poll as rp


def _sb():
    sb = MagicMock()
    first_eq = sb.table.return_value.select.return_value.eq.return_value  # .eq(analytics_authorized)
    first_eq.execute.return_value.data = []          # flag-off path stops here
    first_eq.eq.return_value.execute.return_value.data = []   # flag-on adds a 2nd .eq
    return sb, first_eq


def test_gates_on_measurement_enabled_when_flag_on():
    sb, first_eq = _sb()
    with patch.object(rp.settings, "REPORTING_MEASURED_CHANNELS_ONLY", True), \
         patch.object(rp, "supabase", return_value=sb):
        rp.poll_reporting()
    first_eq.eq.assert_called_once_with("measurement_enabled", True)


def test_polls_all_authorized_when_flag_off():
    sb, first_eq = _sb()
    with patch.object(rp.settings, "REPORTING_MEASURED_CHANNELS_ONLY", False), \
         patch.object(rp, "supabase", return_value=sb):
        rp.poll_reporting()
    first_eq.eq.assert_not_called()  # no measurement_enabled filter
