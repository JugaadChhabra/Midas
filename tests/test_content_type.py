"""app.content_type.is_episode — the single definition of "is this an episode".

The SEO flow audits nursery-rhyme content only; Shows episodes of "Taarak Mehta
Ka Ooltah Chashmah" are excluded. "Taarak Mehta" is the channel IP and appears
in nearly EVERY title, rhymes included, so the word "episode" is what separates
an episode from a rhyme. These tests pin exactly that: the IP alone must not
flag a rhyme; "episode" must flag an episode.
"""
import pytest

from app.content_type import is_episode


@pytest.mark.parametrize(
    "title",
    [
        "Taarak Mehta Ka Ooltah Chashmah - Episode 42",
        "taarak mehta ka ooltah chashmah ep... Episode 3",   # lower-case
        "Taarak Mehta 3D | Full Episode",
        "Episodes 10-12 | Taarak Mehta Ka Ooltah Chashmah",  # plural
        "Episode-3 Taarak Mehta",                            # hyphen, no space
    ],
)
def test_show_episodes_are_flagged(title):
    assert is_episode(title, []) is True


@pytest.mark.parametrize(
    "title",
    [
        # Rhyme content on the SAME channel — carries the IP but is NOT an episode.
        "Taarak Mehta Ka Ooltah Chashmah - Wheels on the Bus",
        "Johny Johny Yes Papa | Taarak Mehta 3D Rhymes",
        "Twinkle Twinkle Little Star",
    ],
)
def test_nursery_rhymes_are_not_flagged(title):
    assert is_episode(title, []) is False


def test_is_none_safe():
    # audit_video and sync pass raw snippet values; None title / None tags occur.
    assert is_episode(None, None) is False
    assert is_episode(None, ["episode"]) is False  # tag matching is opt-in
