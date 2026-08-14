"""Every metadata write declares the same audience, and it declares "not for kids".

YouTube's `selfDeclaredMadeForKids` rides along on `status`, so every write that
sends `parts="snippet,status"` restates it — silently overwriting whatever the
video had. That makes it a single fleet-wide setting whether or not anyone
intended it to be, and it was set inconsistently: the shorts uploader sent False
while both audit paths sent True, so a video's audience flag depended on which
subsystem touched it last.

One constant now, asserted equal across subsystems.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.audits import SELF_DECLARED_MADE_FOR_KIDS

REPO = Path(__file__).resolve().parents[1]


def test_audited_videos_are_declared_not_made_for_kids():
    assert SELF_DECLARED_MADE_FOR_KIDS is False


def test_the_shorts_uploader_declares_the_same_thing():
    """A video that is cut into a short and then audited must not flip audience
    halfway through. Both writers, one value."""
    from app.shorts import youtube_upload

    source = Path(youtube_upload.__file__).read_text()
    literals = set(re.findall(r'"selfDeclaredMadeForKids":\s*(True|False|[A-Z_]+)', source))
    assert literals, "the shorts uploader no longer sets the flag"
    for literal in literals:
        if literal in ("True", "False"):
            assert (literal == "True") is SELF_DECLARED_MADE_FOR_KIDS, (
                f"shorts uploader sends {literal}, audits send "
                f"{SELF_DECLARED_MADE_FOR_KIDS} — a video's audience flag would "
                f"depend on which subsystem wrote last"
            )


def test_no_audit_path_hardcodes_the_flag():
    """Both the apply and the revert payload must go through the constant.

    The revert path is the one that bites: it restores the pre-audit title and
    description, so it reads as "undo" — but it restates `status` too, and a
    hardcoded True there would re-flag a video the apply had just cleared.
    """
    source = (REPO / "app" / "audits.py").read_text()
    hardcoded = re.findall(r'"selfDeclaredMadeForKids":\s*(True|False)', source)
    assert not hardcoded, (
        f"app/audits.py hardcodes the audience flag {hardcoded}; use "
        f"SELF_DECLARED_MADE_FOR_KIDS so apply and revert cannot disagree"
    )
