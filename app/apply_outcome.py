"""Typed outcome of applying an audit's metadata to YouTube.

apply_audit_internal classifies YouTube failures at the API boundary (the only
place the raw error text exists). Historically it re-encoded that classification
as an HTTPException whose *detail string* downstream callers re-parsed — YouTube's
error vocabulary leaking through the HTTP layer into the autopilot loop.

ApplyError carries the classification as a typed `.outcome` so callers switch on
an enum, not a string. It still IS-A HTTPException, so the `/apply` route and the
bulk-apply handler keep their exact status/detail behaviour (and the frontend's
`429` / `detail == "youtube_quota_exceeded"` contract) with no change. The enum
*values* deliberately equal the long-standing strings — some are persisted as
`autopilot_paused_reason` and read by auth.py and the UI.
"""
from enum import Enum

from fastapi import HTTPException


class ApplyOutcome(str, Enum):
    TEST_AND_COMPARE = "blocked_test_and_compare"
    QUOTA_EXCEEDED = "youtube_quota_exceeded"
    TOKEN_EXPIRED = "token_expired"
    FAILED = "failed"


# The HTTP status each outcome maps to — the whole YouTube-error taxonomy, in one
# place, instead of smeared across raise sites and re-decoded downstream.
_APPLY_STATUS: dict[ApplyOutcome, int] = {
    ApplyOutcome.TEST_AND_COMPARE: 409,
    ApplyOutcome.QUOTA_EXCEEDED: 429,
    ApplyOutcome.TOKEN_EXPIRED: 401,
    ApplyOutcome.FAILED: 500,
}


class ApplyError(HTTPException):
    """A classified apply failure. `.outcome` is the typed reason; being an
    HTTPException subclass preserves the existing HTTP status/detail contract for
    the `/apply` route and bulk handler unchanged."""

    def __init__(self, outcome: ApplyOutcome, detail: str | None = None):
        self.outcome = outcome
        super().__init__(status_code=_APPLY_STATUS[outcome], detail=detail or outcome.value)
