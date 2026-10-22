"""Slice 1 · S1.1 — siblings and backlink candidates (spec Part 4 S1.1, Part 2 §2.3; #62).

Runs against the FakeSupabase double: the real reach, warm, embeddings and
rows code, with only the database faked.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import backlinks
from app.openrouter import EMBED_MODEL
from app.reembed import MODEL_VERSION
from app.rows import PAGE_SIZE
from tests.fakes import FakeQuery, FakeSupabase

FRONTIER = date(2026, 10, 20)
SRC_CH, SIB, OTHER = "c1", "c2", "c3"
REACH, TRAFFIC = "channel_reach_basic_a1", "channel_traffic_source_a3"


def day(n: int) -> str:
    """The data-day n days before the frontier."""
    return (FRONTIER - timedelta(days=n)).isoformat()


def ledger(channel, report_type, days):
    return [{"report_id": f"{channel}-{report_type}-{d}", "channel_id": channel,
             "data_date": d, "report_type": report_type} for d in days]


def suggested(target, referrer, views, d=None, channel=SRC_CH, source_type=7):
    return {"video_id": target, "channel_id": channel, "date": d or day(0),
            "source_type": source_type, "source_detail": referrer, "views": views,
            "engaged_views": 0, "watch_time_minutes": 0.0, "report_id": "r"}


def video(video_id, channel=SRC_CH, *, title=None, privacy="public", is_short=False,
          description=""):
    return {"id": video_id, "channel_id": channel, "title": title or f"Title {video_id}",
            "privacy_status": privacy, "is_short": is_short, "description": description}


def emb(video_id, vector, model_version=MODEL_VERSION):
    return {"video_id": video_id, "chunk_index": "pooled", "model_version": model_version,
            "embedding": vector}


def impressions(video_id, n, channel=SRC_CH):
    return {"video_id": video_id, "channel_id": channel, "date": day(0),
            "impressions": n, "ctr": 0.05}


def thresholds(join_low=0.8, model_version=MODEL_VERSION):
    return {"model_version": model_version, "join_high": 0.9, "join_low": join_low,
            "leave": 0.85}


#: 28 contiguous reach days: certified.
def certified(channel):
    return ledger(channel, REACH, [day(n) for n in range(28)])


def fake(*, traffic_ledger=(), traffic=(), videos=(), reach_rows=(), embeddings=(),
         channels=None, reach_ledger=None):
    tables = {
        "reporting_reports_ingested": list(traffic_ledger) + list(
            reach_ledger if reach_ledger is not None
            else certified(SRC_CH) + certified(SIB) + certified(OTHER)),
        "video_traffic_source_daily": list(traffic),
        "videos": list(videos),
        "video_reach_daily": list(reach_rows),
        "video_embeddings": list(embeddings),
        "channels": channels if channels is not None else [
            {"id": SRC_CH, "playlist_thresholds": thresholds()},
            {"id": SIB, "playlist_thresholds": None},
            {"id": OTHER, "playlist_thresholds": None},
        ],
    }
    for rows in tables.values():
        for i, r in enumerate(rows, 1):
            r.setdefault("id", i)
    return FakeSupabase(tables)


@contextmanager
def wired(sb, ingest=(SRC_CH, SIB, OTHER), **settings):
    settings = {"SIBLING_MIN_VIEWS": 100, "BACKLINK_MAX": 3, "WARM_MIN_IMPRESSIONS": 500,
                "TRAFFIC_INGEST_CHANNELS": set(ingest), **settings}
    with patch.object(backlinks, "supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch("app.warm.supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.multiple(backlinks.settings, **settings):
        yield


@contextmanager
def postgrest_cap():
    """Truncate every read at PAGE_SIZE rows, as PostgREST does: the double
    doesn't, so without this a >1000-row test passes on an unpaged read."""
    execute = FakeQuery.execute

    def capped(self):
        result = execute(self)
        if self._write is None and isinstance(result.data, list):
            result.data = result.data[:PAGE_SIZE]
        return result

    with patch.object(FakeQuery, "execute", capped):
        yield


# ── siblings ──────────────────────────────────────────────────────────────

TRAFFIC_28 = ledger(SRC_CH, TRAFFIC, [day(n) for n in range(28)])
OUR_VIDEOS = [video("src"), video("s1", SIB), video("s2", SIB), video("o1", OTHER),
              video("u1", "c4")]


def siblings(sb, **kw):
    with wired(sb, **kw):
        return backlinks.siblings(SRC_CH)


def test_a_sibling_needs_sibling_min_views_and_they_are_ordered_by_views():
    sb = fake(traffic_ledger=TRAFFIC_28, videos=OUR_VIDEOS, traffic=[
        suggested("src", "s1", 60), suggested("src", "s2", 40, d=day(3)),   # SIB: 100
        suggested("src", "o1", 99),                                          # OTHER: 99
    ])
    assert siblings(sb) == [{"channel_id": SIB, "views": 100}]

    sb = fake(traffic_ledger=TRAFFIC_28, videos=OUR_VIDEOS, traffic=[
        suggested("src", "s1", 100), suggested("src", "o1", 300)])
    assert siblings(sb) == [{"channel_id": OTHER, "views": 300},
                            {"channel_id": SIB, "views": 100}]


def test_a_channel_outside_traffic_ingest_channels_never_counts():
    sb = fake(traffic_ledger=TRAFFIC_28, videos=OUR_VIDEOS, traffic=[
        suggested("src", "s1", 100), suggested("src", "o1", 5000), suggested("src", "u1", 5000)])
    assert siblings(sb, ingest=(SRC_CH, SIB)) == [{"channel_id": SIB, "views": 100}]


def test_own_channel_unknown_videos_and_other_source_types_do_not_count():
    sb = fake(traffic_ledger=TRAFFIC_28, videos=OUR_VIDEOS + [video("src2")], traffic=[
        suggested("src", "src2", 5000),                     # the channel itself
        suggested("src", "not-ours-11", 5000),              # a video not in `videos`
        suggested("src", "s1", 5000, source_type=14),       # not suggested
        suggested("src", "", 5000),                         # the folded blank bucket
    ])
    assert siblings(sb) == []


def test_the_window_is_the_latest_28_ingested_traffic_days_not_calendar_days():
    # Traffic reports every other day: the 28 latest span 55 calendar days.
    every_other = [day(2 * n) for n in range(40)]
    sb = fake(
        traffic_ledger=ledger(SRC_CH, TRAFFIC, every_other)
        # Reach reports on the days between don't make a traffic day.
        + ledger(SRC_CH, REACH, [day(2 * n + 1) for n in range(40)])
        # Nor do another channel's traffic reports.
        + ledger(SIB, TRAFFIC, [day(2 * n + 1) for n in range(40)]),
        videos=OUR_VIDEOS,
        traffic=[
            suggested("src", "s1", 100, d=day(54)),   # 28th ingested day: in
            suggested("src", "o1", 100, d=day(56)),   # 29th: out
        ],
    )
    assert siblings(sb) == [{"channel_id": SIB, "views": 100}]


def test_no_ingested_traffic_days_means_no_siblings():
    sb = fake(videos=OUR_VIDEOS, traffic=[suggested("src", "s1", 5000)])
    assert siblings(sb) == []


def test_siblings_reads_past_the_1000_row_cap():
    sb = fake(traffic_ledger=TRAFFIC_28, videos=OUR_VIDEOS, traffic=[
        suggested(f"t{i:04d}", "s1", 1, d=day(i % 28)) for i in range(1500)])
    with postgrest_cap():
        assert siblings(sb, SIBLING_MIN_VIEWS=1500) == [{"channel_id": SIB, "views": 1500}]


# ── candidates ────────────────────────────────────────────────────────────

SOURCE = video("src", description="First line\nmore")
NEAR = [1.0, 0.0]


def at(sim: float) -> list[float]:
    """A unit vector whose cosine with NEAR is `sim`."""
    return [sim, (1 - sim * sim) ** 0.5]


def target(video_id, sim, imp=1000, channel=SRC_CH, **video_kw):
    """A warm, embedded, public long-form target `sim` from the source."""
    return (video(video_id, channel, **video_kw), impressions(video_id, imp, channel),
            emb(video_id, at(sim)))


def scene(*targets, source=SOURCE, source_vector=NEAR, extra_reach=(), extra_embeddings=(),
          sibling_views=100, **kw):
    vids, reach_rows, embs = [source], list(extra_reach), list(extra_embeddings)
    if source_vector is not None:
        embs.append(emb(source["id"], source_vector))
    for v, r, e in targets:
        vids.append(v)
        reach_rows.append(r)
        if e is not None:
            embs.append(e)
    vids += [video("s-ref", SIB), video("o-ref", OTHER)]
    traffic = [suggested(source["id"], "s-ref", sibling_views)]
    return fake(traffic_ledger=TRAFFIC_28, traffic=traffic, videos=vids,
                reach_rows=reach_rows, embeddings=embs, **kw)


def candidates(sb, source=SOURCE, **kw):
    with wired(sb, **kw):
        return backlinks.candidates(source)


def ids(result):
    return [r["video_id"] for r in result.rows]


def test_a_qualifying_target_comes_back_with_its_row():
    result = candidates(scene(target("a", 0.95, imp=700, title="Song A")))
    assert result.rows == [{"video_id": "a", "channel_id": SRC_CH, "title": "Song A",
                            "similarity": pytest.approx(0.95), "impressions": 700}]
    assert result.reason is None
    assert result.skipped_unembedded == 0


def test_a_sibling_channels_target_counts_and_a_non_siblings_does_not():
    sb = scene(target("sib", 0.95, channel=SIB), target("oth", 0.95, channel=OTHER))
    assert ids(candidates(sb)) == ["sib"]


def test_a_sibling_below_sibling_min_views_contributes_no_targets():
    sb = scene(target("sib", 0.95, channel=SIB), sibling_views=99)
    assert ids(candidates(sb)) == []


def test_precomputed_sibling_ids_are_used_instead_of_reading_traffic():
    sb = scene(target("sib", 0.95, channel=SIB), target("oth", 0.95, channel=OTHER))
    with wired(sb):
        result = backlinks.candidates(SOURCE, sibling_ids=[OTHER])
    assert ids(result) == ["oth"]


def test_private_and_unlisted_targets_are_excluded():
    sb = scene(target("pub", 0.95), target("nul", 0.95, privacy=None),
               target("priv", 0.95, privacy="private"), target("unl", 0.95, privacy="unlisted"))
    assert sorted(ids(candidates(sb))) == ["nul", "pub"]


def test_a_short_is_excluded():
    sb = scene(target("long", 0.95), target("short", 0.95, is_short=True),
               target("unknown", 0.95, is_short=None))
    assert sorted(ids(candidates(sb))) == ["long", "unknown"]


def test_the_source_itself_is_excluded():
    sb = scene(target("a", 0.9), extra_reach=[impressions("src", 5000)])   # warm, similar to itself
    assert ids(candidates(sb)) == ["a"]


def test_a_video_already_linked_from_the_source_is_excluded():
    source = video("src", description=(
        "Line\nWatch https://youtu.be/linked00001 and "
        "https://www.youtube.com/watch?v=linked00002"))
    sb = scene(target("linked00001", 0.95), target("linked00002", 0.95),
               target("fresh000001", 0.95), source=source)
    assert ids(candidates(sb, source=source)) == ["fresh000001"]


def test_a_cold_target_is_excluded():
    sb = scene(target("warm", 0.95, imp=500), target("cold", 0.95, imp=499))
    assert ids(candidates(sb)) == ["warm"]


def test_a_target_on_a_channel_with_uncertified_reach_is_not_warm():
    sb = scene(target("sib", 0.95, channel=SIB),
               reach_ledger=certified(SRC_CH) + ledger(SIB, REACH, [day(n) for n in range(10)]))
    assert ids(candidates(sb)) == []


def test_a_target_below_the_source_channels_join_low_is_excluded():
    sb = scene(target("above", 0.8001), target("below", 0.79999))   # join_low 0.8
    assert ids(candidates(sb)) == ["above"]


def test_a_target_in_an_intervention_or_an_episode_is_still_a_target():
    """Warm is B4's impressions measure only: a treated video is a fine link target."""
    v, r, e = target("ep", 0.95)
    sb = scene((dict(v, is_episode=True), r, e))
    assert ids(candidates(sb)) == ["ep"]


def test_ranked_by_similarity_then_impressions_and_capped_at_twice_backlink_max():
    sb = scene(
        target("a", 0.99, imp=600), target("b", 0.97, imp=900), target("c", 0.97, imp=5000),
        target("d", 0.95), target("e", 0.93), target("f", 0.91), target("g", 0.90),
        target("h", 0.85),
    )
    assert ids(candidates(sb)) == ["a", "c", "b", "d", "e", "f"]
    assert ids(candidates(sb, BACKLINK_MAX=2)) == ["a", "c", "b", "d"]


def test_targets_without_a_b6_embedding_are_skipped_and_counted_never_from_embed_model():
    v1, r1, _ = target("old", 0.99)
    v2, r2, _ = target("none", 0.99)
    sb = scene(target("new", 0.9), (v1, r1, None), (v2, r2, None),
               extra_embeddings=[emb("old", NEAR, model_version=EMBED_MODEL)])
    result = candidates(sb)
    assert ids(result) == ["new"]
    assert result.skipped_unembedded == 2


def test_a_source_without_a_b6_embedding_gets_no_candidates_and_is_counted():
    sb = scene(target("a", 0.99), source_vector=None,
               extra_embeddings=[emb("src", NEAR, model_version=EMBED_MODEL)])
    result = candidates(sb)
    assert result.rows == []
    assert result.reason == backlinks.SOURCE_NOT_EMBEDDED
    assert result.skipped_unembedded == 1


def test_no_thresholds_means_no_candidates_with_a_reason():
    sb = scene(target("a", 0.99), channels=[{"id": SRC_CH, "playlist_thresholds": None}])
    result = candidates(sb)
    assert result.rows == []
    assert result.reason == backlinks.NO_THRESHOLDS


def test_thresholds_for_another_model_version_mean_no_candidates_with_a_reason():
    sb = scene(target("a", 0.99), channels=[
        {"id": SRC_CH, "playlist_thresholds": thresholds(model_version=EMBED_MODEL)}])
    result = candidates(sb)
    assert result.rows == []
    assert result.reason == backlinks.THRESHOLDS_OTHER_MODEL


def test_the_source_channels_join_low_applies_to_sibling_targets():
    sb = scene(target("sib", 0.85, channel=SIB), channels=[
        {"id": SRC_CH, "playlist_thresholds": thresholds(join_low=0.9)},
        # A sibling's own, lower threshold isn't used.
        {"id": SIB, "playlist_thresholds": thresholds(join_low=0.1)}])
    assert ids(candidates(sb)) == []


def test_candidates_read_past_the_1000_row_cap():
    # 1,200 warm, embedded targets; the only similar one sorts last by id.
    many = [target(f"v{i:04d}", 0.5) for i in range(1199)] + [target("v9999", 0.99)]
    sb = scene(*many)
    with postgrest_cap():
        assert ids(candidates(sb)) == ["v9999"]
