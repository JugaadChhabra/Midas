"""Reading an embedding goes through one interface.

app/embeddings.py was a writer with no read interface, so its storage key —
(chunk_index='pooled', model_version=EMBED_MODEL, video_id) — was re-derived at
six Python call sites plus two SQL functions. `_parse_embedding`, an adapter for
the fact that PostgREST hands pgvector back as a string, had leaked out of
storage and into two other modules' import lists.

Four of those readers also used an unpaginated `.in_()`, so on a channel with
more than 1000 embedded videos the similarity matrix silently lost its tail.

And `embed_video` short-circuited on ANY existing row, so a video whose title
had just been rewritten kept the vector of its old title forever — even though
the call sits directly after a successful apply, which is precisely the moment
the title changed.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import embeddings as e


def _sb(rows, capture=None):
    """Supabase stub whose every filter chain terminates in `rows`."""
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        if capture is not None:
            capture["table"] = name

        class Chain:
            def __getattr__(self, attr):
                def call(*a, **kw):
                    if capture is not None:
                        capture.setdefault("calls", []).append((attr, a))
                    return self
                return call

            def execute(self):
                r = MagicMock()
                r.data = rows
                return r

        t.select.return_value = Chain()
        return t

    sb.table.side_effect = table
    return sb


# ── the pgvector adapter ──────────────────────────────────────────────────

def test_parse_vector_accepts_the_postgrest_string_form():
    assert e.parse_vector("[0.1,0.2,-0.3]") == pytest.approx([0.1, 0.2, -0.3])


def test_parse_vector_accepts_a_real_list():
    assert e.parse_vector([1, 2]) == [1.0, 2.0]


# ── reads ─────────────────────────────────────────────────────────────────

def test_pooled_embedding_parses_the_vector():
    with patch.object(e, "supabase", return_value=_sb([{"embedding": "[1,2,3]"}])):
        assert e.pooled_embedding("v1") == [1.0, 2.0, 3.0]


def test_pooled_embedding_missing_is_none():
    with patch.object(e, "supabase", return_value=_sb([])):
        assert e.pooled_embedding("v1") is None


def test_pooled_embedding_filters_on_the_full_key():
    """chunk_index AND model_version — a partial key would match another
    model's vectors or a per-chunk row."""
    cap = {}
    with patch.object(e, "supabase", return_value=_sb([{"embedding": "[1]"}], cap)):
        e.pooled_embedding("v1")
    eqs = {a for name, a in cap["calls"] if name == "eq"}
    assert ("chunk_index", e.POOLED) in eqs
    assert ("model_version", e.EMBED_MODEL) in eqs
    assert ("video_id", "v1") in eqs


def test_has_pooled_embedding_is_a_bare_existence_check():
    """Must not pull the vector — that is ~39 KB of egress per row."""
    cap = {}
    with patch.object(e, "supabase", return_value=_sb([{"id": 1}], cap)):
        assert e.has_pooled_embedding("v1") is True
    assert "embedding" not in cap["calls"][0][1][0]


def test_pooled_embeddings_returns_a_lookup():
    rows = [{"video_id": "v1", "embedding": "[1,2]"},
            {"video_id": "v2", "embedding": "[3,4]"}]
    with patch.object(e, "supabase", return_value=_sb(rows)):
        out = e.pooled_embeddings(["v1", "v2"])
    assert out == {"v1": [1.0, 2.0], "v2": [3.0, 4.0]}


def test_pooled_embeddings_empty_input_makes_no_query():
    sb = MagicMock()
    with patch.object(e, "supabase", return_value=sb):
        assert e.pooled_embeddings([]) == {}
    sb.table.assert_not_called()


def test_pooled_embeddings_chunks_past_the_row_cap():
    """Unpaginated, a channel with >1000 embedded videos lost its tail."""
    seen = []

    def build(chunk):
        seen.append(list(chunk))
        b = MagicMock()
        b.order.return_value.range.return_value.execute.return_value.data = [
            {"video_id": v, "embedding": "[1]"} for v in chunk
        ]
        return b

    with patch.object(e, "_pooled_query", side_effect=build):
        out = e.pooled_embeddings([f"v{n}" for n in range(1200)])
    assert len(out) == 1200
    assert max(len(c) for c in seen) <= 500


def test_embedded_video_ids_returns_only_ids():
    rows = [{"video_id": "v1"}, {"video_id": "v3"}]
    with patch.object(e, "supabase", return_value=_sb(rows)):
        assert e.embedded_video_ids(["v1", "v2", "v3"]) == {"v1", "v3"}


# ── invalidation ──────────────────────────────────────────────────────────

def _embed_world(existing):
    """(supabase stub, captured upserts) for embed_video."""
    upserts = []

    def table(name):
        t = MagicMock()
        if name == "video_embeddings":
            # has_pooled_embedding: .select().eq().eq().eq().limit().execute()
            t.select.return_value.eq.return_value.eq.return_value.eq.return_value \
                .limit.return_value.execute.return_value.data = existing
            t.upsert.side_effect = lambda row, **kw: (
                upserts.append(row) or MagicMock()
            )
        elif name == "videos":
            t.select.return_value.eq.return_value.single.return_value \
                .execute.return_value.data = {
                    "id": "v1", "title": "New Title",
                    "channel_id": "ch1", "privacy_status": "public",
                }
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    return sb, upserts


def test_embed_video_is_idempotent_by_default():
    sb, upserts = _embed_world(existing=[{"id": 1}])
    with patch.object(e, "supabase", return_value=sb):
        assert e.embed_video("v1") is False
    assert upserts == []


def test_force_re_embeds_a_video_whose_title_changed():
    """autopilot embeds right after a successful apply — the one moment the
    title is guaranteed to have changed."""
    sb, upserts = _embed_world(existing=[{"id": 1}])
    with patch.object(e, "supabase", return_value=sb), \
         patch.object(e, "fetch_transcript", return_value=(None, None)), \
         patch.object(e, "embed", return_value=[[0.1, 0.2]]):
        assert e.embed_video("v1", use_transcript=False, force=True) is True
    assert len(upserts) == 1
    assert upserts[0]["video_id"] == "v1"
    assert upserts[0]["chunk_index"] == e.POOLED


def test_embed_video_writes_the_full_key():
    sb, upserts = _embed_world(existing=[])
    with patch.object(e, "supabase", return_value=sb), \
         patch.object(e, "fetch_transcript", return_value=(None, None)), \
         patch.object(e, "embed", return_value=[[0.5]]):
        assert e.embed_video("v1", use_transcript=False) is True
    assert upserts[0]["model_version"] == e.EMBED_MODEL
    assert upserts[0]["chunk_index"] == e.POOLED


# ── the SQL mirror ────────────────────────────────────────────────────────

def test_sql_rpcs_use_the_same_chunk_index():
    """The pgvector RPCs re-type the storage key and cannot import it."""
    from pathlib import Path
    mig = Path(__file__).resolve().parents[1] / "supabase/migrations"
    for name in ("20260727120000_playlist_video_sims_rpc.sql",
                 "20260727150000_orphan_clusters_collate_c.sql"):
        sql = (mig / name).read_text()
        assert f"chunk_index = '{e.POOLED}'" in sql, f"{name} disagrees on chunk_index"
        assert "model_version = p_model_version" in sql, f"{name} disagrees on model_version"
