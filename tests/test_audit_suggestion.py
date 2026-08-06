"""One type owns the LLM audit contract.

Before this, the contract existed five times and none of them was a type:
prose in DEFAULT_PROMPT, prose again in elaborate(), prose again in
reflection's house_format, ad-hoc dict-poking in audit_video, and a
re-validation from the flattened DB row hours later in validate_audit.

The concrete cost: _cap_description_hashtags enforced the 15-hashtag
ceiling at GENERATE time only, so the apply-time override path
(`(body and body.description) or audit["suggested_description"]`) sent an
uncapped description straight to YouTube — the exact failure the function
exists to prevent, since YouTube ignores ALL hashtags above 15.

Normalisation now happens in the constructor, so every path that produces
a suggestion is capped, and every ceiling has one executable home.
"""
import pytest

from app.audit_suggestion import (
    DESCRIPTION_MAX,
    HASHTAG_LIMIT,
    TAGS_MAX,
    TAGS_TOTAL_CHARS_MAX,
    TITLE_MAX,
    AuditSuggestion,
)


def _llm(title="A title", description="Desc", tags=None, **kw):
    return {
        "comparisons": {
            "title": {"suggested": title},
            "description": {"suggested": description},
            "tags": {"suggested": tags if tags is not None else ["a", "b"]},
        },
        "issues": [{"field": "title", "severity": "low"}],
        "reasoning": "because",
        **kw,
    }


# ── decoding the LLM's many shapes ────────────────────────────────────────

def test_decodes_the_documented_shape():
    s = AuditSuggestion.from_llm(_llm())
    assert s.title == "A title"
    assert s.description == "Desc"
    assert s.tags == ["a", "b"]
    assert s.reasoning == "because"
    assert s.issues == [{"field": "title", "severity": "low"}]


def test_decodes_a_bare_list_as_the_issues_array():
    """Some models return a bare JSON array instead of the object shape."""
    s = AuditSuggestion.from_llm([{"field": "title", "problem": "x"}])
    assert s.issues == [{"field": "title", "problem": "x"}]
    assert s.title is None and s.description is None and s.tags == []


def test_decodes_comparisons_emitted_as_a_list():
    raw = {"comparisons": [
        {"field": "Title", "suggested": "T"},
        {"field": "tags", "suggested": ["x"]},
    ]}
    s = AuditSuggestion.from_llm(raw)
    assert s.title == "T"
    assert s.tags == ["x"]


def test_missing_comparisons_do_not_raise():
    s = AuditSuggestion.from_llm({})
    assert s.title is None
    assert s.tags == []
    assert s.rejection() is not None


def test_non_list_tags_are_not_coerced_into_a_lie():
    """A string where a list belongs must fail validation, not silently split."""
    s = AuditSuggestion.from_llm(_llm(tags="a,b,c"))
    assert s.rejection() == "tags not a list of strings"


# ── normalisation: the hashtag ceiling ────────────────────────────────────

def _desc_with(n):
    return "line one\n" + " ".join(f"#tag{i}" for i in range(n))


def test_description_is_capped_at_construction():
    s = AuditSuggestion.from_llm(_llm(description=_desc_with(20)))
    assert s.description.count("#") == HASHTAG_LIMIT


def test_cap_keeps_the_first_hashtags_in_document_order():
    """The first 3 surface above the title — they must survive."""
    s = AuditSuggestion.from_llm(_llm(description=_desc_with(20)))
    assert "#tag0" in s.description and "#tag2" in s.description
    assert "#tag19" not in s.description


def test_a_compliant_description_is_untouched():
    d = _desc_with(HASHTAG_LIMIT)
    assert AuditSuggestion.from_llm(_llm(description=d)).description == d


def test_cap_applies_to_every_construction_path():
    """The apply-time override path used to bypass the cap entirely."""
    over = AuditSuggestion.from_fields(title="t", description=_desc_with(30), tags=["a"])
    assert over.description.count("#") == HASHTAG_LIMIT

    row = AuditSuggestion.from_audit_row({
        "suggested_title": "t",
        "suggested_description": _desc_with(30),
        "suggested_tags": ["a"],
    })
    assert row.description.count("#") == HASHTAG_LIMIT


# ── validation: one executable home for the ceilings ──────────────────────

@pytest.mark.parametrize("kw,reason", [
    ({"title": ""}, "title empty or >100 chars"),
    ({"title": "x" * (TITLE_MAX + 1)}, "title empty or >100 chars"),
    ({"description": ""}, "description empty or >5000 chars"),
    ({"description": "x" * (DESCRIPTION_MAX + 1)}, "description empty or >5000 chars"),
    ({"tags": ["t"] * (TAGS_MAX + 1)}, ">30 tags"),
    ({"tags": ["x" * 60] * 10}, "tags total chars >500"),
])
def test_rejection_reasons(kw, reason):
    assert AuditSuggestion.from_llm(_llm(**kw)).rejection() == reason


def test_a_good_suggestion_has_no_rejection():
    s = AuditSuggestion.from_llm(_llm())
    assert s.rejection() is None
    assert s.is_valid


def test_ceilings_are_defined_once():
    """These numbers are quoted as prose in three prompts; this is the referent."""
    assert (TITLE_MAX, DESCRIPTION_MAX, TAGS_MAX, TAGS_TOTAL_CHARS_MAX, HASHTAG_LIMIT) \
        == (100, 5000, 30, 500, 15)


# ── round-tripping through the persisted row ──────────────────────────────

def test_row_round_trip_preserves_the_verdict():
    s = AuditSuggestion.from_llm(_llm(title="x" * (TITLE_MAX + 1)))
    back = AuditSuggestion.from_audit_row(s.to_audit_row())
    assert back.rejection() == s.rejection()


def test_to_audit_row_emits_the_persisted_column_names():
    row = AuditSuggestion.from_llm(_llm()).to_audit_row()
    assert set(row) == {
        "suggested_title", "suggested_description", "suggested_tags",
        "issues_found", "ai_reasoning",
    }
    assert row["issues_found"]["comparisons"]["title"]["suggested"] == "A title"


def test_hashtag_matching_handles_indic_scripts():
    """r"#\\w+" truncates "#मराठी" to "#मर" — \\w drops Devanagari combining marks.

    The house format is built around regional-language hashtags, so the counter
    must see them whole or it both miscounts and corrupts them.
    """
    desc = "#मराठी #बालगीत #tag-name #tag.name " + " ".join(f"#t{i}" for i in range(20))
    s = AuditSuggestion.from_llm(_llm(description=desc))
    assert "#मराठी" in s.description        # not truncated to "#मर"
    assert "#बालगीत" in s.description
    assert "#tag-name" in s.description     # hyphen is part of the tag
    assert len([c for c in s.description if c == "#"]) == HASHTAG_LIMIT
