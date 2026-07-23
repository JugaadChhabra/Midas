# tests/test_backfill_nas_folder.py
from unittest.mock import patch

from scripts.backfill_nas_folder import (
    KNOWN_LANGUAGES, derive_folder, folders_or_fallback,
)

FOLDERS = ["BANGLA", "HINDI", "MARATHI", "ENGLISH"]


def test_folders_fallback_when_nas_unreachable():
    # SMB errors (off-network) must not abort the backfill — fall back to the
    # stable known set so it can still run against the DB.
    with patch("scripts.backfill_nas_folder.list_source_languages",
               side_effect=OSError("NAS unreachable")):
        assert folders_or_fallback() == KNOWN_LANGUAGES


def test_folders_prefers_live_listing():
    with patch("scripts.backfill_nas_folder.list_source_languages",
               return_value=["HINDI", "TAMIL"]):
        assert folders_or_fallback() == ["HINDI", "TAMIL"]


def test_derive_unique_match():
    assert derive_folder("TMKOC Hindi Rhymes", FOLDERS) == "HINDI"


def test_derive_no_match_returns_none():
    assert derive_folder("Some Punjabi Channel", FOLDERS) is None


def test_derive_ambiguous_returns_none():
    # both HINDI and ENGLISH appear -> ambiguous
    assert derive_folder("Hindi + English Kids", FOLDERS) is None
