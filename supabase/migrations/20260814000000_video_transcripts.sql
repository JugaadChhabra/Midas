-- Cache YouTube transcripts so a video is fetched once, not once per audit.
--
-- fetch_transcript() makes two network calls (list, then fetch) and nothing stored
-- the result: only `transcript_available` and `transcript_lang` flags landed, on
-- `audits`. So the same text was re-downloaded by every path that touched the
-- video — the audit, the embedding pass, every re-audit of a quarantined row, and
-- once per shadow audit. Shadow audits are the worst of it: they exist to A/B a
-- candidate prompt against videos that were ALREADY audited, so a run over 20
-- videos was 40 redundant round trips for text we had.
--
-- A separate table, deliberately NOT a column on `videos`: audit_video() does
-- `select("*")` on that row, so widening it would drag up to 8 KB of transcript
-- into every read that doesn't want it — making the hot path slower while trying
-- to make it faster. Keeping it separate also means it can be pruned or excluded
-- from a dump independently.
--
-- Size is bounded: fetch_transcript already truncates to TRANSCRIPT_MAX_CHARS
-- (8000), and only audited or embedded videos ever get a row, so this grows with
-- audit volume rather than with the catalogue.

create table if not exists video_transcripts (
    video_id    text primary key references videos(id) on delete cascade,
    -- NULL when the video has no usable transcript. Distinct from '': absent
    -- means "nothing to use", and the row still records that we checked.
    text        text,
    lang        text,
    -- False rows are the negative cache. Without them, a video with captions
    -- disabled gets re-probed on every single audit, forever.
    available   boolean not null default false,
    fetched_at  timestamptz not null default now()
);

-- The re-probe scan: find negative-cached rows old enough to be worth retrying,
-- since a video can gain auto-captions after we first looked.
create index if not exists video_transcripts_unavailable_idx
    on video_transcripts (fetched_at)
    where available = false;

grant all on video_transcripts to service_role;
