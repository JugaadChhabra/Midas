"""Slice 3 · S3.2 (#116): the title writer, its checks, the pipeline, the
stamp, and the two read-only owner scripts (preview, bake-off).

The real context, warm pool, reach and stamp code runs against FakeSupabase;
OpenRouter (`titles.chat_json`) is faked at the edge.
"""
import csv
import dataclasses
from contextlib import ExitStack, contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import backlinks, decide, titles
from app.audit_suggestion import TITLE_MAX
from scripts import preview_titles, title_bakeoff
from tests.fakes import FakeSupabase

CH = "UCmarathi1"
FRONTIER = date(2026, 10, 20)
REACH, TRAFFIC = "channel_reach_basic_a1", "channel_traffic_source_a3"
BIG, A, B, C, D, E, SH = ("bigVideo001", "aVideo00001", "bVideo00001", "cVideo00001",
                          "dVideo00001", "eVideo00001", "shortVid001")
#: (impressions, CTR) on one day. Warm long CTRs: .01 .02 .03 .06 .08 .025 → median .0275.
REACH_ROWS = {BIG: (9_000_000, 0.01), SH: (6000, 0.001), A: (5000, 0.02), B: (4000, 0.03),
              C: (3000, 0.06), D: (2000, 0.08), E: (1000, 0.025)}
MARATHI = "ट्विंकल ट्विंकल | Twinkle Twinkle"


def day(n: int) -> str:
    return (FRONTIER - timedelta(days=n)).isoformat()


def _video(vid, **kw):
    return {"id": vid, "channel_id": CH, "title": f"Rhyme {vid}",
            "description": "Twinkle twinkle\nLyrics", "privacy_status": "public",
            "is_short": vid == SH, "is_episode": False, **kw}


def _traffic(vid, n, source_type, views, detail=""):
    return {"video_id": vid, "channel_id": CH, "date": day(n), "source_type": source_type,
            "source_detail": detail, "views": views}


def world():
    tables = {
        "channels": [{"id": CH, "default_language": "mr"}],
        "videos": [_video(v) for v in REACH_ROWS],
        "reporting_reports_ingested":
            [{"report_id": f"r{d}", "channel_id": CH, "data_date": day(d), "report_type": REACH}
             for d in range(28)]
            + [{"report_id": f"t{d}", "channel_id": CH, "data_date": day(d),
                "report_type": TRAFFIC} for d in range(28)],
        "video_reach_daily": [{"video_id": v, "channel_id": CH, "date": day(0),
                               "impressions": n, "ctr": ctr}
                              for v, (n, ctr) in REACH_ROWS.items()],
        "video_traffic_source_daily": [
            _traffic(A, 1, 5, 10, "twinkle"), _traffic(A, 2, 5, 20, "twinkle"),
            _traffic(A, 1, 5, 5, "baa baa"), _traffic(A, 1, 5, 100, ""),
            _traffic(A, 40, 5, 999, "old"),                   # outside the 28 days
            _traffic(A, 1, 3, 10), _traffic(C, 1, 3, 200), _traffic(C, 2, 7, 100, D),
            _traffic(D, 1, 7, 50, C), _traffic(SH, 1, 3, 6000),
        ],
        "video_transcripts": [{"video_id": A, "text": "twinkle twinkle little star",
                               "lang": "en", "available": True, "fetched_at": None}],
        "interventions": [],
        "audit_strategies": [],
        "lever_verdicts": [],
    }
    for name, rows in tables.items():
        for i, r in enumerate(rows, 1):
            r.setdefault("id", i)
    return FakeSupabase(tables)


@contextmanager
def wired(sb, *, chat=None):
    with ExitStack() as stack:
        for mod in ("titles", "agent_tick", "warm", "reach", "db", "backlinks", "human_edits",
                    "lever_verdicts"):
            stack.enter_context(patch(f"app.{mod}.supabase", return_value=sb))
        stack.enter_context(patch.multiple(
            titles.settings, HOLDOUT_PCT=0.0, TITLE_AGENT_PCT=0.0, WARM_POOL_USE_RPC=False, WARM_EXPLORE_PCT=0.0,
            WARM_MIN_IMPRESSIONS=500, TITLE_CANDIDATES=3, WRITER_MODEL="writer/model",
            TITLE_MAX_IMPRESSIONS=5_000_000))
        fake = stack.enter_context(patch("app.titles.chat_json", side_effect=chat))
        stack.enter_context(patch("app.titles.fetch_transcript",
                                  side_effect=AssertionError("live transcript fetch")))
        titles._strategy_rows_ensured.clear()
        yield fake
        titles._strategy_rows_ensured.clear()


def replies(*batches):
    """A fake chat_json answering each call with the next batch of titles."""
    calls = iter(batches)

    def chat(prompt, model=None, system=None, image_urls=None, label=None):
        batch = next(calls)
        if not isinstance(batch, list):
            return batch
        return {"candidates": [{"title": t, "reason": f"why {t}"} for t in batch]}
    return chat


# ── check ─────────────────────────────────────────────────────────────────

def video(language="mr", title="Rhyme #kids"):
    return {"id": A, "title": title, "default_language": language}


def test_the_script_check_rejects_a_gujarati_title_with_no_gujarati_character():
    assert titles.check("Twinkle Twinkle Little Star", video("gu")) == \
        "script: no Gujarati character"
    assert titles.check("ट्विंकल ट्विंकल", video("gu")) == "script: no Gujarati character"
    assert titles.check("ટ્વિંકલ ટ્વિંકલ | Twinkle", video("gu")) is None


@pytest.mark.parametrize("language", ["mr", "hi", "bgc"])
def test_the_script_check_accepts_a_devanagari_title_on_devanagari_channels(language):
    assert titles.check(MARATHI, video(language)) is None


def test_english_has_no_script_check():
    assert titles.check("Twinkle Twinkle Little Star", video("en")) is None


def test_every_channel_language_but_english_has_a_script():
    assert set(titles.SCRIPTS) == set(backlinks.HEADINGS) - {"en"}


def test_an_unknown_language_fails_closed():
    assert titles.check(MARATHI, video("xx")).startswith("script:")


def test_the_other_checks():
    v = video(title="ट्विंकल  Twinkle #kids")
    assert titles.check("", v).startswith("length:")
    assert titles.check("   ", v).startswith("length:")
    assert titles.check("ट" * (TITLE_MAX + 1), v).startswith("length:")
    assert titles.check("ट" * TITLE_MAX, v) is None
    assert titles.check("ट्विंकल twinkle   #KIDS", v) == "unchanged: the same as the current title"
    assert titles.check("ट्विंकल #kids #rhymes", v).startswith("hashtags:")
    assert titles.check("ट्विंकल #rhymes", v) is None            # one # as before
    assert titles.check("ट्विंकल https://youtu.be/x", v) == "url: contains a link"
    assert titles.check("ट्विंकल www.example.com", v) == "url: contains a link"


# ── the writer and the pipeline ───────────────────────────────────────────

def test_all_failing_candidates_give_none_with_reasons_and_the_retry_carries_them():
    sb = world()
    with wired(sb, chat=replies(["Rhyme aVideo00001", "English only"],
                                ["English again", "x" * 200])) as chat:
        written = titles.pipeline(_video(A), cache_only=True)
    assert written.title is None and written.reason is None
    assert len(written.failures) == 4
    assert "unchanged" in written.failures[0] and "Devanagari" in written.failures[1]
    assert [c["attempt"] for c in written.candidates] == [1, 1, 2, 2]
    first, retry = (c.args[0] for c in chat.call_args_list)
    assert "previous candidates failed" not in first
    assert "previous candidates failed" in retry
    assert "'English only': script: no Devanagari character" in retry
    assert "'Rhyme aVideo00001': unchanged" in retry


def test_the_first_passing_candidate_wins_with_no_retry():
    sb = world()
    with wired(sb, chat=replies(["English only", MARATHI, "ट्विंकल 2"])) as chat:
        written = titles.pipeline(_video(A), cache_only=True)
    assert (written.title, written.reason) == (MARATHI, f"why {MARATHI}")
    assert chat.call_count == 1
    assert [c["check"] is None for c in written.candidates] == [False, True]


def test_the_retry_can_pass():
    sb = world()
    with wired(sb, chat=replies(["English only"], [MARATHI])) as chat:
        written = titles.pipeline(_video(A), cache_only=True)
    assert written.title == MARATHI and chat.call_count == 2


@pytest.mark.parametrize("reply", [{}, {"candidates": "x"}, {"candidates": [{"t": 1}]}, []])
def test_a_malformed_reply_counts_as_no_passing_candidate(reply):
    sb = world()
    with wired(sb, chat=replies(reply, reply)):
        written = titles.pipeline(_video(A), cache_only=True)
    assert written.title is None and written.failures


def test_write_candidates_asks_the_writer_model_with_the_title_prompt():
    sb = world()
    with wired(sb, chat=replies(["a", "b", "c", "d"], ["a"])) as chat:
        ctx = titles.context(_video(A), cache_only=True)
        assert len(titles.write_candidates(ctx)) == 3                 # TITLE_CANDIDATES
        titles.write_candidates(ctx, model="other/model")
    first, second = chat.call_args_list
    assert first.kwargs["model"] == "writer/model" and second.kwargs["model"] == "other/model"
    assert first.kwargs["label"] == "titles.write"
    assert first.kwargs["system"] == titles.system_prompt()
    assert "home page" in titles.system_prompt() and str(TITLE_MAX) in titles.system_prompt()


def test_writer_model_defaults_to_audit_model():
    from app.config import Settings
    assert Settings.WRITER_MODEL == Settings.AUDIT_MODEL


# ── the context ───────────────────────────────────────────────────────────

def test_the_context():
    sb = world()
    with wired(sb):
        channel = titles.channel_context(CH)
        ctx = titles.context(_video(A, description="d" * 2000), channel=channel,
                             cache_only=True)
    assert set(channel.reach) == {BIG, A, B, C, D, E}                 # no Short
    assert channel.median_ctr == pytest.approx(0.0275)
    assert channel.ceiling == {BIG}                                   # top 1% (1 of 6), > 5M
    assert ctx["description"] == "d" * 1500
    assert ctx["transcript"] == "twinkle twinkle little star"
    assert ctx["default_language"] == "mr"
    assert (ctx["impressions"], ctx["ctr"]) == (5000, 0.02)
    assert ctx["channel_median_ctr"] == pytest.approx(0.0275)
    assert ctx["search_terms"] == [{"term": "twinkle", "views": 30},
                                   {"term": "baa baa", "views": 5}]
    assert [t["video_id"] for t in ctx["top_performers"]] == [C, D]  # A itself left out
    assert ctx["top_performers"][0]["views_per_impression"] == pytest.approx(0.1)
    assert ctx["traffic_mix_28d"]


# ── path and stamp ────────────────────────────────────────────────────────

def test_the_path_split_is_stable_and_about_half():
    ids = [f"vid{i:08d}" for i in range(2000)]
    with patch.object(titles.settings, "TITLE_AGENT_PCT", 0.5):
        paths = [titles.title_path(v) for v in ids]
        assert paths == [titles.title_path(v) for v in ids]
    assert 0.45 < paths.count(titles.AGENT) / len(ids) < 0.55
    with patch.object(titles.settings, "TITLE_AGENT_PCT", 0.0):
        assert {titles.title_path(v) for v in ids} == {titles.PIPELINE}


def test_the_stamp_covers_lever_path_prompt_writer_and_question_set():
    with patch.object(titles.settings, "WRITER_MODEL", "writer/model"):
        version, inputs = titles.strategy_inputs(titles.PIPELINE)
        agent, _ = titles.strategy_inputs(titles.AGENT)
        with patch.object(decide, "QUESTION_SET_VERSION", "2099.01-test"):
            moved, _ = titles.strategy_inputs(titles.PIPELINE)
    with patch.object(titles.settings, "WRITER_MODEL", "other/model"):
        other, _ = titles.strategy_inputs(titles.PIPELINE)
    assert set(inputs) == {"lever", "path", "prompt_sha256", "writer_model",
                           "decision_question_set_version"}
    assert inputs["lever"] == "title" and inputs["writer_model"] == "writer/model"
    assert version.startswith(titles.settings.STRATEGY_LABEL + "-")
    assert len({version, agent, moved, other}) == 4
    with pytest.raises(ValueError):
        titles.strategy_inputs("house_format")


def test_strategy_version_upserts_its_row_once():
    sb = world()
    with wired(sb):
        v1 = titles.strategy_version(titles.PIPELINE)
        assert titles.strategy_version(titles.PIPELINE) == v1
    [(table, op, row)] = sb.writes
    assert (table, op) == ("audit_strategies", "upsert")
    assert row["version"] == v1 and row["model"] == "writer/model"
    assert row["prompt_template"] == "code:app/titles.py TITLE_PROMPT"


# ── the owner scripts write nothing ───────────────────────────────────────

def test_the_preview_lists_title_answers_and_writes_nothing(capsys, tmp_path):
    sb = world()
    with wired(sb, chat=replies([MARATHI], ["ट्विंकल 2"], ["ट्विंकल 3"])):
        items = titles.preview(CH, 20)
        out = tmp_path / "p.csv"
        preview_titles.main(["--channel", CH, "--n", "1", "--csv", str(out)])
    assert sb.writes == []
    assert [i["video_id"] for i in items] == [A, E]     # below the median, BIG over the ceiling
    assert [(i["arm"], i["path"]) for i in items] == [("treated", "pipeline")] * 2
    assert items[0]["written"].title == MARATHI
    assert items[1]["written"].title == "ट्विंकल 2"
    assert "-> 'ट्विंकल 3'" in capsys.readouterr().out
    assert [r["video_id"] for r in csv.DictReader(out.open(encoding="utf-8"))] == [A]


def test_the_preview_asks_triages_rules():
    """S3.3: the preview's title answer is TRIAGE.rules on the tick's context,
    so an id the SEO team excludes, and a video backlinks would take, drop out."""
    sb = world()
    with wired(sb, chat=replies(["ट्विंकल 1"])), \
         patch.object(titles.settings, "TITLE_EXCLUDE_VIDEOS", {A}):
        assert [i["video_id"] for i in titles.preview(CH, 20)] == [E]
    with wired(sb, chat=replies(["ट्विंकल 1"], ["ट्विंकल 2"])), \
         patch.object(titles.decide, "TRIAGE", dataclasses.replace(
             decide.TRIAGE, rules=lambda ctx: "backlinks" if ctx["ctr"] == 0.02 else "title")):
        assert [i["video_id"] for i in titles.preview(CH, 2)] == [BIG, B]


def test_the_agent_preview_says_not_built_and_calls_no_writer():
    sb = world()
    with wired(sb) as chat, patch.object(titles.settings, "TITLE_AGENT_PCT", 1.0):
        items = titles.preview(CH, 20, path=titles.AGENT)
    assert {i["note"] for i in items} == {"agent not built"}
    chat.assert_not_called()
    assert sb.writes == []


def test_the_preview_holdout_gets_no_writer_call():
    sb = world()
    with wired(sb) as chat, patch.object(titles.settings, "HOLDOUT_PCT", 1.0):
        items = titles.preview(CH, 20)
    assert {i["arm"] for i in items} == {"holdout"} and not any(i["written"] for i in items)
    chat.assert_not_called()


def test_the_bakeoff_writes_no_row_and_its_csv_names_no_model(tmp_path):
    models = ["anthropic/claude-x", "google/gemini-y", "openai/gpt-z"]

    def chat(prompt, model=None, system=None, image_urls=None, label=None):
        return {"candidates": [{"title": "English only", "reason": model},
                               {"title": "ट्विंकल ट्विंकल", "reason": model}]}
    sb = world()
    out = tmp_path / "bake.csv"
    with wired(sb, chat=chat) as fake:
        title_bakeoff.main(["--channel", CH, "--n", "2", "--models", ",".join(models),
                            "--out", str(out), "--seed", "1"])
    assert sb.writes == []
    assert fake.call_count == 2 * 3
    text = out.read_text(encoding="utf-8")
    for m in models:
        assert m not in text and m.split("/")[0] not in text
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 6 and {r["video_id"] for r in rows} == {A, E}
    assert {r["candidate"] for r in rows} == {"ट्विंकल ट्विंकल"}
    assert all(r["checks"].startswith("pass") for r in rows)
    assert all(r["score_1_3"] == "" and r["wrong_or_broken_script"] == "" for r in rows)
    key = dict(csv.reader(title_bakeoff.key_path(out).open(encoding="utf-8")))
    assert key.pop("code") == "model" and sorted(key.values()) == models
    assert {r["code"] for r in rows} == set(key)


# ── review follow-ups ─────────────────────────────────────────────────────

def test_candidates_are_stripped_and_youtube_refused_characters_fail():
    sb = world()
    with wired(sb, chat=replies([f"  {MARATHI} \n"])):
        assert titles.pipeline(_video(A), cache_only=True).title == MARATHI
    for bad in ("ट्विंकल <3", "ट्विंकल > all", "ट्विंकल\nदुसरी ओळ"):
        assert titles.check(bad, video()).startswith("characters:")


def test_a_malformed_retry_still_gives_its_reason():
    sb = world()
    with wired(sb, chat=replies(["English only"], {})):
        written = titles.pipeline(_video(A), cache_only=True)
    assert written.title is None
    assert written.failures[-1] == f"attempt 2: {titles.MALFORMED}"
    assert [c["attempt"] for c in written.candidates] == [1]


def test_the_bakeoff_samples_past_the_pick_exclusions():
    """A video in a backlinks experiment never comes back to the pick, but is
    still a fair sample of the channel's titles for the bake-off."""
    sb = world()
    sb._tables["interventions"].append({
        "id": 1, "video_id": A, "channel_id": CH, "lever": "backlinks", "origin": "midas",
        "arm": "treated", "status": "measuring", "created_at": "2026-10-01T00:00:00+00:00",
        "applied_at": "2026-10-01T00:00:00+00:00"})
    with wired(sb):
        _, picked = titles.title_answers(CH, 20)
        _, sampled = titles.title_answers(CH, 20, pick=False)
    assert [v["id"] for v in picked] == [E]
    assert [v["id"] for v in sampled] == [A, E]


def test_the_csvs_escape_titles_a_spreadsheet_would_run(tmp_path):
    sb = world()
    for v in sb._tables["videos"]:
        v["title"] = "=HYPERLINK(1)"
    out = tmp_path / "bake.csv"
    with wired(sb, chat=replies(["ट्विंकल"], ["ट्विंकल"], ["ट्विंकल"], ["ट्विंकल"])):
        title_bakeoff.main(["--channel", CH, "--n", "2", "--models", "m/one",
                            "--out", str(out), "--seed", "1"])
        preview_titles.main(["--channel", CH, "--n", "2", "--csv", str(tmp_path / "p.csv")])
    for path in (out, tmp_path / "p.csv"):
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert rows and {r["current_title"] for r in rows} == {"'=HYPERLINK(1)"}
