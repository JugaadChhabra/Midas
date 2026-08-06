"""The audit suggestion contract — one type for what the LLM must return.

`audit_video` asks a model for a title/description/tags rewrite and persists
the result. That contract used to exist five times and never as a type: as
prose in `audits.DEFAULT_PROMPT`, again in `audits.elaborate`, again in
`reflection`'s house_format, as ad-hoc dict-poking in `audit_video`, and as a
re-validation from the flattened DB row in `validate_audit`. Nothing tied them
together, so the executable checks and the prompts could drift apart silently.

This module is the executable referent. It owns:

  * decoding — the model's documented shape plus the two malformed shapes it
    actually emits (a bare array, and `comparisons` as a list),
  * normalisation — the 15-hashtag ceiling, applied in the constructor so no
    path can produce an uncapped description,
  * validation — every ceiling the prompts quote as prose.

Normalisation happening at construction is the point. `_cap_description_hashtags`
used to run only at generate time, so the apply-time override path fed an
uncapped description to YouTube — which ignores *all* hashtags on a video
carrying more than 15, the exact failure the cap exists to prevent.

Validity is asked, not enforced: an invalid suggestion still constructs, so
callers can persist it and quarantine it (`reaudit_quarantined` reprocesses
those rows later). Refusing to build would delete that recovery path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The ceilings. Each is quoted as prose in DEFAULT_PROMPT, in elaborate()'s
# embedded copy, and in reflection's house_format; this is what those describe.
TITLE_MAX = 100                # YouTube's hard title limit
DESCRIPTION_MAX = 5000         # YouTube's hard description limit
TAGS_MAX = 30                  # house format: ~25-30 tags
TAGS_TOTAL_CHARS_MAX = 500     # YouTube's total tag-characters budget
HASHTAG_LIMIT = 15             # YouTube ignores ALL hashtags above 15

# Everything up to the next whitespace or '#'. NOT r"#\w+": \w excludes the
# combining marks in Devanagari and other Indic scripts, so "#मराठी" would match
# as "#मर" — truncating and miscounting exactly the regional hashtags the house
# format is built around.
_HASHTAG_RE = re.compile(r"#[^\s#]+")


def cap_description_hashtags(description: str | None, limit: int = HASHTAG_LIMIT) -> str | None:
    """Enforce YouTube's hashtag ceiling on a description.

    YouTube ignores ALL hashtags on a video that carries more than 15, so the
    house format asks for exactly 15 (3 above-title + 12 at the bottom). The LLM
    occasionally emits one or two extra, which would nullify every hashtag — hard
    cap here. Keeps the FIRST `limit` hashtags in document order (preserving the
    3 that surface above the title) and strips the rest, back-to-front so earlier
    match spans stay valid.
    """
    if not description:
        return description
    matches = list(_HASHTAG_RE.finditer(description))
    if len(matches) <= limit:
        return description
    out = description
    for m in reversed(matches[limit:]):
        out = out[: m.start()] + out[m.end():]
    # Tidy whitespace the removals leave behind (doubled spaces, trailing space).
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def _suggested(comparisons: dict, key: str) -> Any:
    return (comparisons.get(key) or {}).get("suggested")


@dataclass(frozen=True)
class AuditSuggestion:
    """A normalised title/description/tags rewrite, valid or not.

    Construct through `from_llm`, `from_audit_row`, or `from_fields` — never
    directly, so normalisation always runs.
    """

    title: str | None
    description: str | None
    tags: list
    comparisons: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    reasoning: str | None = None

    # ── construction ──────────────────────────────────────────────────────

    @classmethod
    def _make(cls, *, title, description, tags, comparisons=None, issues=None,
              reasoning=None) -> "AuditSuggestion":
        return cls(
            title=title,
            description=cap_description_hashtags(description),
            # A non-list `tags` is left alone rather than coerced: silently
            # splitting a string would invent data and hide a malformed
            # response that rejection() is meant to catch.
            tags=tags if isinstance(tags, list) else (tags if tags is not None else []),
            comparisons=comparisons or {},
            issues=issues or [],
            reasoning=reasoning,
        )

    @classmethod
    def from_llm(cls, raw: Any) -> "AuditSuggestion":
        """Decode one `chat_json` result. Never raises — ask `rejection()`."""
        if isinstance(raw, list):
            # Some models return a bare JSON array (usually the issues list)
            # instead of the documented object shape.
            raw = {"issues": raw, "comparisons": {}}
        if not isinstance(raw, dict):
            raw = {}

        comparisons = raw.get("comparisons") or {}
        if isinstance(comparisons, list):
            # Models sometimes emit comparisons as [{field, ...}, ...].
            comparisons = {
                (c.get("field") or "").lower(): c
                for c in comparisons if isinstance(c, dict)
            }
        if not isinstance(comparisons, dict):
            comparisons = {}

        return cls._make(
            title=_suggested(comparisons, "title"),
            description=_suggested(comparisons, "description"),
            tags=_suggested(comparisons, "tags") or [],
            comparisons=comparisons,
            issues=raw.get("issues") or [],
            reasoning=raw.get("reasoning"),
        )

    @classmethod
    def from_audit_row(cls, row: dict) -> "AuditSuggestion":
        """Rebuild from a persisted `audits` row (the flattened column shape)."""
        issues_found = row.get("issues_found") or {}
        return cls._make(
            title=row.get("suggested_title"),
            description=row.get("suggested_description"),
            tags=row.get("suggested_tags") or [],
            comparisons=issues_found.get("comparisons") or {},
            issues=issues_found.get("issues") or [],
            reasoning=row.get("ai_reasoning"),
        )

    @classmethod
    def from_fields(cls, *, title=None, description=None, tags=None) -> "AuditSuggestion":
        """Build from explicit values — the apply-time override path.

        Routing overrides through here is what stops a caller-supplied
        description reaching YouTube with more than HASHTAG_LIMIT hashtags.
        """
        return cls._make(title=title, description=description,
                         tags=tags if tags is not None else [])

    # ── validation ────────────────────────────────────────────────────────

    def rejection(self) -> str | None:
        """None if this is safe to apply, else why not.

        Reason strings are appended to `audits.ai_reasoning` on quarantine, so
        they are user-visible text; they are kept identical to the ones this
        replaced.
        """
        title = (self.title or "").strip()
        if not title or len(title) > TITLE_MAX:
            return f"title empty or >{TITLE_MAX} chars"
        desc = self.description or ""
        if not desc or len(desc) > DESCRIPTION_MAX:
            return f"description empty or >{DESCRIPTION_MAX} chars"
        if not isinstance(self.tags, list) or not all(isinstance(t, str) for t in self.tags):
            return "tags not a list of strings"
        if len(self.tags) > TAGS_MAX:
            return f">{TAGS_MAX} tags"
        if sum(len(t) for t in self.tags) > TAGS_TOTAL_CHARS_MAX:
            return f"tags total chars >{TAGS_TOTAL_CHARS_MAX}"
        return None

    @property
    def is_valid(self) -> bool:
        return self.rejection() is None

    # ── persistence ───────────────────────────────────────────────────────

    def to_audit_row(self) -> dict:
        """The `audits` columns this suggestion owns. Callers add the rest."""
        return {
            "suggested_title": self.title,
            "suggested_description": self.description,
            "suggested_tags": self.tags if isinstance(self.tags, list) else [],
            "issues_found": {"comparisons": self.comparisons, "issues": self.issues},
            "ai_reasoning": self.reasoning,
        }
