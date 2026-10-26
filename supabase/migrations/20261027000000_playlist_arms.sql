-- Slice 2 · S2.1 (#87) — playlist_arms, the playlist test's unit, and the
-- columns that tie a playlist_proposals row to its arm and its send.
--
-- Spec Part 5 S2.1 (P3, E1, E4–E6). The playlist test splits a channel's
-- eligible playlists into treated and holdout halves (app/playlist_test.py
-- assign_arm) and gives each treated playlist one dose of up to
-- PLAYLIST_TEST_MAX_ADDS videos, proposed as pending `add` rows in
-- playlist_proposals with decision_source = 'experiment' and `arm_id` set, for
-- one human review. One row per playlist, written once per channel by
-- `playlist_test.draw` (it refuses a channel that already has rows).
--
-- `playlist_id` has no FK: playlists can be deleted on YouTube, and the arm
-- must outlive its playlist to be judged `insufficient_data` (S2.3).
-- `eligible_members` is how many current members had a B6 vector at the draw
-- (the members whose centroid the candidates were scored against).
-- `proposal_ids` lists the arm's proposals in candidate rank. The send columns
-- (`first_applied_at`, `last_applied_at`, and on playlist_proposals
-- `applied_at`, `playlist_item_id`, `apply_error`) are written by S2.2's
-- budgeted daily job, and `measurement_*` by S2.3. The vocabularies live in
-- app/status_vocab.py (PlaylistArm, PlaylistArmStatus, PlaylistArmMeasurement,
-- PlaylistProposalSource).

create table if not exists playlist_arms (
    id                  bigserial    primary key,
    channel_id          text         not null references channels(id),
    playlist_id         text         not null,
    arm                 text         not null,   -- treated|holdout
    status              text         not null,   -- planned|applying|dosed|no_dose|holdout|judged|insufficient_data
    eligible_members    int,
    proposal_ids        bigint[],
    first_applied_at    timestamptz,
    last_applied_at     timestamptz,
    measurement_status  text,                    -- awaiting_window|measuring|done
    measurement_result  jsonb,
    drawn_at            timestamptz  default now(),
    unique (playlist_id)
);

-- decision_source gains 'experiment' (the playlist test's proposals); it has
-- no check constraint, so nothing changes in the column itself.
alter table playlist_proposals add column if not exists arm_id           bigint references playlist_arms(id);
alter table playlist_proposals add column if not exists applied_at       timestamptz;
alter table playlist_proposals add column if not exists playlist_item_id text;
alter table playlist_proposals add column if not exists apply_error      jsonb;
