from fastapi import HTTPException

from app.apply_outcome import ApplyError, ApplyOutcome


def test_apply_error_is_http_exception_with_mapped_status():
    e = ApplyError(ApplyOutcome.QUOTA_EXCEEDED)
    assert isinstance(e, HTTPException)          # keeps the /apply + bulk contract
    assert e.status_code == 429
    assert e.detail == "youtube_quota_exceeded"  # preserves the frontend/DB string
    assert e.outcome is ApplyOutcome.QUOTA_EXCEEDED


def test_apply_error_status_mapping():
    assert ApplyError(ApplyOutcome.TEST_AND_COMPARE).status_code == 409
    assert ApplyError(ApplyOutcome.TOKEN_EXPIRED).status_code == 401
    assert ApplyError(ApplyOutcome.FAILED).status_code == 500


def test_apply_error_custom_detail_keeps_outcome():
    e = ApplyError(ApplyOutcome.FAILED, "YouTube update failed: boom")
    assert e.detail == "YouTube update failed: boom"
    assert e.outcome is ApplyOutcome.FAILED


def test_enum_values_match_the_persisted_strings():
    # These strings are stored as autopilot_paused_reason and read by the UI/auth.
    assert ApplyOutcome.TOKEN_EXPIRED.value == "token_expired"
    assert ApplyOutcome.TEST_AND_COMPARE.value == "blocked_test_and_compare"
