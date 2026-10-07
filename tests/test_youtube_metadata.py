"""The metadata payload YouTube accepts, built once for apply and revert.

apply and revert used to hand-copy this shape — category, language adaptation,
made-for-kids, and the parts they imply. They share build_update_payload now, so
the contract has one owner and the two paths cannot drift.
"""
import pytest

from app.youtube_metadata import (
    CATEGORY_ID_EDUCATION,
    SELF_DECLARED_MADE_FOR_KIDS,
    SNIPPET_STATUS_PARTS,
    build_update_payload,
)


def test_payload_carries_the_full_contract():
    p = build_update_payload("vid1", title="T", description="D",
                             tags=["a", "b"], lang="en")
    assert p["id"] == "vid1"
    assert p["snippet"]["title"] == "T"
    assert p["snippet"]["description"] == "D"
    assert p["snippet"]["tags"] == ["a", "b"]
    assert p["snippet"]["categoryId"] == CATEGORY_ID_EDUCATION
    assert p["status"]["selfDeclaredMadeForKids"] is SELF_DECLARED_MADE_FOR_KIDS


def test_language_is_adapted_at_the_boundary():
    """A content dialect (ISO 639-3) is mapped to the code YouTube documents."""
    p = build_update_payload("v", title="T", description="D", tags=[], lang="bgc")
    assert p["snippet"]["defaultLanguage"] == "hi"
    assert p["snippet"]["defaultAudioLanguage"] == "hi"


@pytest.mark.parametrize("lang", ["bho", "raj"])
def test_bhojpuri_and_rajasthani_are_sent_as_hindi(lang):
    """B7: `bho` and `raj` have no ISO 639-1 code, so YouTube gets `hi`."""
    p = build_update_payload("v", title="T", description="D", tags=[], lang=lang)
    assert p["snippet"]["defaultLanguage"] == "hi"
    assert p["snippet"]["defaultAudioLanguage"] == "hi"


def test_a_two_letter_language_passes_through():
    p = build_update_payload("v", title="T", description="D", tags=[], lang="hi")
    assert p["snippet"]["defaultLanguage"] == "hi"


def test_an_unmapped_language_reaches_the_payload_unchanged():
    """`hi` is also the mapping's output, so it can't tell pass-through from
    "everything becomes hi". A code the table doesn't touch can."""
    p = build_update_payload("v", title="T", description="D", tags=[], lang="pa")
    assert p["snippet"]["defaultLanguage"] == "pa"
    assert p["snippet"]["defaultAudioLanguage"] == "pa"


def test_absent_language_omits_the_field_rather_than_guessing():
    """A channel with no configured language must not have one invented for it."""
    p = build_update_payload("v", title="T", description="D", tags=[], lang=None)
    assert "defaultLanguage" not in p["snippet"]
    assert "defaultAudioLanguage" not in p["snippet"]


def test_the_parts_string_pairs_snippet_with_status():
    """made-for-kids rides on status, so status must travel with snippet or the
    flag is silently dropped."""
    assert SNIPPET_STATUS_PARTS == "snippet,status"
