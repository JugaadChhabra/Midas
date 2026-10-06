"""B6: the scoped re-embed and per-channel playlist thresholds.

The production `model_version` (= EMBED_MODEL) holds vectors from two input
recipes, title + transcript after an apply and title only from bootstrap, so it
can't say what was embedded. app/reembed.py embeds one recipe under a version
that names it, resumably, and calibrates thresholds per channel on the result
without touching the process-global settings.
"""
import socket
from unittest.mock import patch

import pytest

from app import reembed
from app.config import settings
from app.openrouter import EMBED_MODEL
from tests.fakes import FakeSupabase

MR, PA = "UCmarathi", "UCpunjabi"


def _video(vid, channel=MR, title="t", description="d", tags=("a", "b")):
    return {"id": vid, "channel_id": channel, "title": title,
            "description": description, "tags": list(tags) if tags is not None else None}


class FakeEmbed:
    """Stands in for openrouter.embed: a deterministic vector per text."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]


# ── the recipe ────────────────────────────────────────────────────────────

def test_model_version_is_new_and_names_the_recipe():
    assert reembed.MODEL_VERSION != EMBED_MODEL
    assert reembed.MODEL_VERSION == f"{EMBED_MODEL}|{reembed.RECIPE}"


def test_recipe_is_title_description_tags_in_one_fixed_shape():
    text = reembed.recipe_text(_video("v1", title=" Song ", description="About it",
                                      tags=["rhyme", "kids"]))
    assert text == "Song\n\nAbout it\n\nrhyme, kids"


def test_recipe_keeps_its_shape_when_fields_are_empty():
    """No branch drops a block: an empty field is an empty block."""
    assert reembed.recipe_text(_video("v1", title="Song", description=None, tags=None)) \
        == "Song\n\n\n\n"


def test_recipe_is_identical_for_every_video_and_never_reads_a_transcript():
    """No transcript-dependent branch: the text is a pure function of the row,
    and two videos with the same metadata embed the same text whatever their
    privacy, transcript or channel."""
    a = _video("v1", channel=MR) | {"privacy_status": "public"}
    b = _video("v2", channel=PA) | {"privacy_status": "private"}
    with patch("app.transcripts.fetch_transcript",
               side_effect=AssertionError("the recipe must not read transcripts")):
        assert reembed.recipe_text(a) == reembed.recipe_text(b)


def test_reembed_embeds_the_recipe_text_for_every_video():
    sb = FakeSupabase({
        "videos": [_video("v1", title="One"), _video("v2", title="Two", tags=[])],
        "video_embeddings": [],
    })
    fake = FakeEmbed()
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", fake):
        reembed.reembed_channel(MR)
    sent = [t for call in fake.calls for t in call]
    assert sorted(sent) == sorted([reembed.recipe_text(v) for v in sb.rows("videos")])
    rows = sb.rows("video_embeddings")
    assert {(r["video_id"], r["chunk_index"], r["model_version"]) for r in rows} == {
        ("v1", "pooled", reembed.MODEL_VERSION), ("v2", "pooled", reembed.MODEL_VERSION)}


# ── resumable ─────────────────────────────────────────────────────────────

def test_rerun_skips_videos_already_embedded_under_the_new_version():
    old = {"video_id": "v1", "chunk_index": "pooled", "model_version": EMBED_MODEL,
           "embedding": "[9]"}
    done = {"video_id": "v2", "chunk_index": "pooled",
            "model_version": reembed.MODEL_VERSION, "embedding": "[1]"}
    sb = FakeSupabase({
        "videos": [_video("v1"), _video("v2"), _video("v3")],
        "video_embeddings": [old, done],
    })
    fake = FakeEmbed()
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", fake):
        first = reembed.reembed_channel(MR)
        second = reembed.reembed_channel(MR)
    # v1's old-version vector doesn't count; v2 is already done under the new one.
    assert first == {"channel_id": MR, "videos": 3, "skipped": 1, "embedded": 2, "failed": 0}
    assert second == {"channel_id": MR, "videos": 3, "skipped": 3, "embedded": 0, "failed": 0}
    assert len(fake.calls) == 1
    # The production-version row is untouched.
    assert old in sb.rows("video_embeddings")


def test_a_failed_batch_is_counted_and_the_rest_still_run(monkeypatch):
    monkeypatch.setattr(reembed, "BATCH_SIZE", 1)
    sb = FakeSupabase({"videos": [_video("v1"), _video("v2")], "video_embeddings": []})
    calls = []

    def flaky(texts):
        calls.append(texts)
        if len(calls) == 1:
            raise RuntimeError("OpenRouter embeddings 502")
        return [[1.0, 0.0] for _ in texts]

    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", flaky):
        out = reembed.reembed_channel(MR)
    assert out["embedded"] == 1 and out["failed"] == 1
    assert len(sb.rows("video_embeddings")) == 1


def test_a_failed_batch_is_retried_one_by_one(monkeypatch):
    """One text the API rejects mustn't fail its batch-mates on every rerun."""
    monkeypatch.setattr(reembed, "BATCH_SIZE", 3)
    sb = FakeSupabase({"videos": [_video("v1"), _video("bad", title="BAD"), _video("v3")],
                       "video_embeddings": []})

    def rejects_bad(texts):
        if any(t.startswith("BAD") for t in texts):
            raise RuntimeError("OpenRouter embeddings 400: input too long")
        return [[1.0, 0.0] for _ in texts]

    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", rejects_bad):
        out = reembed.reembed_channel(MR)
    assert out["embedded"] == 2 and out["failed"] == 1
    assert {r["video_id"] for r in sb.rows("video_embeddings")} == {"v1", "v3"}


def test_too_few_vectors_back_is_a_failure_not_a_silent_drop(monkeypatch):
    monkeypatch.setattr(reembed, "BATCH_SIZE", 2)
    sb = FakeSupabase({"videos": [_video("v1"), _video("v2")], "video_embeddings": []})
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", lambda texts: [[1.0, 0.0]]):
        out = reembed.reembed_channel(MR)
    # Batch of 2 → 1 vector: fails, then each single succeeds.
    assert out == {"channel_id": MR, "videos": 2, "skipped": 0, "embedded": 2, "failed": 0}


def test_only_the_named_channel_is_embedded():
    sb = FakeSupabase({"videos": [_video("v1", MR), _video("p1", PA)],
                       "video_embeddings": []})
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", FakeEmbed()):
        reembed.reembed_channel(MR)
    assert {r["video_id"] for r in sb.rows("video_embeddings")} == {"v1"}


# ── estimate ──────────────────────────────────────────────────────────────

def test_estimate_makes_no_network_call():
    """Estimate reads the DB (faked here) and never calls OpenRouter or opens a
    socket. The conftest guard blocks sockets; the embed and httpx patches make
    an attempt fail loudly rather than as a connection error."""
    sb = FakeSupabase({
        "videos": [_video("v1", title="abcd"), _video("v2")],
        "video_embeddings": [{"video_id": "v2", "chunk_index": "pooled",
                              "model_version": reembed.MODEL_VERSION, "embedding": "[1]"}],
    })
    boom = AssertionError("estimate must not call the network")
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", side_effect=boom), \
         patch("httpx.post", side_effect=boom), \
         patch.object(socket.socket, "connect", side_effect=boom):
        out = reembed.estimate_channel(MR, usd_per_mtok=1.0)
    remaining_text = reembed.recipe_text(_video("v1", title="abcd"))
    assert out["videos"] == 2 and out["remaining"] == 1
    assert out["tokens"] == reembed.estimate_tokens(remaining_text)
    assert out["usd"] == pytest.approx(out["tokens"] / 1_000_000)
    assert sb.writes == []


def test_token_estimate_counts_bytes_so_indic_text_costs_more():
    assert reembed.estimate_tokens("abc") < reembed.estimate_tokens("अआइ")
    assert reembed.estimate_tokens("") == 0


# ── calibration ───────────────────────────────────────────────────────────

_ASSIGN_IDS = iter(range(1, 10**6))


def _assign(pid, vid, action="added", at="2026-10-01T00:00:00+00:00"):
    """A playlist_assignments row, with its real columns: no channel_id (the
    table has none; a channel's rows are found through `playlists`)."""
    return {"id": next(_ASSIGN_IDS), "playlist_id": pid, "video_id": vid,
            "action": action, "decided_at": at}


def _playlist(pid, channel):
    return {"id": pid, "channel_id": channel}


def _emb(vid, vec):
    return {"video_id": vid, "chunk_index": "pooled",
            "model_version": reembed.MODEL_VERSION,
            "embedding": "[" + ",".join(str(x) for x in vec) + "]"}


def _calibration_db(n=12):
    """Two channels, one playlist each, with differently spread members."""
    assignments, embeddings = [], []
    for i in range(n):
        assignments.append(_assign("PLmr", f"m{i}"))
        embeddings.append(_emb(f"m{i}", [1.0, i * 0.05]))       # tight cluster
        assignments.append(_assign("PLpa", f"p{i}"))
        embeddings.append(_emb(f"p{i}", [1.0, i * 0.4]))        # loose cluster
    # A removed member and a production-version vector must both be ignored.
    assignments.append(_assign("PLmr", "gone", "added", "2026-09-01T00:00:00+00:00"))
    assignments.append(_assign("PLmr", "gone", "removed", "2026-09-02T00:00:00+00:00"))
    embeddings.append(_emb("gone", [-1.0, 0.0]))
    embeddings.append({"video_id": "m0", "chunk_index": "pooled",
                       "model_version": EMBED_MODEL, "embedding": "[-1,0]"})
    return FakeSupabase({
        "channels": [{"id": MR, "playlist_thresholds": None},
                     {"id": PA, "playlist_thresholds": None}],
        "playlists": [_playlist("PLmr", MR), _playlist("PLpa", PA)],
        "playlist_assignments": assignments,
        "video_embeddings": embeddings,
    })


def test_calibration_is_per_channel_and_leaves_the_global_settings_alone(monkeypatch):
    monkeypatch.setattr(reembed, "MIN_MEMBER_SIMS", 5)
    sb = _calibration_db()
    before = (settings.PLAYLIST_JOIN_HIGH, settings.PLAYLIST_JOIN_LOW, settings.PLAYLIST_LEAVE)
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb):
        mr = reembed.calibrate_channel(MR)
        pa = reembed.calibrate_channel(PA)
    assert (settings.PLAYLIST_JOIN_HIGH, settings.PLAYLIST_JOIN_LOW,
            settings.PLAYLIST_LEAVE) == before

    stored = {c["id"]: c["playlist_thresholds"] for c in sb.rows("channels")}
    assert stored[MR] == mr and stored[PA] == pa
    assert mr["model_version"] == reembed.MODEL_VERSION
    assert mr["member_sims"] == 12 and mr["playlists"] == 1
    # The tight channel gets a higher bar than the loose one.
    assert mr["join_high"] > pa["join_high"]
    for t in (mr, pa):
        assert t["join_low"] <= t["join_high"] and t["join_low"] <= t["leave"]
    # Only `channels` rows were written, one per channel, and nothing else.
    assert [(table, op) for table, op, _ in sb.writes] == [
        ("channels", "update"), ("channels", "update")]


def test_member_similarity_is_measured_apart_and_included():
    """`apart` scores a member as a candidate is scored (centroid of the others);
    `included` as reconcile scores it against PLAYLIST_LEAVE (centroid of all)."""
    sb = FakeSupabase({
        "channels": [{"id": MR}],
        "playlists": [_playlist("PL", MR)],
        "playlist_assignments": [_assign("PL", v) for v in ("a", "b", "c")],
        "video_embeddings": [_emb("a", [1, 0]), _emb("b", [1, 0]), _emb("c", [0, 1])],
    })
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb):
        sims = reembed.member_similarities(MR)
    # a vs mean(b, c) and b vs mean(a, c): cos 45°; c vs mean(a, b): orthogonal.
    assert sorted(sims.apart) == pytest.approx([0.0, 2 ** -0.5, 2 ** -0.5])
    # Each vs mean(a, b, c) = (2, 1) / 3.
    assert sorted(sims.included) == pytest.approx([5 ** -0.5, 2 * 5 ** -0.5, 2 * 5 ** -0.5])
    assert sims.playlists == 1


def test_leave_is_calibrated_on_the_included_similarity(monkeypatch):
    monkeypatch.setattr(reembed, "MIN_MEMBER_SIMS", 1)
    monkeypatch.setattr(reembed, "member_similarities",
                        lambda _cid: reembed.MemberSims([0.1, 0.2, 0.3], [0.7, 0.8, 0.9], 1))
    sb = FakeSupabase({"channels": [{"id": MR}]})
    with patch.object(reembed, "supabase", return_value=sb):
        out = reembed.calibrate_channel(MR)
    assert out["join_high"] == pytest.approx(0.2)
    assert out["join_low"] == pytest.approx(0.11)
    assert out["leave"] == pytest.approx(0.72)


def test_calibration_with_too_little_data_stores_nothing(monkeypatch):
    sb = _calibration_db(n=3)
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb):
        out = reembed.calibrate_channel(MR)
    assert out["skipped"] is True and out["reason"] == "insufficient_data"
    assert sb.writes == []



# ── the script ────────────────────────────────────────────────────────────

def test_script_estimate_prints_cost_and_embeds_nothing(capsys):
    from scripts import reembed as script
    sb = FakeSupabase({"videos": [_video("v1"), _video("p1", PA)], "video_embeddings": []})
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", side_effect=AssertionError("no API in estimate")):
        assert script.main(["--channels", f"{MR},{PA}", "--estimate",
                            "--usd-per-mtok", "0.15"]) == 0
    out = capsys.readouterr().out
    assert f"{MR}: 1 videos, 1 to embed" in out and f"{PA}: 1 videos" in out
    assert "total: ~$" in out
    assert sb.writes == []


def test_script_estimate_needs_a_price():
    from scripts import reembed as script
    with pytest.raises(SystemExit) as exc:
        script.main(["--channels", MR, "--estimate"])
    assert exc.value.code == 2


def test_script_run_embeds_then_calibrates_each_channel(capsys):
    from scripts import reembed as script
    sb = FakeSupabase({"videos": [_video("v1")], "video_embeddings": [],
                       "channels": [{"id": MR}], "playlists": [],
                       "playlist_assignments": []})
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", FakeEmbed()):
        assert script.main(["--channels", MR]) == 0
    out = capsys.readouterr().out
    assert '"embedded": 1' in out and "insufficient_data" in out


def test_members_are_found_through_the_channels_playlists():
    """playlist_assignments has no channel_id: a channel's members are those of
    the playlists whose `playlists.channel_id` is the channel."""
    sb = FakeSupabase({
        "playlists": [_playlist("PLmr", MR), _playlist("PLpa", PA)],
        "playlist_assignments": [
            _assign("PLmr", "m1"), _assign("PLmr", "m2"), _assign("PLpa", "p1"),
            # Latest action wins, ordered by decided_at, not by row order.
            _assign("PLmr", "m3", "removed", "2026-10-02T00:00:00+00:00"),
            _assign("PLmr", "m3", "added", "2026-10-01T00:00:00+00:00"),
        ],
    })
    with patch.object(reembed, "supabase", return_value=sb):
        assert reembed._members(MR) == {"PLmr": ["m1", "m2"]}
        assert reembed._members(PA) == {"PLpa": ["p1"]}
    assert all("channel_id" not in r for r in sb.rows("playlist_assignments"))


def test_script_a_calibration_error_is_reported_and_the_next_channel_still_runs(capsys, monkeypatch):
    from scripts import reembed as script
    sb = FakeSupabase({"videos": [_video("v1"), _video("p1", PA)], "video_embeddings": [],
                       "channels": [{"id": MR}, {"id": PA}], "playlists": [],
                       "playlist_assignments": []})
    calls = []

    def calibrate(cid):
        calls.append(cid)
        if cid == MR:
            raise RuntimeError("PGRST204")
        return {"skipped": True}

    monkeypatch.setattr(reembed, "calibrate_channel", calibrate)
    with patch.object(reembed, "supabase", return_value=sb), \
         patch("app.embeddings.supabase", return_value=sb), \
         patch.object(reembed, "embed", FakeEmbed()):
        assert script.main(["--channels", f"{MR},{PA}"]) == 1
    assert calls == [MR, PA]
    assert "calibration_error" in capsys.readouterr().out
