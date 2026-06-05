# Content Intelligence — Roadmap (deferred work)

This file tracks what we are **not** building right now. Blocks A and B (foundation +
content-aware audit) ship first; everything below waits for those to prove out.

The original spec lives in `MIDAS_CONTENT_INTELLIGENCE_PLAN.md`. This doc supersedes
it for ordering and revisions.

---

## Status

| Block | Scope | State |
|---|---|---|
| A | `default_language` backfill, `_build_user_block` lift, keyframes/audit migration | **In progress** |
| B | `transcripts.py`, `keyframes.py`, content-aware `audit_video()` | **In progress** |
| C | Style profile (one-time) | Deferred |
| D | Thumbnail generation + validation loop + apply | Deferred |
| E | Autopilot integration of thumbnail apply | Deferred |

Ship A+B first. Watch audit quality on a few channels for ~1 week. Then start C.

---

## Block C — Style profile (~½ day)

Build the one-time per-channel style document used by thumbnail generation.

- `app/style_profile.py` with `build_style_profile()` and `load_style_profile()`
- Folder-hash auto-rebuild: hash `thumbnail_reference/` contents, store hash in
  `channels.style_profile_hash`; rebuild lazily when hash mismatches at audit time.
  No manual rebuild button needed.
- Output the profile as **JSON** (not Markdown) and use the existing `chat_json` —
  do not introduce a `chat_text` helper.
- Drop a per-channel `thumbnail_reference/<channel_id>/` folder convention so each
  channel has its own profile.
- Endpoint: `POST /channels/{id}/style-profile/rebuild` (force rebuild for ops).

Open question: do we keep `style_profile.md` on disk or move it into
`channels.style_profile_json`? Disk is simpler; DB is easier to ship between
machines. Default to DB column.

---

## Block D — Thumbnail generation (~3 days, behind per-channel flag)

### D.1 Schema additions

```sql
ALTER TABLE channels
  ADD COLUMN IF NOT EXISTS thumbnail_generation_enabled BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS style_profile_hash TEXT,
  ADD COLUMN IF NOT EXISTS style_profile_json JSONB;

CREATE TABLE generated_thumbnails (
    id BIGSERIAL PRIMARY KEY,
    audit_id BIGINT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,
    prompt_used TEXT NOT NULL,
    model TEXT NOT NULL,
    generation_n INT NOT NULL,
    validation_score FLOAT,
    validation_feedback JSONB,
    selected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE audits
  ADD COLUMN IF NOT EXISTS thumbnail_generation_status TEXT DEFAULT 'not_attempted',
  -- not_attempted | generating | success | failed_validation | failed_generation
  ADD COLUMN IF NOT EXISTS selected_thumbnail_id BIGINT REFERENCES generated_thumbnails(id);
```

Storage bucket: `generated-thumbs` (private).

### D.2 `chat_image_gen` helper in `openrouter.py`

Verify OpenRouter Gemini 2.5 Flash Image response shape with a single live call
**before** writing the abstraction. Note that the existing openrouter.py uses
raw `httpx.post`, not the OpenAI SDK — match that pattern.

### D.3 `app/thumbnail_generator.py`

- Generate → validate → regen loop (max 3).
- **Validator must be a different model family than generator.**
  - Gen: `google/gemini-2.5-flash-image`
  - Validate: `anthropic/claude-haiku-4.5` or `openai/gpt-4o-mini`
  - Same-family validation rubber-stamps slop.
- **PIL crop/letterbox to 1280×720** before upload — `thumbnails.set` rejects
  non-16:9 outright.
- On all attempts failed: set `thumbnail_generation_status='failed_validation'`.
  Autopilot must **permanently skip** these audits — do not retry on next tick.
  Reset requires human action (UI button or DB update).

### D.4 Per-channel opt-in

`channels.thumbnail_generation_enabled` controls whether `audit_video()` calls
`generate_thumbnail_for_audit()`. Drop the global env flag from the original
plan — channels mature at different rates.

Add a third channel-level setting: `thumbnail_auto_apply` (separate from
`thumbnail_generation_enabled`). If `enabled=true` and `auto_apply=false`,
generate thumbnails but require human click-to-apply. Useful for the first 20
videos per channel.

### D.5 Apply path additions

- `_apply_generated_thumbnail()` in `audits.py`: download from Supabase Storage,
  POST to YouTube `thumbnails.set`.
- Quota: charge 50 units (`thumbnails.set`).
- Storage cleanup hook: after `apply_audit_internal` succeeds, delete all
  non-selected `generated_thumbnails` storage objects for this audit, and all
  `video_keyframes` storage objects for this video. Keep DB rows for audit
  trail.

### D.6 Frontend

- Channel page: thumbnail comparison panel (current vs generated).
- `GET /audits/{id}/thumbnail` returns signed URL.
- Optional: surface count of `failed_validation` audits as a "needs human
  thumbnail review" stat.

---

## Block E — Autopilot integration (~½ day)

- Dynamic `APPLY_COST` in `autopilot.py`: 51 base, 101 if audit has
  `selected_thumbnail_id`. Read this when picking the next eligible audit.
- Skip audits with `thumbnail_generation_status='failed_validation'` until reset.
- Roll out to one channel first, monitor for ~1 week before broader.

---

## Decisions / non-obvious items to remember

1. **Keyframes serve both audit AND thumbnail gen.** Block B extracts them and
   attaches to the audit LLM. Block D reuses the same frames as visual seed/reference
   for generation. No second extraction pass.
2. **No per-frame vision call.** Original plan called `analyze_keyframe()` once per
   keyframe (8 LLM calls/video just to score). Replaced with: send all keyframes
   straight to the audit LLM in one call as image attachments — let the audit model
   reason about the best moment in its single pass.
3. **`KEYFRAME_MAX_FRAMES=4`** (not 8). Halves storage + ffmpeg runtime; covers
   hook/middle/climax/outro adequately.
4. **Stream URL never persists.** `_get_stream_url` is private; extraction happens
   in the same function call that fetched the URL. yt-dlp URLs expire ~6h.
5. **Scene detection deferred.** Smart timestamps only in v1. Add scene detection
   later if smart timestamps disappoint, but it scans the full stream and is
   expensive on long videos.
6. **`channels.default_language` is load-bearing.** Block A backfills it during
   OAuth and sync. Falling back silently to `"en"` for null is a trap — the apply
   path already silently writes `defaultLanguage` to YouTube. UI should warn when
   null.
7. **Cost reality check.** Original plan estimated $0.05–0.20 per video with
   thumbnails. Realistic is closer to $0.10–0.30 for 3-attempt regen on a
   tough video. Budget $200–400 per 1000 videos.
8. **`failed_validation` retry policy.** No automatic retry. Image-gen $$ on
   un-generatable videos compounds fast.
9. **Storage retention.** Block D must clean up keyframes + non-selected
   generated thumbnails on audit apply. DB rows stay (cheap), bytes go.
10. **Validator family must differ from generator.** This is a hard requirement
    in Block D, not a "consider later."

---

## What was rejected from the original plan

- `chat_text` helper — use `chat_json` with a `{markdown: "..."}` wrapper field.
- Global `THUMBNAIL_GENERATION_ENABLED` env flag — replaced by per-channel column.
- Scene detection ffmpeg path — deferred indefinitely.
- Per-frame `analyze_keyframe()` LLM calls — replaced by attaching frames to audit.
- Manual `/style-profile/rebuild` as primary mechanism — use folder hash auto-rebuild.
