"""Live probe: which language codes does YouTube list for `defaultLanguage`?

`app/youtube_metadata.py` maps the Haryanvi content language `bgc` (ISO 639-3,
no ISO 639-1 code) to `hi` before it reaches `snippet.defaultLanguage` /
`defaultAudioLanguage` (`_NON_ISO_639_1`). That mapping was chosen from the
docs, not from the API. This probe asks the API: it calls `i18nLanguages.list`
(1 quota unit) and prints whether `bgc` and `hi` are in the returned list.

Reading the result:
  - `hi` listed, `bgc` not  -> the `bgc -> hi` mapping stands.
  - `bgc` listed            -> YouTube takes `bgc` directly; the owner decides
                               whether to drop the mapping.
The docs say `defaultLanguage` accepts "any supported application language or
most other ISO 639-1:2002 language codes", so `i18nLanguages.list` is the
application-language set. A code missing from it is undocumented, not proven
rejected.

Read-only. Nothing is written to YouTube or to the DB, except that
`youtube_for_channel` stores a refreshed access token if the old one expired.
The 1u is not charged to the `quota_log` ledger (there is no `Op` for it).

Usage:
    PYTHONPATH=. venv/bin/python scripts/probes/probe_i18n_languages.py <channel_id>
"""

from __future__ import annotations

import argparse
import json

from googleapiclient.errors import HttpError

from app.youtube_client import youtube_for_channel

_CODES = ("bgc", "hi")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("channel_id")
    args = p.parse_args()

    yt = youtube_for_channel(args.channel_id)

    print("\n── i18nLanguages.list (part=snippet) ─────────────────────")
    try:
        resp = yt.i18nLanguages().list(part="snippet").execute()
    except HttpError as e:
        print(f"HttpError {e.resp.status}: {e.content!r}")
        return 1

    items = resp.get("items") or []
    listed = {(i.get("snippet") or {}).get("hl"): (i.get("snippet") or {}).get("name")
              for i in items}
    print(f"{len(listed)} languages listed")

    print("\n=== codes Midas cares about ===")
    for code in _CODES:
        if code in listed:
            print(f"  {code:4s} LISTED      ({listed[code]})")
        else:
            print(f"  {code:4s} not listed")

    print(f"\n=== ALL {len(listed)} codes ===")
    print(json.dumps(dict(sorted(listed.items(), key=lambda kv: str(kv[0]))),
                     indent=2, ensure_ascii=False))
    print("\n── done ─────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
