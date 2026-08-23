#!/usr/bin/env python3
"""Reconnect the evidence loop: enable measurement, retire velocity candidates.

Step 1 of docs/superpowers/specs/2026-08-23-observability-evidence-loop-design.md.
Two writes that belong together, because both exist for the same reason — the
learning loop was fed nothing, and what little it was fed came from a metric
known to be broken.

    python scripts/reconnect_evidence_loop.py            # preview, writes nothing
    python scripts/reconnect_evidence_loop.py --apply    # do it, in one transaction

WRITE 1 — `channels.measurement_enabled = true` on the autopilot channel.
`audits.py` only stamps `awaiting_window` when this flag is set, so every audit
that channel applied fell to the `not_applicable` default with no result. It has
produced zero verdicts ever, while the only channel that HAS produced verdicts
has autopilot off. One boolean severed the loop.

WRITE 2 — retire the `shadow` prompt candidates written by the velocity-era
reflection. They are keyed on `performance_snapshot ? 'median_velocity_lift'`:
the old view-velocity report emitted that key, the CTR report emits
`median_ctr_delta_pct` instead, so the JSON shape is what dates the row. This
works because the column is `jsonb` (`?` is jsonb-only — it would error on
`json` or `text`). They are retired, not deleted, so the history stays readable.

Both writes run in ONE transaction. A failure on either rolls back both, because
retiring candidates while measurement stays off would leave the channel with no
prompt lineage and no way to build a new one.

Refusals, not assumptions. The script aborts rather than guessing if the
expected row counts don't match — a retirement predicate that hits more rows
than expected means a CTR-era candidate has been written since the spec was
drafted, and THAT one must not be retired.

Per CLAUDE.md: verify the change landed, THEN refresh the NAS snapshot. Do not
snapshot first — publishing replaces today's slot, so snapshotting an unverified
change overwrites a known-good copy.
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import psycopg
except ImportError:
    sys.exit("psycopg is required: pip install 'psycopg[binary]'")

#: The only channel with autopilot on, and the one whose outcomes were discarded.
AUTOPILOT_CHANNEL = "UCc4Tv_DEGDEKrKAt-vyVNmw"

#: How many velocity-era shadow candidates the 2026-08-08 export showed. A
#: different number is a reason to stop and look, not to proceed.
EXPECTED_VELOCITY_CANDIDATES = 5


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "This must point at the PRODUCTION Postgres on the office machine. "
            "Running it against a local copy will report success and change "
            "nothing that matters."
        )
    return dsn


def _preview(cur) -> tuple[bool, int]:
    """Print current state. Returns (channel_needs_write, velocity_candidate_count)."""
    cur.execute(
        "SELECT id, measurement_enabled, autopilot_enabled FROM channels WHERE id = %s",
        (AUTOPILOT_CHANNEL,),
    )
    row = cur.fetchone()
    if row is None:
        sys.exit(f"channel {AUTOPILOT_CHANNEL} does not exist — wrong database?")
    _, measurement_enabled, autopilot_enabled = row

    print(f"channel {AUTOPILOT_CHANNEL}")
    print(f"  measurement_enabled : {measurement_enabled}")
    print(f"  autopilot_enabled   : {autopilot_enabled}")
    if measurement_enabled:
        print("  -> already enabled; write 1 is a no-op")
    else:
        print("  -> WRITE 1 will set measurement_enabled = true")

    cur.execute(
        """
        SELECT id, channel_id, created_at::date,
               performance_snapshot ->> 'median_velocity_lift' AS velocity_lift
          FROM prompt_versions
         WHERE status = 'shadow'
           AND performance_snapshot ? 'median_velocity_lift'
         ORDER BY created_at
        """
    )
    velocity = cur.fetchall()
    print(f"\nvelocity-era shadow candidates: {len(velocity)}")
    for vid, cid, created, lift in velocity:
        print(f"  id={vid} {created} ch={cid[:12]} velocity_lift={lift}")

    # Anything in shadow WITHOUT the velocity key is CTR-era and must survive.
    #
    # `performance_snapshot IS NOT NULL` is load-bearing: on a NULL snapshot the
    # jsonb `?` operator yields NULL, so `? 'median_velocity_lift'` and
    # `NOT (? ...)` are BOTH not-true and the row fell out of the preview
    # entirely — while the preview reads as if it accounts for every shadow row.
    # It is listed separately below rather than folded in here, because a NULL
    # snapshot is neither era: it cannot be dated from its shape at all.
    cur.execute(
        """
        SELECT id, channel_id, created_at::date
          FROM prompt_versions
         WHERE status = 'shadow'
           AND performance_snapshot IS NOT NULL
           AND NOT (performance_snapshot ? 'median_velocity_lift')
         ORDER BY created_at
        """
    )
    keep = cur.fetchall()
    if keep:
        print(f"\nCTR-era shadow candidates ({len(keep)}) — these are NOT touched:")
        for vid, cid, created in keep:
            print(f"  id={vid} {created} ch={cid[:12]}")

    cur.execute(
        """
        SELECT id, channel_id, created_at::date
          FROM prompt_versions
         WHERE status = 'shadow'
           AND performance_snapshot IS NULL
         ORDER BY created_at
        """
    )
    unsnapshotted = cur.fetchall()
    if unsnapshotted:
        print(f"\nshadow candidates with NO performance_snapshot ({len(unsnapshotted)}) "
              "— also NOT touched:")
        for vid, cid, created in unsnapshotted:
            print(f"  id={vid} {created} ch={cid[:12]}")
        print("  (a NULL snapshot cannot be dated by its JSON shape, so the "
              "retirement predicate deliberately skips these. Left in shadow is "
              "the safe direction: a row wrongly retired loses its lineage.)")

    return (not measurement_enabled), len(velocity)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="perform the writes (default is preview only)")
    ap.add_argument("--expect-velocity", type=int, default=EXPECTED_VELOCITY_CANDIDATES,
                    help="abort unless exactly this many velocity-era candidates are "
                         "found (default %(default)s)")
    args = ap.parse_args()

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            needs_channel_write, n_velocity = _preview(cur)

            if not args.apply:
                print("\n(preview only — nothing written. re-run with --apply)")
                return

            if n_velocity != args.expect_velocity:
                conn.rollback()
                sys.exit(
                    f"\nABORT: expected {args.expect_velocity} velocity-era "
                    f"candidates, found {n_velocity}.\n"
                    "HIGHER means a candidate was written since this was drafted: "
                    "inspect it before retiring anything — if it is CTR-era it "
                    "must survive.\n"
                    "LOWER means something already changed these rows — a partial "
                    "earlier run, a manual edit, or the wrong database. Retiring "
                    "the remainder would finish a job whose first half nobody has "
                    "looked at.\n"
                    "Either way: look, then pass --expect-velocity to confirm you "
                    "have."
                )

            if needs_channel_write:
                cur.execute(
                    "UPDATE channels SET measurement_enabled = true WHERE id = %s",
                    (AUTOPILOT_CHANNEL,),
                )
                print(f"\nwrite 1: measurement_enabled = true ({cur.rowcount} row)")
            else:
                print("\nwrite 1: skipped (already enabled)")

            cur.execute(
                """
                UPDATE prompt_versions
                   SET status = 'retired', retired_at = now()
                 WHERE status = 'shadow'
                   AND performance_snapshot ? 'median_velocity_lift'
                """
            )
            print(f"write 2: retired {cur.rowcount} velocity-era candidates")
        conn.commit()

    print(
        "\ncommitted.\n"
        "\nNow, in this order:\n"
        "  1. Verify: re-run this script with no flags. measurement_enabled should\n"
        "     read True and the velocity-candidate count should be 0.\n"
        "  2. Only then refresh the NAS snapshot (CLAUDE.md):\n"
        "       PYTHONPATH=. venv/bin/python -c \\\n"
        "         \"from app.backup import snapshot_to_nas; print(snapshot_to_nas())\"\n"
        "\nWithin ~24h of the next autopilot apply that channel should have audits\n"
        "in awaiting_window; first verdicts in roughly 3 weeks."
    )


if __name__ == "__main__":
    main()
