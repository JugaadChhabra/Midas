"""Slice 2 · S2.4 — Short-link recommendations (spec Part 5 S2.4, Part 2 §2.3,
P4; #90).

Runs against the FakeSupabase double: the real reach, warm, embeddings, decide
and rows code, with only the database and OpenRouter faked.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app import main, short_links
from app.job_status import JobRunFailed
from app.openrouter import EMBED_MODEL
from app.reembed import MODEL_VERSION
from scripts import short_links as script
from tests.fakes import FakeSupabase

FRONTIER = date(2026, 10, 20)
CH, OTHER = "c1", "c2"
REACH, TRAFFIC = "channel_reach_basic_a1", "channel_traffic_source_a3"
NEAR = [1.0, 0.0]


def day(n: int) -> str:
    return (FRONTIER - timedelta(days=n)).isoformat()


def at(sim: float) -> list[float]:
    """A unit vector whose cosine with NEAR is `sim`."""
    return [sim, (1 - sim * sim) ** 0.5]


def ledger(channel, report_type, days):
    return [{"report_id": f"{channel}-{report_type}-{n}", "channel_id": channel,
             "data_date": day(n), "report_type": report_type} for n in days]


def video(video_id, channel=CH, *, privacy="public", is_short=False):
    return {"id": video_id, "channel_id": channel, "title": f"Title {video_id}",
            "privacy_status": privacy, "is_short": is_short}


def emb(video_id, vector, model_version=MODEL_VERSION):
    return {"video_id": video_id, "chunk_index": "pooled", "model_version": model_version,
            "embedding": vector}


def feed(video_id, views, n=0, channel=CH, source_type=24):
    return {"video_id": video_id, "channel_id": channel, "date": day(n),
            "source_type": source_type, "source_detail": "", "views": views}


def thresholds(join_low=0.8, model_version=MODEL_VERSION):
    return {"model_version": model_version, "join_high": 0.9, "join_low": join_low,
            "leave": 0.85}


class World:
    """A channel's Shorts, long videos, warmth, vectors and feed views, as rows."""

    def __init__(self):
        self.videos, self.reach, self.embeddings, self.traffic = [], [], [], []
        self.recommendations = []

    def add_short(self, vid, views=10, *, channel=CH, vector=NEAR, n=0, **video_kw):
        self.videos.append(video(vid, channel, is_short=True, **video_kw))
        self.traffic.append(feed(vid, views, n, channel))
        if vector is not None:
            self.embeddings.append(emb(vid, vector))
        return self

    def add_target(self, vid, sim, imp=1000, *, channel=CH, embedded=True, **video_kw):
        self.videos.append(video(vid, channel, **video_kw))
        self.reach.append({"video_id": vid, "channel_id": channel, "date": day(0),
                           "impressions": imp, "ctr": 0.05})
        if embedded:
            self.embeddings.append(emb(vid, at(sim)))
        return self

    def fake(self, *, channel_thresholds=None, traffic_days=range(28)):
        tables = {
            "reporting_reports_ingested": (
                ledger(CH, REACH, range(28)) + ledger(OTHER, REACH, range(28))
                + ledger(CH, TRAFFIC, traffic_days) + ledger(OTHER, TRAFFIC, range(28))),
            "videos": self.videos,
            "video_reach_daily": self.reach,
            "video_embeddings": self.embeddings,
            "video_traffic_source_daily": self.traffic,
            "channels": [{"id": CH, "playlist_thresholds": (
                thresholds() if channel_thresholds is None else channel_thresholds)},
                {"id": OTHER, "playlist_thresholds": thresholds()}],
            "short_link_recommendations": self.recommendations,
            "decision_log": [],
        }
        for name, rows in tables.items():
            if name in ("videos", "channels"):
                continue
            for i, r in enumerate(rows, 1):
                r.setdefault("id", i)
        return FakeSupabase(tables, serial=("short_link_recommendations", "decision_log"))


class Backend:
    """The fake OpenRouter: records every call, answers next-watch."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, prompt, model=None, system=None, image_urls=None, label=None):
        self.calls.append(label)
        if self.fail:
            raise RuntimeError("openrouter down")
        return {"answer": "no", "probs": {"yes": 0.3, "no": 0.7}}


@contextmanager
def wired(sb, backend=None, **settings):
    settings = {"SHORT_LINK_TARGETS": 3, "SHORT_LINK_MIN_FEED_VIEWS": 1,
                "SHORT_LINK_MAX_PER_RUN": 50, "WARM_MIN_IMPRESSIONS": 500,
                "SHORT_LINK_CHANNELS": {CH}, "TRAFFIC_INGEST_CHANNELS": {CH},
                "DECIDE_BACKEND": "llm", **settings}
    with patch.object(short_links, "supabase", return_value=sb), \
         patch("app.backlinks.supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch("app.warm.supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch("app.decide.supabase", return_value=sb), \
         patch("app.decide.openrouter.chat_json", backend or Backend()), \
         patch.multiple(short_links.settings, **settings):
        yield


def target_ids(world, short="S1", **kw):
    sb = world.fake(**kw)
    with wired(sb):
        found = short_links.targets({"id": short, "channel_id": CH})
    return [r["video_id"] for r in found.rows], found


# ── shorts(): feed views over ingested data-days ─────────────────────────

def test_feed_views_count_over_the_latest_28_ingested_data_days_not_calendar_days():
    # Traffic ingested on days 0–13 and 30–44: the latest 28 ingested are 0–13
    # and 30–43, so day 40 (calendar-old) counts and day 44 (ingested) doesn't,
    # nor day 20, inside the span with no ingested report.
    w = (World().add_short("S1", 2, n=40).add_short("S2", 5, n=44)
         .add_short("S3", 1, n=0).add_short("S4", 9, n=20))
    w.traffic.append(feed("S1", 3, n=0))
    sb = w.fake(traffic_days=[*range(14), *range(30, 45)])
    with wired(sb):
        listed = short_links.shorts(CH)
    assert [(s["id"], s["feed_views"]) for s in listed] == [("S1", 5), ("S3", 1)]


def test_shorts_are_public_shorts_of_the_channel_over_the_floor_most_views_first():
    w = (World().add_short("S1", 3).add_short("S2", 9).add_short("S3", 9)
         .add_short("SP", 50, privacy="private").add_short("SN", 4, privacy=None)
         .add_short("SO", 50, channel=OTHER).add_short("S0", 1))
    w.videos.append(video("LONG"))
    w.traffic += [feed("LONG", 50), feed("S0", 99, source_type=32),
                  feed("ghost", 50)]                       # not in videos
    sb = w.fake()
    with wired(sb, SHORT_LINK_MIN_FEED_VIEWS=2):
        listed = short_links.shorts(CH)
    assert [s["id"] for s in listed] == ["S2", "S3", "SN", "S1"]


def test_no_ingested_traffic_lists_no_shorts():
    sb = World().add_short("S1").fake(traffic_days=[])
    with wired(sb):
        assert short_links.shorts(CH) == []


# ── targets() ────────────────────────────────────────────────────────────

def test_each_target_exclusion():
    w = (World().add_short("S1")
         .add_target("OK", 0.95)
         .add_target("LOW", 0.79)                           # under join_low
         .add_target("COLD", 0.95, imp=499)                 # not warm
         .add_target("PRIV", 0.95, privacy="private")
         .add_target("SHORT", 0.95, is_short=True)
         .add_target("NULLS", 0.9, privacy=None, is_short=None)
         .add_target("SIB", 0.99, channel=OTHER))           # same channel only
    w.embeddings.append(emb("OLD", at(0.99), EMBED_MODEL))
    w.add_target("OLD", 0.99, embedded=False)               # only an EMBED_MODEL vector
    ids, found = target_ids(w)
    assert ids == ["OK", "NULLS"]
    assert found.join_low == 0.8 and found.reason is None
    assert found.skipped_unembedded == 1                   # OLD


def test_targets_rank_by_similarity_then_impressions_then_id_and_cap():
    w = (World().add_short("S1")
         .add_target("C", 0.9, imp=600).add_target("B", 0.9, imp=600)
         .add_target("A", 0.9, imp=700).add_target("TOP", 0.97, imp=501)
         .add_target("D", 0.85))
    ids, found = target_ids(w)
    assert ids == ["TOP", "A", "B"]
    assert [r["impressions"] for r in found.rows] == [501, 700, 600]
    assert found.rows[0]["channel_id"] == CH
    assert found.rows[0]["similarity"] == pytest.approx(0.97)


def test_a_short_without_a_vector_is_skipped_and_counted():
    ids, found = target_ids(World().add_short("S1", vector=None).add_target("OK", 0.95))
    assert (ids, found.skipped_unembedded, found.reason) == (
        [], 1, short_links.SOURCE_NOT_EMBEDDED)


@pytest.mark.parametrize("channel_thresholds, reason", [
    ({}, short_links.NO_THRESHOLDS),
    (thresholds(model_version=EMBED_MODEL), short_links.THRESHOLDS_OTHER_MODEL),
])
def test_missing_or_other_model_thresholds_are_refused(channel_thresholds, reason):
    w = World().add_short("S1").add_target("OK", 0.95)
    ids, found = target_ids(w, channel_thresholds=channel_thresholds)
    assert (ids, found.reason) == ([], reason)


# ── refresh() ────────────────────────────────────────────────────────────

def recs(sb):
    return sb.rows("short_link_recommendations")


def test_refresh_writes_pending_rows_ranked_with_their_numbers():
    w = (World().add_short("S1", 7).add_target("A", 0.97, imp=800)
         .add_target("B", 0.9, imp=900))
    sb = w.fake()
    with wired(sb):
        counts = short_links.refresh(CH)
    rows = recs(sb)
    assert [(r["short_id"], r["target_video_id"], r["rank"], r["status"]) for r in rows] == [
        ("S1", "A", 1, "pending"), ("S1", "B", 2, "pending")]
    assert [(r["impressions"], r["feed_views"], r["channel_id"]) for r in rows] == [
        (800, 7, CH), (900, 7, CH)]
    assert rows[0]["similarity"] == pytest.approx(0.97)
    assert (counts["recommended"], counts["rows"], counts["attempted"], counts["errored"]) == (
        1, 2, 1, 0)


def test_refresh_never_re_recommends_a_short_that_has_rows():
    w = World().add_short("S1", 9).add_short("S2", 5).add_target("A", 0.95)
    w.recommendations.append({"channel_id": CH, "short_id": "S1", "target_video_id": "A",
                              "rank": 1, "similarity": 0.9, "status": "dismissed"})
    sb = w.fake()
    with wired(sb):
        first = short_links.refresh(CH)
        second = short_links.refresh(CH)
    assert [(r["short_id"], r["status"]) for r in recs(sb)] == [
        ("S1", "dismissed"), ("S2", "pending")]
    assert (first["recommended"], first["already"]) == (1, 1)
    assert (second["recommended"], second["already"]) == (0, 2)


def test_refresh_stops_at_the_per_run_cap_most_feed_views_first():
    w = World().add_target("A", 0.95)
    for i, views in enumerate([5, 9, 7, 1]):
        w.add_short(f"S{i}", views)
    w.add_short("SX", 8, vector=None)                       # skipped: no cap slot used
    sb = w.fake()
    with wired(sb, SHORT_LINK_MAX_PER_RUN=2):
        counts = short_links.refresh(CH)
        assert sorted({r["short_id"] for r in recs(sb)}) == ["S1", "S2"]
        assert counts["skipped_unembedded"] == 1
        short_links.refresh(CH)
    assert sorted({r["short_id"] for r in recs(sb)}) == ["S0", "S1", "S2", "S3"]


def test_a_short_with_no_target_gets_no_row_and_is_tried_again():
    sb = World().add_short("S1").add_target("FAR", 0.5).fake()
    with wired(sb):
        counts = short_links.refresh(CH)
    assert recs(sb) == [] and counts["no_targets"] == 1 and counts["attempted"] == 0


def test_refused_thresholds_write_nothing():
    sb = World().add_short("S1").add_target("A", 0.95).fake(channel_thresholds={})
    with wired(sb):
        counts = short_links.refresh(CH)
    assert sb.writes == [] and counts["refused"] == short_links.NO_THRESHOLDS


def test_one_decision_log_row_per_pair_in_shadow_with_its_id_on_the_row():
    w = (World().add_short("S1").add_short("S2", 3)
         .add_target("A", 0.97).add_target("B", 0.9))
    sb = w.fake()
    backend = Backend()
    with wired(sb, backend):
        short_links.refresh(CH)
    logs = sb.rows("decision_log")
    assert [r["subject"] for r in logs] == ["S1->A", "S1->B", "S2->A", "S2->B"]
    assert {r["used"] for r in logs} == {"rules"}
    assert {r["rules_answer"] for r in logs} == {"yes"}
    assert {r["jev_answer"] for r in logs} == {"no"}
    assert all(r.get("intervention_id") is None for r in logs)
    assert backend.calls == ["decide.next_watch"] * 4
    log_of = {r["subject"]: r["id"] for r in logs}
    assert {f"{r['short_id']}->{r['target_video_id']}": r["decision_log_id"]
            for r in recs(sb)} == log_of


def test_the_next_watch_context_is_agent_ticks_with_the_short_as_source():
    sb = World().add_short("S1").add_target("A", 0.97).fake()
    with wired(sb), patch("app.short_links.decide.decide",
                          wraps=short_links.decide.decide) as asked:
        short_links.refresh(CH)
    [(question_set, subject, context), ] = [c.args for c in asked.call_args_list]
    assert question_set is short_links.decide.NEXT_WATCH and subject == "S1->A"
    assert context == {"source_video_id": "S1", "source_title": "Title S1",
                       "target_video_id": "A", "target_channel_id": CH,
                       "target_title": "Title A", "similarity": pytest.approx(0.97),
                       "join_low": 0.8}


def test_a_backend_failure_still_writes_the_recommendation_and_its_log_row():
    sb = World().add_short("S1").add_target("A", 0.97).fake()
    with wired(sb, Backend(fail=True)):
        counts = short_links.refresh(CH)
    [log_row] = sb.rows("decision_log")
    [rec] = recs(sb)
    assert log_row["jev_answer"] is None and log_row["used"] == "rules"
    assert rec["decision_log_id"] == log_row["id"] and rec["status"] == "pending"
    assert counts["errored"] == 0


# ── preview ──────────────────────────────────────────────────────────────

def test_preview_writes_nothing_and_calls_no_backend(capsys):
    w = (World().add_short("S1", 7).add_short("S2", vector=None)
         .add_target("A", 0.97).add_target("B", 0.9))
    sb = w.fake()
    backend = Backend()
    before = {name: sb.rows(name) for name in ("short_link_recommendations", "decision_log")}
    with wired(sb, backend):
        assert script.main(["--channel", CH, "--preview"]) == 0
    assert sb.writes == [] and backend.calls == []
    assert {name: sb.rows(name) for name in before} == before
    out = capsys.readouterr().out
    assert "=== 1. S1 feed views 7: Title S1" in out
    assert "  1. A sim 0.9700 imp 1000: Title A" in out and "  2. B sim" in out
    assert "1 would be, 1 skipped (no vector)" in out


def test_preview_says_when_the_thresholds_are_refused(capsys):
    sb = World().add_short("S1").add_target("A", 0.95).fake(channel_thresholds={})
    with wired(sb):
        assert script.main(["--channel", CH, "--preview"]) == 1
    assert "refused (no_thresholds)" in capsys.readouterr().out and sb.writes == []


# ── the job ──────────────────────────────────────────────────────────────

def test_short_link_refresh_is_registered_monday_1030_utc():
    sched = BackgroundScheduler(daemon=True)
    main._register_jobs(sched)
    job = sched.get_job("short_link_refresh")
    assert job is not None and job.func is short_links.run_weekly
    assert job.max_instances == 1 and job.coalesce is True
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["day_of_week"], fields["hour"], fields["minute"]) == ("mon", "10", "30")
    assert str(job.trigger.timezone) == "UTC"


def test_the_job_runs_short_link_channels_that_are_also_ingested():
    w = World().add_short("S1").add_target("A", 0.95)
    w.add_short("SO", channel=OTHER).add_target("AO", 0.95, channel=OTHER)
    sb = w.fake()
    with wired(sb, SHORT_LINK_CHANNELS={CH, OTHER}, TRAFFIC_INGEST_CHANNELS={CH}):
        assert short_links.run_weekly() is None
    assert {r["channel_id"] for r in recs(sb)} == {CH}
    with wired(sb, SHORT_LINK_CHANNELS={OTHER}, TRAFFIC_INGEST_CHANNELS={CH}):
        assert short_links.run_weekly() is None


def test_a_crashed_channel_fails_the_run_after_the_others_ran():
    w = World().add_short("S1").add_target("A", 0.95)
    w.add_short("SO", channel=OTHER).add_target("AO", 0.95, channel=OTHER)
    sb = w.fake()
    real = short_links.refresh

    def refresh(cid):
        if cid == CH:
            raise RuntimeError("boom")
        return real(cid)

    with wired(sb, SHORT_LINK_CHANNELS={CH, OTHER}, TRAFFIC_INGEST_CHANNELS={CH, OTHER}), \
         patch.object(short_links, "refresh", refresh), pytest.raises(JobRunFailed) as raised:
        short_links.run_weekly()
    assert raised.value.failed_channels == {CH: "RuntimeError: boom"}
    assert {r["channel_id"] for r in recs(sb)} == {OTHER}


def _failing_insert(sb, failing):
    table = sb.table

    def patched(name):
        t = table(name)
        if name == "short_link_recommendations":
            insert = t.insert

            def maybe(payload, **kw):
                if payload[0]["short_id"] in failing:
                    raise RuntimeError("insert failed")
                return insert(payload, **kw)
            t.insert = maybe
        return t
    return patched


def test_every_short_failing_fails_the_channel_some_is_degraded():
    w = World().add_short("S1", 9).add_short("S2").add_target("A", 0.95)
    sb = w.fake()
    with wired(sb), patch.object(sb, "table", _failing_insert(sb, {"S1", "S2"})), \
         pytest.raises(JobRunFailed) as raised:
        short_links.run_weekly()
    assert raised.value.failed_channels == {CH: "ItemsFailed: shorts: all 2 failed"}

    sb = w.fake()
    with wired(sb), patch.object(sb, "table", _failing_insert(sb, {"S1"})):
        assert short_links.run_weekly() == {"partial_errors": {CH: "shorts: 1/2 failed"}}
    assert {r["short_id"] for r in recs(sb)} == {"S2"}
    with wired(sb):                                        # the failed Short is tried again
        assert short_links.run_weekly() is None
    assert sorted(r["short_id"] for r in recs(sb)) == ["S1", "S2"]
    assert all(r["decision_log_id"] for r in recs(sb))


def test_refused_thresholds_make_the_channel_degraded_naming_the_reason():
    sb = World().add_short("S1").add_target("A", 0.95).fake(channel_thresholds={})
    with wired(sb):
        assert short_links.run_weekly() == {"partial_errors": {CH: "refused: no_thresholds"}}


def test_the_settings_start_values():
    from app.config import Settings
    s = Settings()
    assert s.SHORT_LINK_CHANNELS == {"UCr5-YUqBiW7PUmeAtxUWuRg"}
    assert (s.SHORT_LINK_TARGETS, s.SHORT_LINK_MIN_FEED_VIEWS, s.SHORT_LINK_MAX_PER_RUN) == (
        3, 1, 50)
