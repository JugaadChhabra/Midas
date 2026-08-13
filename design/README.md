# design/

`running-shape.html` is the approved design for the whole UI — Running,
Autopilot, Videos, Playlists, Settings. It is a standalone throwaway: real
channel names and counts pulled from the account on 2026-08-12, invented
per-channel history, and buttons that fire toasts instead of doing anything.

It is checked in because it is the **reference the build is measured against**,
not because anything imports it. `scripts/design_diff.py` renders it beside the
running app and reports where they have drifted.

Do not edit it to match the build. It is the other way round: when the build
should legitimately differ — new data the design never had, a control the
design omitted that turned out to be necessary — record that in
`scripts/design_diff.py` as an explicit exception, with the reason. An
un-recorded difference is drift.

Provenance: published from this repo's session as a claude.ai artifact
(`bb200a61-c909-4856-a5f1-7f91810b1604`) and fetched back byte-for-byte. The
artifact URL needs the publishing account's login; this copy does not.
