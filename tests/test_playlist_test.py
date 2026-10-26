"""Slice 2 · S2.1 — the playlist test's arms, candidates, draw and preview
(spec Part 5 S2.1, Part 2 §4, P3; #87).

Runs against the FakeSupabase double: the real reach, warm, embeddings,
reembed and rows code, with only the database faked.
"""
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import playlist_test
from app.openrouter import EMBED_MODEL
from app.reembed import MODEL_VERSION
from app.rows import PAGE_SIZE
from scripts import playlist_test as script
from tests.fakes import FakeQuery, FakeSupabase

FRONTIER = date(2026, 10, 20)
CH, OTHER = "c1", "c2"
REACH = "channel_reach_basic_a1"
NEAR = [1.0, 0.0]


def day(n: int) -> str:
    return (FRONTIER - timedelta(days=n)).isoformat()


def at(sim: float) -> list[float]:
    """A unit vector whose cosine with NEAR is `sim`."""
    return [sim, (1 - sim * sim) ** 0.5]


def certified(channel):
    return [{"report_id": f"{channel}-{n}", "channel_id": channel, "data_date": day(n),
             "report_type": REACH} for n in range(28)]


def video(video_id, channel=CH, *, privacy="public", is_short=False, is_episode=None):
    return {"id": video_id, "channel_id": channel, "title": f"Title {video_id}",
            "privacy_status": privacy, "is_short": is_short, "is_episode": is_episode}


def emb(video_id, vector, model_version=MODEL_VERSION):
    return {"video_id": video_id, "chunk_index": "pooled", "model_version": model_version,
            "embedding": vector}


def reach(video_id, n, channel=CH):
    return {"video_id": video_id, "channel_id": channel, "date": day(0),
            "impressions": n, "ctr": 0.05}


def playlist(pid, *, role="funnel", channel=CH, title=None):
    return {"id": pid, "channel_id": channel, "title": title or f"Playlist {pid}", "role": role}


def added(pid, vid, n=0, action="added"):
    return {"playlist_id": pid, "video_id": vid, "action": action,
            "decided_at": f"2026-10-0{1 + n}T00:00:00+00:00"}


def thresholds(join_high=0.9, model_version=MODEL_VERSION):
    return {"model_version": model_version, "join_high": join_high, "join_low": 0.8,
            "leave": 0.85}


class World:
    """A channel's playlists, members, warm videos and vectors, as rows."""

    def __init__(self):
        self.playlists, self.assignments, self.videos = [], [], []
        self.reach, self.embeddings = [], []

    def add_playlist(self, pid, members=3, *, role="funnel", vector=NEAR, embedded=None):
        """A playlist with `members` members, the first `embedded` (default all)
        with a MODEL_VERSION vector at `vector`."""
        self.playlists.append(playlist(pid, role=role))
        embedded = members if embedded is None else embedded
        for i in range(members):
            vid = f"{pid}-m{i}"
            self.videos.append(video(vid))
            self.assignments.append(added(pid, vid))
            if i < embedded:
                self.embeddings.append(emb(vid, vector))
        return self

    def add_candidate(self, vid, sim, imp=1000, *, channel=CH, embedded=True, **video_kw):
        self.videos.append(video(vid, channel, **video_kw))
        self.reach.append(reach(vid, imp, channel))
        if embedded:
            self.embeddings.append(emb(vid, at(sim)))
        return self

    def fake(self, *, channel_thresholds=None, arms=(), proposals=()):
        tables = {
            "reporting_reports_ingested": certified(CH) + certified(OTHER),
            "playlists": self.playlists,
            "playlist_assignments": self.assignments,
            "videos": self.videos,
            "video_reach_daily": self.reach,
            "video_embeddings": self.embeddings,
            "channels": [{"id": CH, "playlist_thresholds": (
                thresholds() if channel_thresholds is None else channel_thresholds)},
                {"id": OTHER, "playlist_thresholds": thresholds()}],
            "playlist_arms": list(arms),
            "playlist_proposals": list(proposals),
        }
        for name, rows in tables.items():
            if name == "playlists":
                continue
            for i, r in enumerate(rows, 1):
                r.setdefault("id", i)
        return FakeSupabase(tables, serial=("playlist_arms", "playlist_proposals"))


@contextmanager
def wired(sb, **settings):
    settings = {"PLAYLIST_HOLDOUT_PCT": 0.5, "PLAYLIST_TEST_MAX_ADDS": 5,
                "WARM_MIN_IMPRESSIONS": 500, **settings}
    with patch.object(playlist_test, "supabase", return_value=sb), \
         patch("app.backlinks.supabase", return_value=sb), \
         patch("app.reembed.supabase", return_value=sb), \
         patch("app.reach.supabase", return_value=sb), \
         patch("app.warm.supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.multiple(playlist_test.settings, **settings):
        yield


@contextmanager
def postgrest_cap():
    """Truncate every read at PAGE_SIZE rows, as PostgREST does."""
    execute = FakeQuery.execute

    def capped(self):
        result = execute(self)
        if self._write is None and isinstance(result.data, list):
            result.data = result.data[:PAGE_SIZE]
        return result

    with patch.object(FakeQuery, "execute", capped):
        yield


def ids(rows):
    return [r["video_id"] for r in rows]


# ── eligibility ───────────────────────────────────────────────────────────

def test_eligibility_excludes_series_and_playlists_under_3_embedded_members():
    w = (World()
         .add_playlist("PLok", 3)
         .add_playlist("PLseries", 5, role="series")
         .add_playlist("PLthin", 5, embedded=2)                  # 5 members, 2 vectors
         .add_playlist("PLnull", 3, role=None))                  # an unclassified role is fine
    # A member whose only vector is the production one doesn't count.
    w.embeddings[-1]["model_version"] = EMBED_MODEL
    with wired(w.fake()):
        got = playlist_test.eligible(CH)
    assert [p["playlist_id"] for p in got] == ["PLok"]
    assert got[0]["eligible_members"] == 3

    with wired(w.fake()):
        survey = playlist_test.survey(CH)
    assert {s["playlist_id"]: s["reason"] for s in survey.skipped} == {
        "PLseries": "series", "PLthin": "too_few_embedded_members",
        "PLnull": "too_few_embedded_members"}


def test_a_removed_member_is_not_a_member():
    w = World().add_playlist("PL1", 3)
    w.assignments.append(added("PL1", "PL1-m0", n=5, action="removed"))
    with wired(w.fake()):
        assert playlist_test.eligible(CH) == []


def test_eligibility_reads_past_the_1000_row_cap():
    w = World().add_playlist("PLbig", 1200)
    with wired(w.fake()), postgrest_cap():
        [got] = playlist_test.eligible(CH)
    assert got["eligible_members"] == 1200


# ── the split ─────────────────────────────────────────────────────────────

def test_the_split_is_stable_and_about_half_and_half():
    with patch.multiple(playlist_test.settings, PLAYLIST_HOLDOUT_PCT=0.5):
        arms = [playlist_test.assign_arm(f"PL{i:05d}") for i in range(4000)]
        again = [playlist_test.assign_arm(f"PL{i:05d}") for i in range(4000)]
    assert arms == again
    assert set(arms) == {"treated", "holdout"}
    assert 0.47 < arms.count("holdout") / len(arms) < 0.53


def test_the_split_follows_playlist_holdout_pct():
    with patch.multiple(playlist_test.settings, PLAYLIST_HOLDOUT_PCT=0.0):
        assert {playlist_test.assign_arm(f"PL{i}") for i in range(200)} == {"treated"}
    with patch.multiple(playlist_test.settings, PLAYLIST_HOLDOUT_PCT=1.0):
        assert {playlist_test.assign_arm(f"PL{i}") for i in range(200)} == {"holdout"}


# ── candidates ────────────────────────────────────────────────────────────

def candidates(w, playlist_id="PL1", **kw):
    sb = w.fake(**{k: v for k, v in kw.items() if k == "channel_thresholds"})
    with wired(sb, **{k: v for k, v in kw.items() if k != "channel_thresholds"}):
        return playlist_test.candidates(CH, playlist_id)


def test_each_candidate_exclusion():
    w = (World().add_playlist("PL1", 3)
         .add_candidate("ok", 0.95)
         .add_candidate("cold", 0.95, imp=499)
         .add_candidate("private", 0.95, privacy="private")
         .add_candidate("short", 0.95, is_short=True)
         .add_candidate("episode", 0.95, is_episode=True)
         .add_candidate("below", 0.8999)
         .add_candidate("noemb", 0.95, embedded=False)
         .add_candidate("elsewhere", 0.95, channel=OTHER)
         .add_candidate("nullprivacy", 0.95, privacy=None)
         .add_candidate("nullshort", 0.95, is_short=None))
    # A member is never proposed again, however warm and close.
    w.reach.append(reach("PL1-m0", 9000))
    got = candidates(w)
    assert sorted(ids(got.rows)) == ["nullprivacy", "nullshort", "ok"]
    assert got.reason is None
    assert got.skipped_unembedded == 1
    assert got.join_high == 0.9


def test_the_bar_is_join_high_on_the_member_centroid_compared_raw():
    w = World().add_playlist("PL1", 0)
    # Two members at right angles: the centroid sits between them.
    for vid, vec in (("a", [1.0, 0.0]), ("b", [0.0, 1.0]), ("c", [1.0, 0.0])):
        w.videos.append(video(vid))
        w.assignments.append(added("PL1", vid))
        w.embeddings.append(emb(vid, vec))
    # Centroid = (2/3, 1/3): cosine to (1, 0) = 2/sqrt(5) = 0.894427...
    w.add_candidate("x", 0.0)
    w.embeddings[-1]["embedding"] = [1.0, 0.0]
    assert ids(candidates(w, channel_thresholds=thresholds(join_high=0.8944)).rows) == ["x"]
    assert ids(candidates(w, channel_thresholds=thresholds(join_high=0.8945)).rows) == []


def test_missing_or_other_version_thresholds_are_refused_with_a_reason():
    w = World().add_playlist("PL1", 3).add_candidate("ok", 0.99)
    got = candidates(w, channel_thresholds={})
    assert (got.rows, got.reason) == ([], "no_thresholds")
    got = candidates(w, channel_thresholds=thresholds(model_version=EMBED_MODEL))
    assert (got.rows, got.reason) == ([], "thresholds_other_model_version")


def test_ranked_by_impressions_then_similarity_then_id_and_capped_at_5():
    w = (World().add_playlist("PL1", 3)
         .add_candidate("v_low_imp", 0.99, imp=600)
         .add_candidate("v_b", 0.95, imp=5000)
         .add_candidate("v_a", 0.95, imp=5000)
         .add_candidate("v_closer", 0.97, imp=5000)
         .add_candidate("v_top", 0.91, imp=9000)
         .add_candidate("v_mid", 0.92, imp=3000)
         .add_candidate("v_sixth", 0.93, imp=700))
    got = candidates(w)
    assert ids(got.rows) == ["v_top", "v_closer", "v_a", "v_b", "v_mid"]
    assert got.rows[0] == {"video_id": "v_top", "title": "Title v_top",
                           "similarity": pytest.approx(0.91), "impressions": 9000}
    assert len(candidates(w, PLAYLIST_TEST_MAX_ADDS=2).rows) == 2


def test_candidates_read_past_the_1000_row_cap():
    w = World().add_playlist("PL1", 3)
    for i in range(1200):
        w.add_candidate(f"v{i:04d}", 0.95, imp=500 + i)
    with postgrest_cap():
        got = candidates(w)
    assert ids(got.rows) == [f"v{i:04d}" for i in (1199, 1198, 1197, 1196, 1195)]


# ── draw and preview ──────────────────────────────────────────────────────

def _arms():
    """Playlist ids, by the arm the stable hash gives them at 0.5."""
    with patch.multiple(playlist_test.settings, PLAYLIST_HOLDOUT_PCT=0.5):
        treated = [f"PL{i}" for i in range(40) if playlist_test.assign_arm(f"PL{i}") == "treated"]
        holdout = [f"PL{i}" for i in range(40) if playlist_test.assign_arm(f"PL{i}") == "holdout"]
    return treated, holdout


TREATED, HOLDOUT = _arms()


def drawable():
    """Two treated playlists (one with candidates, one far from every video),
    one holdout, and one series playlist."""
    t_dosed, t_empty = TREATED[:2]
    [h] = HOLDOUT[:1]
    w = (World()
         .add_playlist(t_dosed, 3)
         .add_playlist(t_empty, 3, vector=[0.0, 1.0])
         .add_playlist(h, 3)
         .add_playlist("PLseries", 3, role="series")
         .add_candidate("v1", 0.95, imp=2000)
         .add_candidate("v2", 0.93, imp=1000))
    return w, t_dosed, t_empty, h


def test_draw_writes_arms_and_pending_experiment_proposals_for_treated_only():
    w, t_dosed, t_empty, h = drawable()
    sb = w.fake()
    with wired(sb):
        result = playlist_test.draw(CH)

    arms = {a["playlist_id"]: a for a in sb.rows("playlist_arms")}
    assert set(arms) == {t_dosed, t_empty, h}
    assert {pid: (a["arm"], a["status"]) for pid, a in arms.items()} == {
        t_dosed: ("treated", "planned"), t_empty: ("treated", "no_dose"),
        h: ("holdout", "holdout")}
    assert all(a["channel_id"] == CH and a["eligible_members"] == 3 for a in arms.values())

    proposals = sb.rows("playlist_proposals")
    assert [(p["video_id"], p["playlist_id"]) for p in proposals] == [
        ("v1", t_dosed), ("v2", t_dosed)]
    for p in proposals:
        assert p["action"] == "add"
        assert p["status"] == "pending"
        assert p["decision_source"] == "experiment"
        assert p["arm_id"] == arms[t_dosed]["id"]
        assert p["video_title"] == f"Title {p['video_id']}"
        assert p["playlist_title"] == f"Playlist {t_dosed}"
    assert proposals[0]["similarity"] == pytest.approx(0.95)
    assert arms[t_dosed]["proposal_ids"] == [p["id"] for p in proposals]
    assert arms[t_empty]["proposal_ids"] == []
    assert arms[h]["proposal_ids"] == []

    assert result["playlists"] == 4
    assert result["arms"] == {"treated": 2, "holdout": 1, "no_dose": 1}
    assert result["proposals"] == 2
    assert result["skipped"] == [{"playlist_id": "PLseries", "title": "Playlist PLseries",
                                  "reason": "series"}]


def test_a_second_draw_refuses_and_writes_nothing():
    w, *_ = drawable()
    sb = w.fake(arms=[{"channel_id": CH, "playlist_id": "PLx", "arm": "holdout",
                       "status": "holdout"}])
    with wired(sb), pytest.raises(playlist_test.AlreadyDrawn):
        playlist_test.draw(CH)
    assert sb.writes == []

    # Another channel's arms don't count.
    sb = w.fake(arms=[{"channel_id": OTHER, "playlist_id": "PLx", "arm": "holdout",
                       "status": "holdout"}])
    with wired(sb):
        playlist_test.draw(CH)
    assert sb.writes


def test_draw_refuses_without_usable_thresholds_and_writes_nothing():
    w, *_ = drawable()
    sb = w.fake(channel_thresholds={})
    with wired(sb):
        result = playlist_test.draw(CH)
    assert result["refused"] == "no_thresholds"
    assert sb.writes == []


def test_preview_writes_nothing_and_shows_what_draw_would_write():
    w, t_dosed, t_empty, h = drawable()
    sb = w.fake()
    with wired(sb):
        got = playlist_test.preview(CH)
    assert sb.writes == []

    by_pl = {p["playlist_id"]: p for p in got["plan"]}
    assert {pid: (p["arm"], p["status"]) for pid, p in by_pl.items()} == {
        t_dosed: ("treated", "planned"), t_empty: ("treated", "no_dose"),
        h: ("holdout", "holdout")}
    assert [(c["video_id"], c["impressions"]) for c in by_pl[t_dosed]["videos"]] == [
        ("v1", 2000), ("v2", 1000)]
    assert by_pl[t_dosed]["videos"][0]["similarity"] == pytest.approx(0.95)
    # A holdout playlist's would-be videos aren't drawn, so none are shown.
    assert by_pl[h]["videos"] == []
    assert got["skipped"] == [{"playlist_id": "PLseries", "title": "Playlist PLseries",
                               "reason": "series"}]
    assert got["already_drawn"] is False
    assert (got["arms"], got["proposals"]) == ({"treated": 2, "holdout": 1, "no_dose": 1}, 2)


# ── the script ────────────────────────────────────────────────────────────

def test_the_script_previews_without_writing_then_draws_once(capsys):
    w, t_dosed, _, h = drawable()
    sb = w.fake()
    with wired(sb):
        assert script.main(["--channel", CH, "--preview"]) == 0
        assert sb.writes == []
        out = capsys.readouterr().out
        assert f"{t_dosed} 'Playlist {t_dosed}'" in out and "arm: treated  status: planned" in out
        assert "add v1 sim 0.9500 imp 2000: Title v1" in out
        assert "skipped PLseries (series)" in out

        assert script.main(["--channel", CH, "--draw"]) == 0
        assert len(sb.rows("playlist_arms")) == 3
        assert "2 proposals" in capsys.readouterr().out

        assert script.main(["--channel", CH, "--draw"]) == 1
        assert "refused" in capsys.readouterr().out
        assert len(sb.rows("playlist_arms")) == 3
