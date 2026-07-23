# tests/test_backfill_nas_folder.py
from scripts.backfill_nas_folder import derive_folder

FOLDERS = ["BANGLA", "HINDI", "MARATHI", "ENGLISH"]


def test_derive_unique_match():
    assert derive_folder("TMKOC Hindi Rhymes", FOLDERS) == "HINDI"


def test_derive_no_match_returns_none():
    assert derive_folder("Some Punjabi Channel", FOLDERS) is None


def test_derive_ambiguous_returns_none():
    # both HINDI and ENGLISH appear -> ambiguous
    assert derive_folder("Hindi + English Kids", FOLDERS) is None
