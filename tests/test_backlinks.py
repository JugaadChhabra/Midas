"""Slice 1 · S1.2 — the canonical backlink block (spec Part 4 S1.2, Part 2 §3.4; #61).

The heading table ships without Marathi (D3: the SEO team writes it), so every
test but the refusal ones renders with a test-only language patched into it.
"""
from unittest.mock import patch

import pytest

from app import backlinks
from app.audit_suggestion import DESCRIPTION_MAX, cap_description_hashtags
from app.config import settings

LANG = "xx"
HEADING = "Watch next:"


@pytest.fixture(autouse=True)
def heading():
    with patch.dict(backlinks.HEADINGS, {LANG: HEADING}):
        yield


def t(n: int, title: str | None = None) -> dict:
    """A target as S1.1 returns it; only video_id and title are read."""
    vid = f"vid{n:08d}"
    return {"video_id": vid, "channel_id": "c1", "title": title or f"Rhyme {n}",
            "similarity": 0.9, "impressions": 1000}


TARGETS = [t(1), t(2), t(3)]

DESCRIPTIONS = [
    "",
    "One line only",
    "#tag1 #tag2 #tag3\nEnglish text.\n\nमराठी मजकूर.\n\n#a #b #c",
    "First line\n",
    "\nstarts with a blank line",
    "First\nWatch more: https://youtu.be/aaaaaaaaaaa\nmore text",
    "First\n\n\ntrailing blanks\n\n",
]


def test_block_is_heading_then_one_line_per_target():
    out = backlinks.render("First line\nRest", TARGETS, LANG)
    assert out == (
        "First line\n"
        "Watch next:\n"
        "Rhyme 1 https://youtu.be/vid00000001\n"
        "Rhyme 2 https://youtu.be/vid00000002\n"
        "Rhyme 3 https://youtu.be/vid00000003\n"
        "\n"
        "Rest"
    )


# ── placement (D2) ────────────────────────────────────────────────────────


def test_block_goes_directly_after_the_first_line():
    """D2: above "Show more". A blank line separates it from what follows."""
    out = backlinks.render("#a #b #c\nBody line\nMore", TARGETS[:1], LANG)
    assert out.split("\n")[:3] == ["#a #b #c", HEADING, "Rhyme 1 https://youtu.be/vid00000001"]
    assert out.endswith("vid00000001\n\nBody line\nMore")


def test_one_line_description_gets_the_block_appended_under_it():
    out = backlinks.render("Only line", TARGETS[:1], LANG)
    assert out == "Only line\nWatch next:\nRhyme 1 https://youtu.be/vid00000001"


def test_empty_description_is_the_block_alone():
    out = backlinks.render("", TARGETS[:1], LANG)
    assert out == "Watch next:\nRhyme 1 https://youtu.be/vid00000001"
    assert backlinks.render(None, TARGETS[:1], LANG) == out


# ── idempotence ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("d", DESCRIPTIONS)
def test_render_twice_is_the_same_text_with_one_block(d):
    once = backlinks.render(d, TARGETS, LANG)
    twice = backlinks.render(once, TARGETS, LANG)
    assert twice == once
    assert twice.count(HEADING) == 1


def test_rerender_with_different_targets_replaces_the_block():
    first = backlinks.render("First\nRest", TARGETS[:2], LANG)
    second = backlinks.render(first, [t(7), t(8)], LANG)
    assert second == backlinks.render("First\nRest", [t(7), t(8)], LANG)
    assert second.count(HEADING) == 1
    assert "vid00000001" not in second and "vid00000002" not in second
    assert backlinks.find(second).video_ids == ("vid00000007", "vid00000008")


def test_a_block_moved_by_a_human_is_moved_back_not_duplicated():
    out = backlinks.render("First\nRest", TARGETS[:1], LANG)
    moved = "New first line\n" + out
    again = backlinks.render(moved, TARGETS[:1], LANG)
    assert again.count(HEADING) == 1
    assert again == "New first line\nWatch next:\nRhyme 1 https://youtu.be/vid00000001\n\nFirst\nRest"


# ── find / strip ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("d", DESCRIPTIONS)
def test_strip_undoes_render(d):
    assert backlinks.strip(backlinks.render(d, TARGETS, LANG)) == d


def test_find_returns_the_block_and_its_targets():
    out = backlinks.render("First\nRest", TARGETS[:2], LANG)
    block = backlinks.find(out)
    assert block.language == LANG
    assert block.video_ids == ("vid00000001", "vid00000002")
    assert out[block.start:block.end] == (
        "Watch next:\nRhyme 1 https://youtu.be/vid00000001\nRhyme 2 https://youtu.be/vid00000002"
    )


def test_find_is_none_without_a_block():
    assert backlinks.find("First\nRest") is None
    assert backlinks.find("") is None
    assert backlinks.find(None) is None


def test_a_humans_own_watch_more_lines_are_never_stripped():
    human = (
        "First\n"
        "Watch more rhymes:\n"
        "Rhyme 9 https://youtu.be/vid00000009\n"
        "https://youtu.be/vid00000010\n"
        "Rhyme 11 https://www.youtube.com/watch?v=vid00000011\n"
        "watch next:\n"
        "Rhyme 12 https://youtu.be/vid00000012\n"
        "Rest"
    )
    assert backlinks.find(human) is None
    assert backlinks.strip(human) == human
    out = backlinks.render(human, TARGETS[:1], LANG)
    assert backlinks.strip(out) == human


def test_strip_stops_at_the_first_line_that_is_not_a_block_link():
    d = (
        "First\n"
        "Watch next:\n"
        "Rhyme 1 https://youtu.be/vid00000001\n"
        "Rhyme 2 https://youtu.be/vid00000002?t=30\n"
        "Rest"
    )
    assert backlinks.strip(d) == "First\nRhyme 2 https://youtu.be/vid00000002?t=30\nRest"


def test_a_line_in_block_shape_added_under_the_block_reads_as_the_blocks():
    """Known limit: only a caller holding the rendered targets can tell them apart."""
    d = "First\nWatch next:\nRhyme 1 https://youtu.be/vid00000001\nMy pick https://youtu.be/abcdefghijk\n\nRest"
    assert backlinks.find(d).video_ids == ("vid00000001", "abcdefghijk")


def test_a_heading_with_no_links_under_it_is_not_a_block():
    d = "First\nWatch next:\nRest"
    assert backlinks.find(d) is None
    assert backlinks.strip(d) == d


# ── the cap ───────────────────────────────────────────────────────────────


def test_more_than_backlink_max_targets_is_refused():
    assert settings.BACKLINK_MAX == 3
    with pytest.raises(backlinks.RenderRefused, match="BACKLINK_MAX"):
        backlinks.render("First", [t(1), t(2), t(3), t(4)], LANG)


def test_backlink_max_is_read_at_call_time():
    with patch.object(settings, "BACKLINK_MAX", 1):
        with pytest.raises(backlinks.RenderRefused):
            backlinks.render("First", TARGETS[:2], LANG)
        assert backlinks.render("First", TARGETS[:1], LANG)


def test_no_targets_is_refused():
    with pytest.raises(backlinks.RenderRefused):
        backlinks.render("First", [], LANG)


def test_a_duplicate_target_is_refused():
    with pytest.raises(backlinks.RenderRefused, match="duplicate"):
        backlinks.render("First", [t(1), t(1)], LANG)


@pytest.mark.parametrize("bad", [
    {"video_id": "short", "title": "x"},
    {"video_id": "vid00000001", "title": "   "},
    {"video_id": "vid00000001"},
])
def test_a_malformed_target_is_refused(bad):
    with pytest.raises(backlinks.RenderRefused):
        backlinks.render("First", [bad], LANG)


# ── the language table (D3) ───────────────────────────────────────────────


def test_marathi_renders_with_its_heading():
    """D3, decided by the owner on 2026-10-23 (the SEO team had no preference)."""
    assert backlinks.HEADINGS["mr"] == "आणखी गाणी पहा:"
    out = backlinks.render("First", TARGETS, "mr")
    assert out.splitlines()[1] == "आणखी गाणी पहा:"
    assert backlinks.strip(out) == "First"


@pytest.mark.parametrize("lang", [None, "", "en", "zz"])
def test_a_language_missing_from_the_table_refuses_never_english(lang):
    with patch.dict(backlinks.HEADINGS, {}, clear=True):
        with pytest.raises(backlinks.RenderRefused, match="no backlink heading"):
            backlinks.render("First", TARGETS, lang)


def test_the_heading_follows_the_language():
    with patch.dict(backlinks.HEADINGS, {"yy": "Aur dekhiye:"}):
        out = backlinks.render("First", TARGETS[:1], "yy")
    assert out.split("\n")[1] == "Aur dekhiye:"


def test_the_shipped_table_has_no_hashtag_and_one_line_headings():
    for lang, heading in backlinks.HEADINGS.items():
        assert heading and "#" not in heading and "\n" not in heading, lang
        assert heading == heading.strip(), lang


def test_every_channel_language_has_a_heading():
    """Fleet readiness (owner, 2026-10-25): the 13 channels' default_language
    values (STATE.md §1). Bhojpuri, Rajasthani and 3D Animated use `hi`."""
    assert set(backlinks.HEADINGS) - {LANG} == {"mr", "hi", "bgc", "pa", "gu", "en", "ta", "ml", "kn", "te"}


def test_headings_are_distinct_so_find_knows_the_language():
    assert len(set(backlinks.HEADINGS.values())) == len(backlinks.HEADINGS)


@pytest.mark.parametrize("lang", ["mr", "hi", "bgc", "pa", "gu", "en", "ta", "ml", "kn", "te"])
def test_each_shipped_heading_round_trips(lang):
    out = backlinks.render("First", TARGETS, lang)
    assert out.splitlines()[1] == backlinks.HEADINGS[lang]
    block = backlinks.find(out)
    assert block.language == lang
    assert backlinks.strip(out) == "First"


# ── 5,000 characters ──────────────────────────────────────────────────────


def test_a_result_over_the_description_limit_is_refused():
    base = "First\n" + "x" * (DESCRIPTION_MAX - 6)
    assert len(base) == DESCRIPTION_MAX
    with pytest.raises(backlinks.RenderRefused, match=str(DESCRIPTION_MAX)):
        backlinks.render(base, TARGETS[:1], LANG)


def test_a_result_at_exactly_the_limit_is_allowed():
    block = backlinks.render("", TARGETS[:1], LANG)
    room = DESCRIPTION_MAX - len("First\n") - len(block) - len("\n\n")
    d = "First\n" + "x" * room
    out = backlinks.render(d, TARGETS[:1], LANG)
    assert len(out) == DESCRIPTION_MAX


# ── hashtags ──────────────────────────────────────────────────────────────


def test_output_passes_cap_description_hashtags_unchanged():
    tags = " ".join(f"#t{i}" for i in range(15))
    d = f"#a #b #c\nBody\n{tags[len('#t0 #t1 #t2 '):]}"
    assert cap_description_hashtags(d) == d
    out = backlinks.render(d, TARGETS, LANG)
    assert cap_description_hashtags(out) == out


def test_a_hashtag_in_a_target_title_is_not_carried_into_the_block():
    d = " ".join(f"#t{i}" for i in range(15)) + "\nBody"
    out = backlinks.render(d, [t(1, "Rhyme #shorts #kids")], LANG)
    assert "Rhyme shorts kids https://youtu.be/vid00000001" in out
    assert cap_description_hashtags(out) == out
    assert backlinks.strip(out) == d


def test_a_heading_with_a_hashtag_is_refused():
    with patch.dict(backlinks.HEADINGS, {"yy": "#WatchNext"}):
        with pytest.raises(backlinks.RenderRefused, match="hashtag"):
            backlinks.render("First", TARGETS[:1], "yy")


def test_title_whitespace_is_collapsed_to_one_line():
    out = backlinks.render("First", [t(1, "  Two\nline   title ")], LANG)
    assert out.split("\n")[2] == "Two line title https://youtu.be/vid00000001"


def test_a_devanagari_description_over_5000_bytes_is_refused_though_under_5000_characters():
    """YouTube's description limit is 5,000 bytes (Slice 1 review, 2026-10-23).
    A Devanagari character is 3 bytes in UTF-8."""
    base = "पहिली ओळ\n" + "म" * 1700                    # ~1,709 characters, ~5,100 bytes
    assert len(base) < DESCRIPTION_MAX < len(base.encode("utf-8"))
    with patch.dict(backlinks.HEADINGS, {"mr": "पहा:"}), \
         pytest.raises(backlinks.RenderRefused, match="bytes"):
        backlinks.render(base, [{"video_id": "aaaaaaaaaaa", "title": "t"}], "mr")
