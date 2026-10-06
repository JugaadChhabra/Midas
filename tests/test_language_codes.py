"""Content language and platform language are not the same thing.

`channels.default_language` feeds two consumers that disagree about what a
language code is:

  * the audit prompt's LANGUAGE RULE, which wants the language the audience
    actually speaks, so the model writes in it;
  * YouTube's `snippet.defaultLanguage` / `defaultAudioLanguage`, written on
    every apply AND every revert, which the API documents as accepting "any
    supported application language or most other ISO 639-1:2002 language
    codes" — a two-letter set.

Haryanvi is the case that forces them apart. It is a real language with a real
audience and an ISO 639-3 code (`bgc`), and no ISO 639-1 code at all. Storing
`hi` makes YouTube happy and tells the model to write standard Hindi, which is
the wrong dialect. Storing `bgc` tells the model the truth and hands YouTube a
code it does not document support for — on the write path of the only
autopilot-enabled channel.

So the column holds the truth and the boundary adapts.
"""
import pytest

from app.transcripts import lang_display_name
from app.youtube_metadata import youtube_language_code


def test_haryanvi_has_a_display_name():
    """Without this the prompt's LANGUAGE RULE reads "bgc (bgc)"."""
    assert lang_display_name("bgc") == "Haryanvi"


def test_haryanvi_is_sent_to_youtube_as_hindi():
    """`bgc` is ISO 639-3. YouTube documents ISO 639-1, so send the macrolanguage."""
    assert youtube_language_code("bgc") == "hi"


@pytest.mark.parametrize("code,name", [("bho", "Bhojpuri"), ("raj", "Rajasthani")])
def test_bhojpuri_and_rajasthani_have_display_names(code, name):
    """Same precedent as Haryanvi: ISO 639-2/3 codes with no 639-1 code."""
    assert lang_display_name(code) == name


@pytest.mark.parametrize("code", ["en", "hi", "mr", "pa", "bn", "ta", "te", "gu", "kn", "ml", "ur"])
def test_two_letter_codes_pass_through_untouched(code):
    """Every language already in use is ISO 639-1 and needs no translation."""
    assert youtube_language_code(code) == code


def test_absent_language_stays_absent():
    """None must not become a guess. The apply path omits the field entirely
    when there is no language, and that is the correct behaviour for a channel
    nobody has configured."""
    assert youtube_language_code(None) is None
    assert youtube_language_code("") is None


def test_an_unknown_code_is_passed_through_not_invented():
    """A code this table has never seen is returned as-is.

    Guessing a mapping would be worse than letting YouTube reject it: a wrong
    `defaultAudioLanguage` mislabels the video to every viewer, silently and
    permanently, whereas a rejected write fails loudly and gets fixed.
    """
    assert youtube_language_code("xyz") == "xyz"


def test_the_display_table_and_the_youtube_table_agree_about_what_exists():
    """Any code with a non-ISO-639-1 mapping must also have a display name.

    The two tables exist for different consumers and now live in different
    modules (display names with the prompt helper in transcripts, the YouTube
    mapping with the payload in youtube_metadata), but a code that needs
    translating for YouTube is by definition one this app writes content in —
    so the prompt must be able to name it. Without this, adding the next
    dialect makes the prompt say "raw code" and nothing catches it.
    """
    from app.youtube_metadata import _NON_ISO_639_1

    for code in _NON_ISO_639_1:
        assert lang_display_name(code) != code, (
            f"{code} is translated for YouTube but has no display name, so the "
            f"audit prompt would tell the model its language is {code!r}"
        )
