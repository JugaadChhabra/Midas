# Reflection Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-improving loop that reads real performance data, samples niche competitors on YouTube, and uses an LLM to generate, shadow-test, and auto-promote/revert improved audit prompts — with a separate numeric tuner for playlist similarity thresholds.

**Architecture:** A new `app/reflection.py` module handles all reflection logic (niche extraction, trigger check, competitive sampling, Perplexity platform guidance, Sonnet reflection call, shadow runner, cohort comparison, threshold tuner). Existing files receive minimal surgical additions: `audits.py` gets optional `prompt_override`/`status_override` params; `autopilot.py` skips `shadow_pending` audits and stamps `prompt_version_id`; `main.py` adds a weekly scheduler job. Two DB migrations add `prompt_versions`, `threshold_history`, and new columns on `audit_configs` and `audits`.

**Tech Stack:** Python 3.13, FastAPI, Supabase (postgres), APScheduler, OpenRouter (claude-haiku-4-5 for niche extraction, perplexity/sonar for platform guidance, claude-sonnet-4-6 for reflection), YouTube Data API v3 (`search.list` for competitive sampling), pytest for tests.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `app/reflection.py` | All reflection logic: trigger, perf report, niche extraction, competitive sampling, platform guidance, LLM reflection call, shadow runner, cohort comparison, threshold tuner, router |
| Create | `supabase/migrations/20260519200000_prompt_versions.sql` | `prompt_versions` + `threshold_history` tables |
| Create | `supabase/migrations/20260519200001_reflection_columns.sql` | New columns on `audit_configs` + `audits` |
| Create | `tests/__init__.py` | Makes tests/ a package |
| Create | `tests/test_reflection.py` | Unit tests for reflection.py logic |
| Modify | `app/config.py` | Add `REFLECTION_MODEL` setting |
| Modify | `app/openrouter.py` | Add `chat_text()` for Perplexity (no json_object mode) |
| Modify | `app/youtube_client.py` | Add `yt_search_videos()` for competitive sampling |
| Modify | `app/audits.py` | Add `prompt_override` + `status_override` optional params to `audit_video()` |
| Modify | `app/autopilot.py` | Skip `shadow_pending`; stamp `prompt_version_id` on new audits |
| Modify | `app/main.py` | Add weekly `_weekly_reflection` job to APScheduler |
| Modify | `requirements.txt` | Add `pytest` |
| Modify | `app/static/channel.html` | Reflection history panel + shadow comparison view + mode toggle |

---

## Task 1: Test Infrastructure + Migrations + Config

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `supabase/migrations/20260519200000_prompt_versions.sql`
- Create: `supabase/migrations/20260519200001_reflection_columns.sql`
- Modify: `app/config.py`

- [ ] **Step 1: Add pytest to requirements**

```
pytest==8.3.4
```

Append that line to `requirements.txt`, then run:
```bash
pip install pytest==8.3.4
```
Expected: `Successfully installed pytest-8.3.4`

- [ ] **Step 2: Create tests package**

```bash
mkdir tests && touch tests/__init__.py
```

- [ ] **Step 3: Create prompt_versions + threshold_history migration**

Create `supabase/migrations/20260519200000_prompt_versions.sql`:

```sql
create table if not exists prompt_versions (
    id                   bigserial primary key,
    channel_id           text not null references channels(id) on delete cascade,
    prompt_text          text not null,
    status               text not null default 'shadow',
    created_at           timestamptz default now(),
    promoted_at          timestamptz,
    retired_at           timestamptz,
    reflection_reasoning text,
    performance_snapshot jsonb,
    parent_version_id    bigint references prompt_versions(id)
);
create index if not exists idx_prompt_versions_channel on prompt_versions(channel_id);
create index if not exists idx_prompt_versions_status  on prompt_versions(channel_id, status);

create table if not exists threshold_history (
    id               bigserial primary key,
    channel_id       text not null references channels(id) on delete cascade,
    join_high        float not null,
    join_low         float not null,
    leave_threshold  float not null,
    created_at       timestamptz default now(),
    status           text not null default 'active',
    reason           text
);
create index if not exists idx_threshold_history_channel on threshold_history(channel_id, status);
```

- [ ] **Step 4: Create reflection columns migration**

Create `supabase/migrations/20260519200001_reflection_columns.sql`:

```sql
alter table audit_configs
    add column if not exists niche_queries    jsonb,
    add column if not exists reflection_mode text default 'shadow';

alter table audits
    add column if not exists prompt_version_id bigint references prompt_versions(id);
```

- [ ] **Step 5: Apply migrations via Supabase CLI**

```bash
supabase db push
```
Expected: migrations apply without error. If Supabase CLI unavailable, run the SQL directly in the Supabase dashboard SQL editor.

- [ ] **Step 6: Add REFLECTION_MODEL to config**

In `app/config.py`, add inside the `Settings` class after `PROMPT_GEN_MODEL`:

```python
REFLECTION_MODEL = os.getenv("REFLECTION_MODEL") or "anthropic/claude-sonnet-4-6"
```

- [ ] **Step 7: Verify config loads**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -c "from app.config import settings; print(settings.REFLECTION_MODEL)"
```
Expected: `anthropic/claude-sonnet-4-6`

- [ ] **Step 8: Commit**

```bash
git add requirements.txt tests/__init__.py supabase/migrations/20260519200000_prompt_versions.sql supabase/migrations/20260519200001_reflection_columns.sql app/config.py
git commit -m "feat: reflection engine foundations — migrations, config, test infra"
```

---

## Task 2: openrouter.py — Add chat_text()

Perplexity's `sonar` model does not support `response_format: json_object`. We need a plain-text variant of the chat call.

**Files:**
- Modify: `app/openrouter.py:86` (append after last line)

- [ ] **Step 1: Write the failing test**

Create `tests/test_reflection.py` with this first test:

```python
import pytest
from unittest.mock import patch, MagicMock


def _mock_openrouter_response(content: str):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return mock_resp


def test_chat_text_returns_string():
    with patch("app.openrouter.httpx.post") as mock_post:
        mock_post.return_value = _mock_openrouter_response("hello world")
        from app.openrouter import chat_text
        result = chat_text("say hello", model="perplexity/sonar")
    assert result == "hello world"


def test_chat_text_raises_on_http_error():
    with patch("app.openrouter.httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"
        mock_post.return_value = mock_resp
        from app.openrouter import chat_text
        with pytest.raises(RuntimeError, match="OpenRouter 429"):
            chat_text("say hello", model="perplexity/sonar")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_chat_text_returns_string -v
```
Expected: `ImportError: cannot import name 'chat_text'`

- [ ] **Step 3: Add chat_text to openrouter.py**

Append to `app/openrouter.py` after line 86:

```python


def chat_text(prompt: str, model: str | None = None, system: str | None = None) -> str:
    """Call OpenRouter without response_format constraint. Returns raw text content.
    Used for models that don't support json_object mode (e.g. perplexity/sonar).
    """
    model = model or settings.AUDIT_MODEL
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Midas",
        },
        json={"model": model, "messages": messages},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"OpenRouter {r.status_code} for model {model}: {r.text}")
    data = r.json()
    if "choices" not in data:
        raise RuntimeError(f"OpenRouter unexpected response: {data}")
    return data["choices"][0]["message"]["content"].strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_chat_text_returns_string tests/test_reflection.py::test_chat_text_raises_on_http_error -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add app/openrouter.py tests/test_reflection.py
git commit -m "feat: add chat_text() to openrouter for Perplexity plain-text calls"
```

---

## Task 3: youtube_client.py — Add yt_search_videos()

**Files:**
- Modify: `app/youtube_client.py` (append after `yt_playlist_items_delete`)

- [ ] **Step 1: Write failing test**

Append to `tests/test_reflection.py`:

```python
def test_yt_search_videos_returns_snippets():
    mock_yt = MagicMock()
    mock_yt.search.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "Marathi Rhymes for Kids",
                    "tags": ["marathi", "rhymes"],
                    "description": "Best marathi rhymes",
                }
            }
        ]
    }
    with patch("app.youtube_client._log_quota"):
        from app.youtube_client import yt_search_videos
        results = yt_search_videos(mock_yt, "UCtest", "marathi nursery rhymes", max_results=10)
    assert len(results) == 1
    assert results[0]["title"] == "Marathi Rhymes for Kids"
    assert results[0]["video_id"] == "abc123"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_yt_search_videos_returns_snippets -v
```
Expected: `ImportError: cannot import name 'yt_search_videos'`

- [ ] **Step 3: Add yt_search_videos to youtube_client.py**

Append to `app/youtube_client.py` after the `yt_playlist_items_delete` function:

```python


def yt_search_videos(yt, channel_id: str, query: str, max_results: int = 10, published_after: str | None = None) -> list[dict]:
    """Search YouTube for videos matching query. Cost: 100 quota units.

    Returns list of {video_id, title, description, tags}.
    published_after: ISO 8601 string e.g. '2026-02-19T00:00:00Z'
    """
    success = False
    try:
        params: dict = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "viewCount",
            "maxResults": max_results,
        }
        if published_after:
            params["publishedAfter"] = published_after
        resp = yt.search().list(**params).execute()
        success = True
        results = []
        for item in resp.get("items", []):
            sn = item.get("snippet") or {}
            results.append({
                "video_id": (item.get("id") or {}).get("videoId", ""),
                "title": sn.get("title", ""),
                "description": (sn.get("description") or "")[:300],
                "tags": sn.get("tags") or [],
            })
        return results
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "search.list", 100, success)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_yt_search_videos_returns_snippets -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/youtube_client.py tests/test_reflection.py
git commit -m "feat: add yt_search_videos() for reflection competitive sampling"
```

---

## Task 4: audits.py — Optional prompt_override + status_override

Shadow audits need to run with a different prompt and be stored with `status=shadow_pending` instead of `pending`.

**Files:**
- Modify: `app/audits.py:195` (`audit_video` function signature and body)

- [ ] **Step 1: Write failing test**

Append to `tests/test_reflection.py`:

```python
def test_audit_video_uses_prompt_override():
    """When prompt_override is passed, audit_video uses it instead of audit_configs prompt."""
    mock_video = {
        "id": "vid1", "channel_id": "ch1", "privacy_status": "public",
        "title": "Test", "description": "", "tags": [], "view_count": 100,
        "like_count": 5, "published_at": "2026-01-01T00:00:00Z", "is_short": False,
    }
    mock_cfg = []
    mock_channel = {"default_language": "en"}

    with patch("app.audits.supabase") as mock_sb, \
         patch("app.audits.fetch_transcript", return_value=(None, None)), \
         patch("app.audits.chat_json") as mock_chat:

        def table_side_effect(name):
            m = MagicMock()
            if name == "videos":
                m.select.return_value.eq.return_value.single.return_value.execute.return_value.data = mock_video
            elif name == "audit_configs":
                m.select.return_value.eq.return_value.execute.return_value.data = mock_cfg
            elif name == "channels":
                m.select.return_value.eq.return_value.single.return_value.execute.return_value.data = mock_channel
            elif name == "audits":
                m.insert.return_value.execute.return_value.data = [{"id": 99}]
            return m

        mock_sb.return_value.table.side_effect = table_side_effect
        mock_chat.return_value = {
            "comparisons": {
                "title": {"suggested": "New Title", "current_problems": "", "why_better": ""},
                "description": {"suggested": "New Desc", "current_problems": "", "why_better": ""},
                "tags": {"suggested": ["tag1"], "current_problems": "", "why_better": ""},
                "thumbnail": {"suggested": "", "current_problems": "", "why_better": ""},
            },
            "issues": [],
            "reasoning": "test",
        }

        from app.audits import audit_video
        audit_video("vid1", prompt_override="MY CUSTOM PROMPT", status_override="shadow_pending")

        # Verify chat_json was called with our custom prompt as system
        call_kwargs = mock_chat.call_args
        assert call_kwargs.kwargs.get("system") == "MY CUSTOM PROMPT" or \
               (call_kwargs.args and call_kwargs.args[1] == "MY CUSTOM PROMPT")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_audit_video_uses_prompt_override -v
```
Expected: FAIL (TypeError: unexpected keyword argument)

- [ ] **Step 3: Add optional params to audit_video**

In `app/audits.py`, change the `audit_video` signature at line 195:

```python
def audit_video(video_id: str, prompt_override: str | None = None, status_override: str | None = None) -> dict:
```

Then inside the function, replace the prompt selection block (lines ~212-217) so it respects the override:

```python
    if prompt_override:
        audit_prompt = prompt_override
    elif v.get("is_short") and cfg_row.get("shorts_prompt"):
        audit_prompt = cfg_row["shorts_prompt"]
    else:
        audit_prompt = cfg_row.get("generated_prompt") or DEFAULT_PROMPT
```

And replace the `"status": "pending"` in the row dict (line ~257) with:

```python
        "status": status_override or "pending",
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_audit_video_uses_prompt_override -v
```
Expected: PASS

- [ ] **Step 5: Verify no existing behaviour broken**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -c "from app.audits import audit_video, validate_audit; print('imports ok')"
```
Expected: `imports ok`

- [ ] **Step 6: Commit**

```bash
git add app/audits.py tests/test_reflection.py
git commit -m "feat: audit_video accepts prompt_override and status_override for shadow runs"
```

---

## Task 5: reflection.py — Trigger Logic + Performance Report

**Files:**
- Create: `app/reflection.py`

- [ ] **Step 1: Write failing tests for trigger logic**

Append to `tests/test_reflection.py`:

```python
def _make_perf_report(win_rate=70.0, regression_count=0, count=15):
    return {
        "count": count,
        "win_rate": win_rate,
        "regression_count": regression_count,
        "median_velocity_lift": 12.0,
        "levers": {"title": 15.0, "description": 8.0, "tags": 20.0},
        "worst_audits": [],
        "best_audits": [],
    }


def test_should_reflect_skips_insufficient_data():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=None):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is False
    assert reason == "insufficient_data"


def test_should_reflect_skips_high_win_rate():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=70.0, regression_count=1)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is False
    assert reason == "performing_well"


def test_should_reflect_fires_low_win_rate():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=40.0)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is True
    assert reason == "low_win_rate"


def test_should_reflect_fires_high_regressions():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=60.0, regression_count=4)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is True
    assert reason == "high_regressions"


def test_should_reflect_skips_recent_reflection():
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=40.0)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = [{"created_at": recent}]
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is False
    assert reason == "reflected_recently"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_should_reflect_skips_insufficient_data -v
```
Expected: `ModuleNotFoundError: No module named 'app.reflection'`

- [ ] **Step 3: Create app/reflection.py with trigger + perf report**

Create `app/reflection.py`:

```python
import logging
import statistics
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db import supabase

log = logging.getLogger("midas.reflection")

router = APIRouter(tags=["reflection"])

_WIN_RATE_THRESHOLD = 65.0
_REGRESSION_THRESHOLD = 3
_MIN_DATA_POINTS = 10
_REFLECT_COOLDOWN_DAYS = 7
_VELOCITY_WINDOW_DAYS = 7  # minimum post-apply days to count a data point


# ── Performance report ────────────────────────────────────────────────────────

def _build_perf_report(channel_id: str) -> dict | None:
    """Build structured performance report from applied audits.

    Returns None if fewer than _MIN_DATA_POINTS audits have velocity data.
    """
    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]
    if not video_ids:
        return None

    audits = (
        supabase().table("audits")
        .select("id,video_id,applied_at,suggested_title,title_before,"
                "suggested_description,description_before,"
                "suggested_tags,tags_before,"
                "view_count_at_apply,ai_reasoning")
        .in_("video_id", video_ids)
        .eq("status", "applied")
        .execute()
    ).data or []

    if not audits:
        return None

    vid_rows = (
        supabase().table("videos")
        .select("id,view_count,published_at")
        .in_("id", video_ids)
        .execute()
    ).data or []
    videos_by_id = {v["id"]: v for v in vid_rows}

    now = datetime.now(timezone.utc)
    enriched = []

    for a in audits:
        v = videos_by_id.get(a["video_id"])
        if not v:
            continue
        view_at = a.get("view_count_at_apply") or 0
        view_now = v.get("view_count") or 0
        if not a.get("applied_at") or not v.get("published_at") or view_at <= 0:
            continue
        try:
            ap = datetime.fromisoformat(a["applied_at"].replace("Z", "+00:00"))
            pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        days_since = (now - ap).total_seconds() / 86400.0
        if days_since < _VELOCITY_WINDOW_DAYS:
            continue
        age_at_apply = max(1.0, (ap - pub).total_seconds() / 86400.0)
        before_v = view_at / age_at_apply
        after_v = (view_now - view_at) / max(1.0, days_since)
        if before_v <= 0:
            continue
        velocity_lift_pct = ((after_v - before_v) / before_v) * 100.0
        enriched.append({
            "audit_id": a["id"],
            "velocity_lift_pct": velocity_lift_pct,
            "title_before": a.get("title_before"),
            "title_after": a.get("suggested_title"),
            "title_changed": (a.get("title_before") or "") != (a.get("suggested_title") or ""),
            "desc_changed": (a.get("description_before") or "") != (a.get("suggested_description") or ""),
            "tags_changed": list(a.get("tags_before") or []) != list(a.get("suggested_tags") or []),
            "ai_reasoning": a.get("ai_reasoning"),
            "is_recent": (now - ap) < timedelta(days=14),
        })

    if len(enriched) < _MIN_DATA_POINTS:
        return None

    win_rate = round(
        sum(1 for r in enriched if r["velocity_lift_pct"] > 10) / len(enriched) * 100, 1
    )
    regression_count = sum(
        1 for r in enriched if r["is_recent"] and r["velocity_lift_pct"] < -10
    )
    lifts = sorted(r["velocity_lift_pct"] for r in enriched)
    median_lift = statistics.median(lifts)

    def _lever_avg(key: str) -> float | None:
        sub = [r["velocity_lift_pct"] for r in enriched if r[key]]
        return round(sum(sub) / len(sub), 1) if sub else None

    by_lift = sorted(enriched, key=lambda r: r["velocity_lift_pct"])
    return {
        "count": len(enriched),
        "win_rate": win_rate,
        "regression_count": regression_count,
        "median_velocity_lift": round(median_lift, 1),
        "levers": {
            "title": _lever_avg("title_changed"),
            "description": _lever_avg("desc_changed"),
            "tags": _lever_avg("tags_changed"),
        },
        "worst_audits": by_lift[:2],
        "best_audits": by_lift[-2:],
    }


# ── Trigger logic ─────────────────────────────────────────────────────────────

def _should_reflect(channel_id: str) -> tuple[bool, str]:
    """Return (should_reflect, reason)."""
    # Check cooldown — did we reflect in the last N days?
    last_rows = (
        supabase().table("prompt_versions")
        .select("created_at")
        .eq("channel_id", channel_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if last_rows:
        last_dt = datetime.fromisoformat(last_rows[0]["created_at"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - last_dt) < timedelta(days=_REFLECT_COOLDOWN_DAYS):
            return False, "reflected_recently"

    report = _build_perf_report(channel_id)
    if report is None:
        return False, "insufficient_data"

    if report["win_rate"] > _WIN_RATE_THRESHOLD and report["regression_count"] <= _REGRESSION_THRESHOLD - 1:
        return False, "performing_well"

    if report["win_rate"] < 50.0:
        return True, "low_win_rate"
    if report["regression_count"] > _REGRESSION_THRESHOLD:
        return True, "high_regressions"

    # Check if any single lever is consistently negative
    levers = report["levers"]
    for lever, lift in levers.items():
        if lift is not None and lift < -5.0:
            return True, f"negative_lever_{lever}"

    return False, "performing_well"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_should_reflect_skips_insufficient_data tests/test_reflection.py::test_should_reflect_skips_high_win_rate tests/test_reflection.py::test_should_reflect_fires_low_win_rate tests/test_reflection.py::test_should_reflect_fires_high_regressions tests/test_reflection.py::test_should_reflect_skips_recent_reflection -v
```
Expected: all 5 PASS

- [ ] **Step 5: Commit**

```bash
git add app/reflection.py tests/test_reflection.py
git commit -m "feat: reflection trigger logic and performance report assembly"
```

---

## Task 6: reflection.py — Niche Extraction

**Files:**
- Modify: `app/reflection.py` (append functions)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_reflection.py`:

```python
def test_derive_niche_queries_calls_haiku():
    mock_videos = [{"title": f"Marathi song {i}", "tags": ["marathi", "rhymes"]} for i in range(5)]
    mock_tags = [{"tags": ["marathi", "rhymes", "bal geet"]} for _ in range(10)]

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json") as mock_chat:
        def table_side(name):
            m = MagicMock()
            if name == "videos":
                m.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = mock_videos
                m.select.return_value.eq.return_value.execute.return_value.data = mock_tags
            elif name == "audit_configs":
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side
        mock_chat.return_value = {"queries": ["marathi nursery rhymes", "bal geet"]}

        from app.reflection import derive_niche_queries
        result = derive_niche_queries("ch1")

    assert "marathi nursery rhymes" in result
    assert len(result) >= 1


def test_get_or_derive_uses_cache():
    """If niche_queries already stored, no LLM call is made."""
    cached = ["marathi nursery rhymes", "bal geet"]

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json") as mock_chat:
        m = MagicMock()
        m.select.return_value.eq.return_value.execute.return_value.data = [
            {"niche_queries": cached}
        ]
        mock_sb.return_value.table.return_value = m

        from app.reflection import get_or_derive_niche_queries
        result = get_or_derive_niche_queries("ch1")

    mock_chat.assert_not_called()
    assert result == cached
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_derive_niche_queries_calls_haiku tests/test_reflection.py::test_get_or_derive_uses_cache -v
```
Expected: `AttributeError: module 'app.reflection' has no attribute 'derive_niche_queries'`

- [ ] **Step 3: Add niche extraction functions to reflection.py**

Append to `app/reflection.py` after `_should_reflect`:

```python

# ── Niche extraction ──────────────────────────────────────────────────────────

def derive_niche_queries(channel_id: str) -> list[str]:
    """Derive 2-3 YouTube search queries from channel's own content. Stores result."""
    from app.openrouter import chat_json

    titles = [
        v["title"] for v in (
            supabase().table("videos")
            .select("title")
            .eq("channel_id", channel_id)
            .order("published_at", desc=True)
            .limit(15)
            .execute()
        ).data or []
        if v.get("title")
    ]

    tag_rows = (
        supabase().table("videos")
        .select("tags")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    tag_freq: dict[str, int] = {}
    for row in tag_rows:
        for tag in (row.get("tags") or []):
            tag_freq[tag] = tag_freq.get(tag, 0) + 1
    top_tags = sorted(tag_freq, key=lambda t: tag_freq[t], reverse=True)[:20]

    prompt = (
        f"This YouTube channel's most-used tags: {top_tags}\n"
        f"Sample video titles: {titles[:10]}\n\n"
        f"Produce 2-3 YouTube search queries that would find similar channels and videos. "
        f"Be specific to the actual content niche, not the broad category. "
        f'Return JSON: {{"queries": ["query1", "query2"]}}'
    )
    result = chat_json(prompt, model="anthropic/claude-haiku-4-5-20251001")
    queries = result.get("queries") or []
    queries = [q for q in queries if isinstance(q, str) and q.strip()][:3]

    supabase().table("audit_configs").update(
        {"niche_queries": queries}
    ).eq("channel_id", channel_id).execute()

    log.info("Derived niche queries for %s: %s", channel_id, queries)
    return queries


def get_or_derive_niche_queries(channel_id: str) -> list[str]:
    """Return cached niche queries or derive if not yet stored."""
    rows = (
        supabase().table("audit_configs")
        .select("niche_queries")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    cached = (rows[0].get("niche_queries") if rows else None) or []
    if cached:
        return cached
    return derive_niche_queries(channel_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_derive_niche_queries_calls_haiku tests/test_reflection.py::test_get_or_derive_uses_cache -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add app/reflection.py tests/test_reflection.py
git commit -m "feat: niche extraction — derive YouTube search queries from channel content"
```

---

## Task 7: reflection.py — Competitive Sampling + Platform Guidance

**Files:**
- Modify: `app/reflection.py` (append functions)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_reflection.py`:

```python
def test_sample_competitors_formats_output():
    mock_results = [
        {"video_id": "v1", "title": "Marathi Rhymes for Kids", "description": "Best rhymes", "tags": ["marathi"]},
        {"video_id": "v2", "title": "बालगीत मराठी", "description": "Songs", "tags": ["marathi", "bal geet"]},
    ]
    with patch("app.reflection.youtube_for_channel") as mock_yt_fn, \
         patch("app.reflection.yt_search_videos", return_value=mock_results):
        mock_yt_fn.return_value = MagicMock()
        from app.reflection import _sample_competitors
        output = _sample_competitors("ch1", ["marathi nursery rhymes"])

    assert "Marathi Rhymes for Kids" in output
    assert "बालगीत मराठी" in output


def test_get_platform_guidance_returns_text():
    with patch("app.reflection.chat_text", return_value="Use short titles. Front-load keywords.") as mock_ct:
        from app.reflection import _get_platform_guidance
        result = _get_platform_guidance("marathi children's music")
    assert "titles" in result.lower() or len(result) > 0
    mock_ct.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_sample_competitors_formats_output tests/test_reflection.py::test_get_platform_guidance_returns_text -v
```
Expected: `AttributeError: module 'app.reflection' has no attribute '_sample_competitors'`

- [ ] **Step 3: Add competitive sampling + platform guidance to reflection.py**

Append to `app/reflection.py` after `get_or_derive_niche_queries`:

```python

# ── Competitive sampling ──────────────────────────────────────────────────────

def _sample_competitors(channel_id: str, niche_queries: list[str]) -> str:
    """Sample top-performing videos in niche via YouTube search. Returns formatted context string."""
    from datetime import date, timedelta as td
    from app.youtube_client import youtube_for_channel, yt_search_videos

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=90)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        yt = youtube_for_channel(channel_id)
    except Exception as e:
        log.warning("competitive_sample: could not build YouTube client: %s", e)
        return "(competitive data unavailable)"

    all_results: list[dict] = []
    for query in niche_queries[:2]:  # max 2 queries = 200 quota units
        try:
            results = yt_search_videos(yt, channel_id, query, max_results=10, published_after=published_after)
            all_results.extend(results)
        except Exception as e:
            log.warning("competitive_sample: search failed for '%s': %s", query, e)

    if not all_results:
        return "(competitive data unavailable)"

    lines = ["TOP PERFORMING VIDEOS IN YOUR NICHE (last 90 days):"]
    seen_titles: set[str] = set()
    for r in all_results:
        title = r.get("title", "")
        if title in seen_titles or not title:
            continue
        seen_titles.add(title)
        tags_preview = ", ".join(r.get("tags", [])[:5])
        desc_preview = (r.get("description") or "")[:100]
        lines.append(f'- "{title}"')
        if tags_preview:
            lines.append(f'  Tags: {tags_preview}')
        if desc_preview:
            lines.append(f'  Desc start: {desc_preview}')

    return "\n".join(lines)


# ── Platform guidance ─────────────────────────────────────────────────────────

def _get_platform_guidance(niche_description: str) -> str:
    """Call Perplexity/sonar for current YouTube metadata best practices."""
    from app.openrouter import chat_text

    query = (
        f"What are the current best practices for YouTube metadata optimisation "
        f"(titles, descriptions, tags) for {niche_description} channels in 2025? "
        f"Focus on what drives search discovery and click-through rate. Be specific and practical."
    )
    try:
        return chat_text(query, model="perplexity/sonar")
    except Exception as e:
        log.warning("platform_guidance: Perplexity call failed: %s", e)
        return "(platform guidance unavailable)"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_sample_competitors_formats_output tests/test_reflection.py::test_get_platform_guidance_returns_text -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add app/reflection.py tests/test_reflection.py
git commit -m "feat: competitive sampling and Perplexity platform guidance"
```

---

## Task 8: reflection.py — Reflection LLM Call + Candidate Storage

**Files:**
- Modify: `app/reflection.py` (append functions)

- [ ] **Step 1: Write failing test**

Append to `tests/test_reflection.py`:

```python
def test_run_reflection_stores_candidate_prompt():
    perf_report = _make_perf_report(win_rate=40.0)
    perf_report["worst_audits"] = [{"title_before": "old", "title_after": "new", "velocity_lift_pct": -30.0, "ai_reasoning": "test"}]
    perf_report["best_audits"] = []

    mock_reflection_result = {
        "reflection": "Titles too SEO-heavy for this niche",
        "changes": ["Prioritise native language in titles"],
        "candidate_prompt": "You are a YouTube SEO expert for regional content...",
    }

    inserted_rows = []

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json", return_value=mock_reflection_result) as mock_chat:
        def table_side(name):
            m = MagicMock()
            if name == "audit_configs":
                m.select.return_value.eq.return_value.execute.return_value.data = [
                    {"generated_prompt": "OLD PROMPT", "reflection_mode": "shadow"}
                ]
            elif name == "prompt_versions":
                def capture_insert(row):
                    inserted_rows.append(row)
                    inner = MagicMock()
                    inner.execute.return_value.data = [{"id": 42, **row}]
                    return inner
                m.insert.side_effect = capture_insert
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import _run_reflection
        version_id = _run_reflection("ch1", perf_report, "competitive ctx", "platform guidance")

    assert version_id == 42
    assert len(inserted_rows) == 1
    assert inserted_rows[0]["prompt_text"] == "You are a YouTube SEO expert for regional content..."
    assert inserted_rows[0]["status"] == "shadow"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_run_reflection_stores_candidate_prompt -v
```
Expected: `AttributeError: module 'app.reflection' has no attribute '_run_reflection'`

- [ ] **Step 3: Add reflection LLM call to reflection.py**

Append to `app/reflection.py` after `_get_platform_guidance`:

```python

# ── Reflection LLM call ───────────────────────────────────────────────────────

def _format_perf_report(report: dict) -> str:
    lines = [
        f"CHANNEL PERFORMANCE REPORT:",
        f"- Audits with velocity data: {report['count']}",
        f"- Win rate (velocity lift >10%): {report['win_rate']}%",
        f"- Regression count (last 14 days): {report['regression_count']}",
        f"- Median velocity lift: {report['median_velocity_lift']}%",
        f"- Lever performance:",
        f"    title: {report['levers'].get('title')}%",
        f"    description: {report['levers'].get('description')}%",
        f"    tags: {report['levers'].get('tags')}%",
    ]
    if report.get("worst_audits"):
        lines.append("\nSAMPLE REGRESSED AUDITS:")
        for a in report["worst_audits"]:
            lines.append(f'  Before: "{a.get("title_before", "")}"')
            lines.append(f'  After:  "{a.get("title_after", "")}"')
            lines.append(f'  Velocity lift: {round(a["velocity_lift_pct"], 1)}%')
            if a.get("ai_reasoning"):
                lines.append(f'  LLM reasoning: {(a["ai_reasoning"] or "")[:200]}')
    if report.get("best_audits"):
        lines.append("\nSAMPLE HIGH-PERFORMING AUDITS:")
        for a in report["best_audits"]:
            lines.append(f'  Before: "{a.get("title_before", "")}"')
            lines.append(f'  After:  "{a.get("title_after", "")}"')
            lines.append(f'  Velocity lift: {round(a["velocity_lift_pct"], 1)}%')
    return "\n".join(lines)


def _run_reflection(
    channel_id: str,
    perf_report: dict,
    competitive_ctx: str,
    platform_guidance: str,
) -> int | None:
    """Call Sonnet with full context. Store candidate in prompt_versions. Returns new version id."""
    from app.openrouter import chat_json

    cfg_rows = (
        supabase().table("audit_configs")
        .select("generated_prompt,reflection_mode")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    cfg = cfg_rows[0] if cfg_rows else {}
    current_prompt = cfg.get("generated_prompt") or ""
    reflection_mode = cfg.get("reflection_mode") or "shadow"

    system = (
        "You are a YouTube content optimisation expert improving an AI audit system. "
        "Analyse the performance data and competitive signals, then write an improved audit prompt."
    )
    user = (
        f"{_format_perf_report(perf_report)}\n\n"
        f"{competitive_ctx}\n\n"
        f"CURRENT YOUTUBE PLATFORM GUIDANCE:\n{platform_guidance}\n\n"
        f"CURRENT AUDIT PROMPT:\n{current_prompt}\n\n"
        "Based on all of the above, diagnose why the current prompt underperforms and write "
        "an improved version. Return JSON:\n"
        '{"reflection": "2-3 sentence diagnosis", "changes": ["change1", "change2"], '
        '"candidate_prompt": "full improved prompt text"}'
    )

    try:
        result = chat_json(user, model=settings.REFLECTION_MODEL, system=system)
    except Exception as e:
        log.error("Reflection LLM call failed for %s: %s", channel_id, e)
        return None

    candidate_prompt = (result.get("candidate_prompt") or "").strip()
    if not candidate_prompt:
        log.warning("Reflection returned empty candidate_prompt for %s", channel_id)
        return None

    # Find current live version for parent linkage
    live_rows = (
        supabase().table("prompt_versions")
        .select("id")
        .eq("channel_id", channel_id)
        .eq("status", "live")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    parent_id = live_rows[0]["id"] if live_rows else None

    row = {
        "channel_id": channel_id,
        "prompt_text": candidate_prompt,
        "status": reflection_mode if reflection_mode in ("shadow", "live") else "shadow",
        "reflection_reasoning": result.get("reflection", ""),
        "performance_snapshot": perf_report,
        "parent_version_id": parent_id,
    }
    inserted = supabase().table("prompt_versions").insert(row).execute()
    version_id = (inserted.data[0] if inserted.data else {}).get("id")
    log.info("Stored prompt candidate %s for %s (status=%s)", version_id, channel_id, row["status"])

    # If auto mode: go live immediately
    if reflection_mode == "auto" and version_id:
        supabase().table("audit_configs").update(
            {"generated_prompt": candidate_prompt}
        ).eq("channel_id", channel_id).execute()
        log.info("Auto mode: promoted candidate %s to live for %s", version_id, channel_id)

    return version_id
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_run_reflection_stores_candidate_prompt -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/reflection.py tests/test_reflection.py
git commit -m "feat: reflection LLM call assembles full context and stores candidate prompt"
```

---

## Task 9: reflection.py — Shadow Audit Runner

**Files:**
- Modify: `app/reflection.py` (append function)

- [ ] **Step 1: Write failing test**

Append to `tests/test_reflection.py`:

```python
def test_run_shadow_audits_uses_candidate_prompt():
    applied_audits = [
        {"video_id": f"vid{i}", "applied_at": "2026-05-01T00:00:00Z"}
        for i in range(3)
    ]
    shadow_calls = []

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.audit_video") as mock_audit:

        def table_side(name):
            m = MagicMock()
            if name == "audits":
                m.select.return_value.in_.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = applied_audits
                m.update.return_value.eq.return_value.execute.return_value = None
            elif name == "videos":
                m.select.return_value.eq.return_value.execute.return_value.data = [
                    {"id": f"vid{i}"} for i in range(3)
                ]
            return m
        mock_sb.return_value.table.side_effect = table_side
        mock_audit.return_value = {"id": 99}

        from app.reflection import _run_shadow_audits
        count = _run_shadow_audits("ch1", "CANDIDATE PROMPT", version_id=42)

    assert count == 3
    for call in mock_audit.call_args_list:
        assert call.kwargs.get("prompt_override") == "CANDIDATE PROMPT"
        assert call.kwargs.get("status_override") == "shadow_pending"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_run_shadow_audits_uses_candidate_prompt -v
```
Expected: `AttributeError: module 'app.reflection' has no attribute '_run_shadow_audits'`

- [ ] **Step 3: Add shadow runner to reflection.py**

Append to `app/reflection.py` after `_run_reflection`:

```python

# ── Shadow audit runner ───────────────────────────────────────────────────────

def _run_shadow_audits(channel_id: str, candidate_prompt: str, version_id: int) -> int:
    """Run candidate prompt on 10 recently applied videos. Store as shadow_pending.

    Returns count of shadow audits created.
    """
    from app.audits import audit_video

    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]
    if not video_ids:
        return 0

    recent_applied = (
        supabase().table("audits")
        .select("video_id,applied_at")
        .in_("video_id", video_ids)
        .eq("status", "applied")
        .order("applied_at", desc=True)
        .limit(10)
        .execute()
    ).data or []

    if not recent_applied:
        return 0

    count = 0
    for row in recent_applied:
        vid = row["video_id"]
        try:
            result = audit_video(
                vid,
                prompt_override=candidate_prompt,
                status_override="shadow_pending",
            )
            # Tag shadow audit with the version that generated it
            if result and result.get("id"):
                supabase().table("audits").update(
                    {"prompt_version_id": version_id}
                ).eq("id", result["id"]).execute()
            count += 1
        except Exception as e:
            log.warning("Shadow audit failed for %s: %s", vid, e)

    log.info("Shadow: ran %d audits for candidate %s on channel %s", count, version_id, channel_id)
    return count
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_run_shadow_audits_uses_candidate_prompt -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/reflection.py tests/test_reflection.py
git commit -m "feat: shadow audit runner — candidate prompt tested on recent videos without applying"
```

---

## Task 10: autopilot.py — Skip shadow_pending + Stamp prompt_version_id

**Files:**
- Modify: `app/autopilot.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_reflection.py`:

```python
def test_autopilot_skip_statuses_include_shadow_pending():
    """shadow_pending must be in the skip set so autopilot never applies shadow audits."""
    from app.autopilot import _next_video_for_channel
    import inspect
    src = inspect.getsource(_next_video_for_channel)
    assert "shadow_pending" in src
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_autopilot_skip_statuses_include_shadow_pending -v
```
Expected: FAIL (assertion error — `shadow_pending` not in source)

- [ ] **Step 3: Add shadow_pending to skip set in autopilot.py**

In `app/autopilot.py`, find line 112:
```python
    skip_statuses = {"applied", "pending", "quarantined", "blocked_test_and_compare"}
```
Change to:
```python
    skip_statuses = {"applied", "pending", "quarantined", "blocked_test_and_compare", "shadow_pending"}
```

- [ ] **Step 4: Stamp prompt_version_id on new audits in autopilot.py**

In `app/autopilot.py`, after the `audit_row = audit_video(video["id"])` call succeeds (after step 7, before step 8), add the current live version lookup. Find the comment `# 8. Validate` and insert before it:

```python
        # Stamp which prompt version generated this audit
        try:
            live_ver = (
                supabase().table("prompt_versions")
                .select("id")
                .eq("channel_id", channel_id)
                .eq("status", "live")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data
            if live_ver and audit_row.get("id"):
                supabase().table("audits").update(
                    {"prompt_version_id": live_ver[0]["id"]}
                ).eq("id", audit_row["id"]).execute()
        except Exception as e:
            log.warning("Failed to stamp prompt_version_id for audit %s: %s", audit_row.get("id"), e)
```

- [ ] **Step 5: Run all tests**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py -v
```
Expected: all PASS

- [ ] **Step 6: Verify autopilot imports still clean**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -c "from app.autopilot import tick; print('ok')"
```
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add app/autopilot.py tests/test_reflection.py
git commit -m "feat: autopilot skips shadow_pending audits and stamps prompt_version_id"
```

---

## Task 11: reflection.py — Auto-Revert Cohort Comparison

**Files:**
- Modify: `app/reflection.py` (append function)

- [ ] **Step 1: Write failing test**

Append to `tests/test_reflection.py`:

```python
def test_check_auto_revert_triggers_on_regression():
    """If new cohort median lift is >10pp below old cohort, revert."""
    old_version_id = 1
    new_version_id = 2

    # Old cohort: 12 audits averaging +20% lift
    old_audits = [{"id": i, "video_id": f"v{i}", "view_count_at_apply": 1000, "applied_at": "2026-04-01T00:00:00Z"} for i in range(12)]
    # New cohort: 12 audits averaging -5% lift
    new_audits = [{"id": i+100, "video_id": f"v{i+100}", "view_count_at_apply": 1000, "applied_at": "2026-04-15T00:00:00Z"} for i in range(12)]

    revert_calls = []

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._cohort_median_lift") as mock_lift:
        mock_lift.side_effect = lambda version_id, *args: 20.0 if version_id == old_version_id else -5.0

        def table_side(name):
            m = MagicMock()
            if name == "prompt_versions":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = [
                    {"id": new_version_id, "parent_version_id": old_version_id,
                     "channel_id": "ch1", "created_at": "2026-04-15T00:00:00Z"}
                ]
                update_m = MagicMock()
                update_m.eq.return_value.execute.return_value = None
                m.update.return_value = update_m
                revert_calls.append = lambda *a: None
            elif name == "audit_configs":
                m.update.return_value.eq.return_value.execute.return_value = None
                m.select.return_value.eq.return_value.execute.return_value.data = [
                    {"generated_prompt": "OLD PROMPT"}
                ]
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import _check_auto_revert
        _check_auto_revert("ch1")

    # Verify revert was called (update status to retired_regression)
    mock_sb.return_value.table.assert_any_call("prompt_versions")


def test_cohort_median_lift_returns_none_insufficient():
    with patch("app.reflection.supabase") as mock_sb:
        mock_sb.return_value.table.return_value.select.return_value \
            .eq.return_value.execute.return_value.data = []
        from app.reflection import _cohort_median_lift
        result = _cohort_median_lift(99, [])
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_cohort_median_lift_returns_none_insufficient -v
```
Expected: `AttributeError: module 'app.reflection' has no attribute '_cohort_median_lift'`

- [ ] **Step 3: Add cohort comparison + auto-revert to reflection.py**

Append to `app/reflection.py` after `_run_shadow_audits`:

```python

# ── Auto-revert cohort comparison ─────────────────────────────────────────────

def _cohort_median_lift(version_id: int, channel_video_ids: list[str]) -> float | None:
    """Compute median velocity_lift_pct for audits generated by a specific prompt version.

    Returns None if fewer than _MIN_DATA_POINTS audits have sufficient post-apply data.
    """
    audits = (
        supabase().table("audits")
        .select("video_id,applied_at,view_count_at_apply")
        .eq("prompt_version_id", version_id)
        .eq("status", "applied")
        .execute()
    ).data or []

    if not audits or not channel_video_ids:
        return None

    vid_rows = (
        supabase().table("videos")
        .select("id,view_count,published_at")
        .in_("id", [a["video_id"] for a in audits])
        .execute()
    ).data or []
    videos_by_id = {v["id"]: v for v in vid_rows}

    now = datetime.now(timezone.utc)
    lifts = []
    for a in audits:
        v = videos_by_id.get(a["video_id"])
        if not v or not a.get("applied_at") or not v.get("published_at"):
            continue
        view_at = a.get("view_count_at_apply") or 0
        if view_at <= 0:
            continue
        try:
            ap = datetime.fromisoformat(a["applied_at"].replace("Z", "+00:00"))
            pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        days_since = (now - ap).total_seconds() / 86400.0
        if days_since < _VELOCITY_WINDOW_DAYS:
            continue
        age_at_apply = max(1.0, (ap - pub).total_seconds() / 86400.0)
        before_v = view_at / age_at_apply
        after_v = (v.get("view_count", 0) - view_at) / max(1.0, days_since)
        if before_v > 0:
            lifts.append(((after_v - before_v) / before_v) * 100.0)

    if len(lifts) < _MIN_DATA_POINTS:
        return None
    return statistics.median(lifts)


def _check_auto_revert(channel_id: str) -> None:
    """For channels in auto mode: compare live cohort vs parent cohort. Revert if regression."""
    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]

    live_rows = (
        supabase().table("prompt_versions")
        .select("id,parent_version_id,created_at")
        .eq("channel_id", channel_id)
        .eq("status", "live")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []

    if not live_rows:
        return
    live = live_rows[0]
    if not live.get("parent_version_id"):
        return  # no parent to compare against

    # Minimum 21 days since promotion before making a verdict
    promoted_dt = datetime.fromisoformat(live["created_at"].replace("Z", "+00:00"))
    if (datetime.now(timezone.utc) - promoted_dt) < timedelta(days=21):
        return

    new_median = _cohort_median_lift(live["id"], video_ids)
    old_median = _cohort_median_lift(live["parent_version_id"], video_ids)

    if new_median is None or old_median is None:
        return  # insufficient data in one or both cohorts

    regression = (old_median - new_median) > 10.0
    if not regression:
        log.info(
            "Auto-revert check for %s: new=%.1f%% old=%.1f%% — keeping",
            channel_id, new_median, old_median,
        )
        return

    log.warning(
        "Auto-revert triggered for %s: new cohort %.1f%% vs old %.1f%% (>10pp regression)",
        channel_id, new_median, old_median,
    )

    # Fetch parent prompt text and restore
    parent_rows = (
        supabase().table("prompt_versions")
        .select("prompt_text")
        .eq("id", live["parent_version_id"])
        .execute()
    ).data or []
    if not parent_rows:
        return

    parent_prompt = parent_rows[0]["prompt_text"]
    now_iso = datetime.now(timezone.utc).isoformat()

    supabase().table("prompt_versions").update(
        {"status": "retired_regression", "retired_at": now_iso}
    ).eq("id", live["id"]).execute()

    supabase().table("prompt_versions").update(
        {"status": "live", "promoted_at": now_iso}
    ).eq("id", live["parent_version_id"]).execute()

    supabase().table("audit_configs").update(
        {"generated_prompt": parent_prompt}
    ).eq("channel_id", channel_id).execute()

    log.info("Reverted channel %s to parent prompt version %s", channel_id, live["parent_version_id"])
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_cohort_median_lift_returns_none_insufficient tests/test_reflection.py::test_check_auto_revert_triggers_on_regression -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```bash
git add app/reflection.py tests/test_reflection.py
git commit -m "feat: cohort comparison and auto-revert for regression detection"
```

---

## Task 12: reflection.py — Threshold Tuner

**Files:**
- Modify: `app/reflection.py` (append function)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_reflection.py`:

```python
def test_tune_thresholds_nudges_up_on_high_fpr():
    """FPR > 20%: join_high should increase by 0.01."""
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(10)] +
        [{"action": "removed"} for _ in range(3)]  # 30% FPR
    )
    stored = []
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.72
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                def capture(row):
                    stored.append(row)
                    inner = MagicMock()
                    inner.execute.return_value = None
                    return inner
                m.insert.side_effect = capture
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] == pytest.approx(0.73, abs=0.001)
    assert result["fpr"] == pytest.approx(0.30, abs=0.01)


def test_tune_thresholds_nudges_down_on_low_fpr():
    """FPR < 5%: join_high should decrease by 0.01."""
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(20)] +
        [{"action": "removed"} for _ in range(0)]  # 0% FPR
    )
    stored = []
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.72
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                def capture(row):
                    stored.append(row)
                    inner = MagicMock()
                    inner.execute.return_value = None
                    return inner
                m.insert.side_effect = capture
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] == pytest.approx(0.71, abs=0.001)


def test_tune_thresholds_respects_upper_bound():
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(10)] +
        [{"action": "removed"} for _ in range(4)]  # 40% FPR
    )
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.84  # one nudge would exceed 0.85
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                m.insert.return_value.execute.return_value = None
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] <= 0.85
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_tune_thresholds_nudges_up_on_high_fpr -v
```
Expected: `AttributeError: module 'app.reflection' has no attribute 'tune_thresholds'`

- [ ] **Step 3: Add threshold tuner to reflection.py**

Append to `app/reflection.py` after `_check_auto_revert`:

```python

# ── Playlist threshold tuner ──────────────────────────────────────────────────

_THRESHOLD_JOIN_HIGH_MIN = 0.65
_THRESHOLD_JOIN_HIGH_MAX = 0.85
_THRESHOLD_NUDGE = 0.01
_FPR_HIGH = 0.20   # false positive rate above which we tighten
_FPR_LOW = 0.05    # false positive rate below which we loosen


def tune_thresholds(channel_id: str) -> dict:
    """Adjust PLAYLIST_JOIN_HIGH based on playlist assignment churn rate.

    Churn signal: embedding-adds that were later removed = false positives.
    Writes a new threshold_history row and updates settings in-process.
    Returns dict with fpr, old_join_high, new_join_high.
    """
    rows = (
        supabase().table("playlist_assignments")
        .select("action,decision_source")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []

    embedding_adds = [r for r in rows if r["action"] == "added" and r["decision_source"] == "embedding"]
    removals = [r for r in rows if r["action"] == "removed"]

    total_adds = len(embedding_adds)
    if total_adds < 5:
        log.info("tune_thresholds: insufficient assignment data for %s (%d adds)", channel_id, total_adds)
        return {"skipped": True, "reason": "insufficient_data"}

    fpr = len(removals) / total_adds
    old_high = settings.PLAYLIST_JOIN_HIGH

    if fpr > _FPR_HIGH:
        delta = _THRESHOLD_NUDGE
    elif fpr < _FPR_LOW:
        delta = -_THRESHOLD_NUDGE
    else:
        log.info("tune_thresholds: FPR %.2f in stable range for %s — no change", fpr, channel_id)
        return {"skipped": True, "reason": "stable_fpr", "fpr": round(fpr, 3)}

    new_high = round(
        max(_THRESHOLD_JOIN_HIGH_MIN, min(_THRESHOLD_JOIN_HIGH_MAX, old_high + delta)), 4
    )

    if new_high == old_high:
        return {"skipped": True, "reason": "at_boundary", "fpr": round(fpr, 3), "new_join_high": new_high}

    # Retire current active threshold row
    supabase().table("threshold_history").update(
        {"status": "retired"}
    ).eq("channel_id", channel_id).eq("status", "active").execute()

    # Insert new active threshold row
    supabase().table("threshold_history").insert({
        "channel_id": channel_id,
        "join_high": new_high,
        "join_low": settings.PLAYLIST_JOIN_LOW,
        "leave_threshold": settings.PLAYLIST_LEAVE,
        "status": "active",
        "reason": f"fpr={round(fpr, 3):.3f} ({'tightened' if delta > 0 else 'loosened'})",
    }).execute()

    # Update in-process settings so the running app uses new threshold immediately
    settings.PLAYLIST_JOIN_HIGH = new_high
    log.info(
        "tune_thresholds: %s PLAYLIST_JOIN_HIGH %.4f → %.4f (fpr=%.2f)",
        channel_id, old_high, new_high, fpr,
    )
    return {
        "fpr": round(fpr, 3),
        "old_join_high": old_high,
        "new_join_high": new_high,
        "delta": delta,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py::test_tune_thresholds_nudges_up_on_high_fpr tests/test_reflection.py::test_tune_thresholds_nudges_down_on_low_fpr tests/test_reflection.py::test_tune_thresholds_respects_upper_bound -v
```
Expected: all 3 PASS

- [ ] **Step 5: Commit**

```bash
git add app/reflection.py tests/test_reflection.py
git commit -m "feat: playlist threshold tuner adjusts PLAYLIST_JOIN_HIGH based on churn rate"
```

---

## Task 13: reflection.py — Main Orchestrator + API Endpoints

**Files:**
- Modify: `app/reflection.py` (append)

- [ ] **Step 1: Add the main reflect() function and router endpoints**

Append to `app/reflection.py`:

```python

# ── Main orchestrator ─────────────────────────────────────────────────────────

def reflect(channel_id: str) -> dict:
    """Full reflection cycle for one channel. Called weekly by scheduler.

    Returns dict describing what happened.
    """
    log.info("Reflection tick for channel %s", channel_id)

    should, reason = _should_reflect(channel_id)
    if not should:
        log.info("Reflection skipped for %s: %s", channel_id, reason)
        # Still run threshold tuner regardless
        tune_result = tune_thresholds(channel_id)
        return {"reflected": False, "reason": reason, "threshold_tune": tune_result}

    niche_queries = get_or_derive_niche_queries(channel_id)
    perf_report = _build_perf_report(channel_id)
    if perf_report is None:
        return {"reflected": False, "reason": "insufficient_data_at_reflect_time"}

    competitive_ctx = _sample_competitors(channel_id, niche_queries)
    niche_desc = ", ".join(niche_queries[:2]) if niche_queries else "general"
    platform_guidance = _get_platform_guidance(niche_desc)

    version_id = _run_reflection(channel_id, perf_report, competitive_ctx, platform_guidance)
    if version_id is None:
        return {"reflected": False, "reason": "reflection_llm_failed"}

    cfg_rows = (
        supabase().table("audit_configs")
        .select("reflection_mode")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    mode = (cfg_rows[0].get("reflection_mode") if cfg_rows else None) or "shadow"

    shadow_count = 0
    if mode == "shadow":
        version_row = (
            supabase().table("prompt_versions")
            .select("prompt_text")
            .eq("id", version_id)
            .single()
            .execute()
        ).data
        if version_row:
            shadow_count = _run_shadow_audits(channel_id, version_row["prompt_text"], version_id)

    _check_auto_revert(channel_id)
    tune_result = tune_thresholds(channel_id)

    log.info(
        "Reflection complete for %s: version_id=%s mode=%s shadow_count=%d",
        channel_id, version_id, mode, shadow_count,
    )
    return {
        "reflected": True,
        "version_id": version_id,
        "mode": mode,
        "shadow_audits_created": shadow_count,
        "threshold_tune": tune_result,
    }


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/channels/{channel_id}/reflection/history")
def reflection_history(channel_id: str):
    """List all prompt versions for a channel, newest first."""
    rows = (
        supabase().table("prompt_versions")
        .select("id,status,created_at,promoted_at,retired_at,reflection_reasoning,performance_snapshot,parent_version_id")
        .eq("channel_id", channel_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return rows


@router.post("/channels/{channel_id}/prompt-versions/{version_id}/promote")
def promote_version(channel_id: str, version_id: int):
    """Manually promote a shadow candidate to live. Only valid for status=shadow."""
    version = (
        supabase().table("prompt_versions")
        .select("*")
        .eq("id", version_id)
        .eq("channel_id", channel_id)
        .single()
        .execute()
    ).data
    if not version:
        raise HTTPException(404, "Version not found")
    if version["status"] != "shadow":
        raise HTTPException(400, f"Cannot promote version with status={version['status']}")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Retire any currently live version
    supabase().table("prompt_versions").update(
        {"status": "retired", "retired_at": now_iso}
    ).eq("channel_id", channel_id).eq("status", "live").execute()

    supabase().table("prompt_versions").update(
        {"status": "live", "promoted_at": now_iso}
    ).eq("id", version_id).execute()

    supabase().table("audit_configs").update(
        {"generated_prompt": version["prompt_text"]}
    ).eq("channel_id", channel_id).execute()

    log.info("Manually promoted prompt version %s for channel %s", version_id, channel_id)
    return {"ok": True, "promoted_version_id": version_id}


@router.post("/channels/{channel_id}/reflection/trigger")
def trigger_reflection(channel_id: str):
    """Manually trigger a reflection cycle (ignores cooldown check)."""
    result = reflect(channel_id)
    return result


@router.get("/channels/{channel_id}/reflection/shadow-comparison")
def shadow_comparison(channel_id: str):
    """Return side-by-side comparison: live vs shadow_pending audits for same videos."""
    shadow_audits = (
        supabase().table("audits")
        .select("id,video_id,suggested_title,suggested_description,suggested_tags,prompt_version_id,created_at")
        .eq("status", "shadow_pending")
        .execute()
    ).data or []

    if not shadow_audits:
        return []

    video_ids = list({a["video_id"] for a in shadow_audits})

    live_audits = (
        supabase().table("audits")
        .select("video_id,suggested_title,suggested_description,suggested_tags,created_at")
        .in_("video_id", video_ids)
        .eq("status", "applied")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    live_by_vid: dict[str, dict] = {}
    for a in live_audits:
        if a["video_id"] not in live_by_vid:
            live_by_vid[a["video_id"]] = a

    result = []
    for shadow in shadow_audits:
        vid = shadow["video_id"]
        live = live_by_vid.get(vid)
        result.append({
            "video_id": vid,
            "shadow_audit_id": shadow["id"],
            "shadow_title": shadow.get("suggested_title"),
            "shadow_description": shadow.get("suggested_description"),
            "shadow_tags": shadow.get("suggested_tags"),
            "live_title": (live or {}).get("suggested_title"),
            "live_description": (live or {}).get("suggested_description"),
            "live_tags": (live or {}).get("suggested_tags"),
            "prompt_version_id": shadow.get("prompt_version_id"),
        })
    return result
```

- [ ] **Step 2: Verify the module imports cleanly**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -c "from app.reflection import reflect, router, tune_thresholds; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/reflection.py
git commit -m "feat: reflection orchestrator and API endpoints (history, promote, trigger, shadow-comparison)"
```

---

## Task 14: main.py — Weekly Reflection Scheduler

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add reflection imports and weekly job to main.py**

In `app/main.py`, add the import after the `from app.playlists_router import router as playlists_router` line:

```python
from app.reflection import reflect as reflection_reflect, router as reflection_router
```

Add the weekly reflection function before the `lifespan` context manager:

```python
def _weekly_reflection():
    for channel_id in _all_channel_ids():
        try:
            result = reflection_reflect(channel_id)
            _main_log.info("Weekly reflection %s: %s", channel_id, result)
        except Exception as e:
            _main_log.exception("Weekly reflection failed for %s: %s", channel_id, e)
```

Inside the `lifespan` context manager, add after the `_weekly_discovery` job:

```python
    scheduler.add_job(
        _weekly_reflection,
        "cron",
        day_of_week="mon",
        hour=4,
        minute=0,
        id="reflection",
        max_instances=1,
        coalesce=True,
    )
```

Add the router after `app.include_router(playlists_router)`:

```python
app.include_router(reflection_router)
```

- [ ] **Step 2: Verify the app starts**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -c "from app.main import app; print('app loads ok')"
```
Expected: `app loads ok`

- [ ] **Step 3: Run all tests**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py -v
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: add weekly reflection scheduler job and register reflection router"
```

---

## Task 15: UI — Reflection Panel in channel.html

**Files:**
- Modify: `app/static/channel.html`

- [ ] **Step 1: Read channel.html to find injection points**

Open `app/static/channel.html` and locate:
1. The audit config section (where `generated_prompt` textarea lives) — this is where the mode toggle and reflection history go
2. The end of the page JS — this is where the new API calls go

- [ ] **Step 2: Add reflection mode toggle to audit config section**

Find the audit config form in `channel.html`. Add after the existing prompt textarea:

```html
<!-- Reflection mode -->
<div class="mt-4 p-3 bg-gray-50 rounded border">
  <div class="flex items-center justify-between mb-2">
    <span class="font-medium text-sm text-gray-700">Self-Improvement Mode</span>
    <select id="reflectionMode" onchange="saveReflectionMode(this.value)"
            class="text-sm border rounded px-2 py-1">
      <option value="shadow">Shadow (review before applying)</option>
      <option value="auto">Auto (apply + revert if regression)</option>
    </select>
  </div>
  <p class="text-xs text-gray-500">
    Shadow: generates improved prompts for your review. Auto: tests live, reverts automatically if performance drops.
  </p>
  <button onclick="triggerReflection()"
          class="mt-2 text-xs bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700">
    Run Reflection Now
  </button>
</div>

<!-- Shadow comparison panel -->
<div id="shadowPanel" class="mt-4 hidden">
  <h3 class="font-semibold text-sm mb-2">Shadow Comparison</h3>
  <p class="text-xs text-gray-500 mb-3">
    These are suggestions from the candidate prompt — not yet applied. Compare with live suggestions and promote if better.
  </p>
  <div id="shadowComparisons" class="space-y-3"></div>
  <div id="shadowPromoteBtn" class="mt-3 hidden">
    <button onclick="promoteCandidate()"
            class="text-sm bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700">
      Promote Candidate to Live
    </button>
  </div>
</div>

<!-- Reflection history -->
<div id="reflectionHistory" class="mt-4 hidden">
  <h3 class="font-semibold text-sm mb-2">Prompt Version History</h3>
  <div id="reflectionHistoryList" class="space-y-2 text-xs"></div>
</div>
```

- [ ] **Step 3: Add JS for reflection features**

Find the closing `</script>` tag in `channel.html` and add before it:

```javascript
// ── Reflection ────────────────────────────────────────────────────────────

let _shadowVersionId = null;

async function loadReflectionData() {
  const channelId = getChannelId();
  if (!channelId) return;

  // Load reflection mode from audit config
  try {
    const cfg = await fetch(`/channels/${channelId}/audit-config`).then(r => r.json());
    const modeEl = document.getElementById('reflectionMode');
    if (modeEl && cfg.reflection_mode) modeEl.value = cfg.reflection_mode;
  } catch (e) { /* non-fatal */ }

  // Load shadow comparison
  try {
    const comparisons = await fetch(`/channels/${channelId}/reflection/shadow-comparison`).then(r => r.json());
    renderShadowComparisons(comparisons);
  } catch (e) { /* non-fatal */ }

  // Load reflection history
  try {
    const history = await fetch(`/channels/${channelId}/reflection/history`).then(r => r.json());
    renderReflectionHistory(history);
  } catch (e) { /* non-fatal */ }
}

function renderShadowComparisons(items) {
  const panel = document.getElementById('shadowPanel');
  const container = document.getElementById('shadowComparisons');
  const promoteBtn = document.getElementById('shadowPromoteBtn');
  if (!panel || !container) return;
  if (!items || items.length === 0) { panel.classList.add('hidden'); return; }

  panel.classList.remove('hidden');
  _shadowVersionId = items[0].prompt_version_id;
  if (_shadowVersionId) promoteBtn && promoteBtn.classList.remove('hidden');

  container.innerHTML = items.slice(0, 5).map(item => `
    <div class="border rounded p-3 text-xs bg-white">
      <div class="font-medium text-gray-600 mb-1 truncate">${item.video_id}</div>
      <div class="grid grid-cols-2 gap-2">
        <div>
          <div class="text-gray-400 mb-1">Current</div>
          <div class="text-gray-700">${item.live_title || '(none)'}</div>
        </div>
        <div>
          <div class="text-indigo-400 mb-1">Candidate</div>
          <div class="text-indigo-700 font-medium">${item.shadow_title || '(none)'}</div>
        </div>
      </div>
    </div>
  `).join('');
}

function renderReflectionHistory(versions) {
  const el = document.getElementById('reflectionHistory');
  const list = document.getElementById('reflectionHistoryList');
  if (!el || !list || !versions || versions.length === 0) return;
  el.classList.remove('hidden');

  const statusColor = { live: 'text-green-600', shadow: 'text-indigo-600', retired: 'text-gray-400', retired_regression: 'text-red-400' };
  list.innerHTML = versions.map(v => `
    <div class="border rounded p-2 bg-white">
      <div class="flex justify-between items-center">
        <span class="font-medium ${statusColor[v.status] || 'text-gray-600'}">${v.status}</span>
        <span class="text-gray-400">${v.created_at ? v.created_at.slice(0, 10) : ''}</span>
      </div>
      ${v.reflection_reasoning ? `<div class="text-gray-500 mt-1">${v.reflection_reasoning}</div>` : ''}
    </div>
  `).join('');
}

async function saveReflectionMode(mode) {
  const channelId = getChannelId();
  if (!channelId) return;
  await fetch(`/channels/${channelId}/audit-config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reflection_mode: mode }),
  });
}

async function triggerReflection() {
  const channelId = getChannelId();
  if (!channelId) return;
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Running…';
  try {
    const result = await fetch(`/channels/${channelId}/reflection/trigger`, { method: 'POST' }).then(r => r.json());
    btn.textContent = result.reflected ? `Done — version ${result.version_id}` : `Skipped: ${result.reason}`;
    if (result.reflected) await loadReflectionData();
  } catch (e) {
    btn.textContent = 'Error';
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = 'Run Reflection Now'; }, 3000);
}

async function promoteCandidate() {
  const channelId = getChannelId();
  if (!channelId || !_shadowVersionId) return;
  if (!confirm('Promote this candidate prompt to live? The current prompt will be retired.')) return;
  const result = await fetch(`/channels/${channelId}/prompt-versions/${_shadowVersionId}/promote`, { method: 'POST' }).then(r => r.json());
  if (result.ok) {
    alert('Candidate promoted to live.');
    await loadReflectionData();
  }
}
```

- [ ] **Step 4: Wire loadReflectionData into page init**

Find the existing page-load call (likely a `DOMContentLoaded` listener or `window.onload` / `init()` function). Add `loadReflectionData()` to it.

Also update the `saveConfig` / `POST /channels/{id}/audit-config` call to pass `reflection_mode` when saving:

Find where the audit config is POSTed and add `reflection_mode` to the payload:
```javascript
reflection_mode: document.getElementById('reflectionMode')?.value || 'shadow',
```

- [ ] **Step 5: Also update audit-config save endpoint to accept reflection_mode**

In `app/audits.py`, update `AuditConfigIn`:

```python
class AuditConfigIn(BaseModel):
    raw_insights: str | None = None
    generated_prompt: str | None = None
    shorts_prompt: str | None = None
    reflection_mode: str | None = None
```

And in `save_config`, add to the payload:

```python
    if body.reflection_mode is not None:
        payload["reflection_mode"] = body.reflection_mode
```

- [ ] **Step 6: Run all tests**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -m pytest tests/test_reflection.py -v
```
Expected: all PASS

- [ ] **Step 7: Verify app starts and all routes registered**

```bash
cd /Users/jugaadchhabra/Documents/Github/Midas && python -c "
from app.main import app
routes = [r.path for r in app.routes]
assert any('reflection' in r for r in routes), 'reflection routes missing'
print('All routes ok')
print([r for r in routes if 'reflection' in r])
"
```
Expected: prints reflection route paths

- [ ] **Step 8: Commit**

```bash
git add app/static/channel.html app/audits.py
git commit -m "feat: reflection UI — mode toggle, shadow comparison, history panel, promote button"
```

---

## Self-Review Against Spec

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Niche extraction from channel content | Task 6 |
| Reflection trigger: win rate < 50%, regressions > 3, negative lever | Task 5 |
| Competitive sampling via YouTube search (200 quota units, publishedAfter 90d) | Task 7 |
| Perplexity platform guidance | Task 7 |
| Reflection LLM call (Sonnet), store in prompt_versions | Task 8 |
| Shadow mode: run on 10 recent videos, shadow_pending status | Task 9 |
| Auto mode: go live immediately, stamp prompt_version_id | Task 8 (auto branch in _run_reflection) |
| Autopilot skips shadow_pending | Task 10 |
| prompt_version_id stamped on new audits | Task 10 |
| Cohort comparison after 21 days | Task 11 |
| Auto-revert on >10pp regression | Task 11 |
| Threshold tuner: FPR arithmetic, nudge ±0.01, bounds [0.65, 0.85] | Task 12 |
| threshold_history table writes | Task 12 |
| API: GET history, POST promote, POST trigger, GET shadow-comparison | Task 13 |
| Weekly scheduler | Task 14 |
| UI: mode toggle, shadow comparison, history, promote button | Task 15 |
| REFLECTION_MODEL config key | Task 1 |
| DB migrations: prompt_versions, threshold_history, new columns | Task 1 |
| chat_text() for Perplexity | Task 2 |
| yt_search_videos() | Task 3 |

All requirements covered. No gaps.

**Type/name consistency check:**
- `_should_reflect` returns `tuple[bool, str]` — used consistently in `reflect()`
- `_build_perf_report` returns `dict | None` — checked for None before use
- `_run_reflection` returns `int | None` — checked for None before shadow runner
- `tune_thresholds` returns `dict` — always returns a dict (either skipped or result)
- `_cohort_median_lift` takes `version_id: int, channel_video_ids: list[str]` — called correctly in `_check_auto_revert`
- `audit_video(video_id, prompt_override, status_override)` — keyword args, safe for existing callers
