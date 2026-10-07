"""The metadata Midas sends YouTube, in one shape.

Apply and revert both push a video's title/description/tags back to YouTube.
They restate the same contract every time — the Education category, the content
language adapted to a code YouTube accepts, and the "not made for kids"
declaration — and they must send `snippet` and `status` together, because the
audience flag rides on `status` and any write that omits it silently clears it.

That contract used to live as two hand-copied blocks in `audits.py`; the
made-for-kids flag had already drifted once (the shorts uploader sent one value
while the audit paths sent another). It lives here now, built once, so apply and
revert cannot disagree about what a write to YouTube looks like.

What does NOT live here: the *act* of writing (the API call, DRY_RUN, error
classification, the database writes) and how each caller reacts to failure —
those legitimately differ between apply and revert and stay at each edge.
"""
from __future__ import annotations

#: Education. Every audited video is filed here (the shorts uploader files its
#: own uploads under a different category — a separate concern, a separate file).
CATEGORY_ID_EDUCATION = "27"

#: The fleet-wide audience declaration. False = not made for kids. A single
#: setting whether or not anyone intended it: `parts="snippet,status"` restates
#: it on every write, overwriting whatever the video had (omitting the key does
#: not help — YouTube treats the absent field on a status update as a change).
#: Asserted equal across subsystems in tests/test_made_for_kids.py.
#:
#: This is a compliance declaration to the FTC, not a preference — changing it is
#: a decision about the catalogue, not a code cleanup.
SELF_DECLARED_MADE_FOR_KIDS = False

#: The parts a metadata write must send. Coupled to the payload below:
#: `status` carries the made-for-kids flag, so it travels with `snippet` or the
#: flag is dropped. Kept beside the builder so the two cannot drift apart.
SNIPPET_STATUS_PARTS = "snippet,status"

#: Content languages with no ISO 639-1 code, and the nearest code YouTube takes.
#:
#: `channels.default_language` serves two consumers that disagree about what a
#: language code is. The audit prompt wants the language the AUDIENCE speaks, so
#: the model writes in it. YouTube's `snippet.defaultLanguage` /
#: `defaultAudioLanguage` — written on every apply and every revert — documents
#: acceptance of "any supported application language or most other ISO 639-1:2002
#: language codes", which is the two-letter set.
#:
#: Haryanvi forces them apart: a real audience, an ISO 639-3 code (`bgc`), and no
#: 639-1 code at all. Storing `hi` would satisfy YouTube while telling the model
#: to write standard Hindi — the wrong dialect for the channel. So the column
#: holds the truth and this table adapts it at the boundary, mapping to the
#: macrolanguage YouTube can express.
#:
#: Only add an entry you have confirmed has no 639-1 code. A code absent from
#: here is passed through untouched: letting YouTube reject an unknown code
#: fails loudly, whereas guessing a mapping mislabels the video to every viewer
#: silently and permanently.
_NON_ISO_639_1 = {
    "bgc": "hi",     # Haryanvi -> Hindi
    # Unused for now: the owner chose plain `hi` for Bhojpuri and Rajasthani
    # (2026-10-06). These let the channels switch later without a code change.
    "bho": "hi",     # Bhojpuri -> Hindi
    "raj": "hi",     # Rajasthani -> Hindi
}


def youtube_language_code(code: str | None) -> str | None:
    """The code to send YouTube for a channel's content language.

    Returns None for an absent language so the caller omits the field rather
    than guessing one — the payload builder below treats None that way.
    """
    if not code:
        return None
    return _NON_ISO_639_1.get(code, code)


def build_update_payload(video_id: str, *, title: str, description: str,
                         tags: list, lang: str | None) -> dict:
    """The videos.update body for one write — the shape YouTube accepts.

    Send it with `SNIPPET_STATUS_PARTS`. `lang` is the stored content language
    (possibly ISO 639-3); it is adapted to a YouTube code here, and omitted
    entirely when absent rather than guessed.
    """
    snippet: dict = {
        "title": title,
        "description": description,
        "tags": tags,
        "categoryId": CATEGORY_ID_EDUCATION,
    }
    yt_lang = youtube_language_code(lang)
    if yt_lang:
        snippet["defaultLanguage"] = yt_lang
        snippet["defaultAudioLanguage"] = yt_lang
    return {
        "id": video_id,
        "snippet": snippet,
        "status": {"selfDeclaredMadeForKids": SELF_DECLARED_MADE_FOR_KIDS},
    }
