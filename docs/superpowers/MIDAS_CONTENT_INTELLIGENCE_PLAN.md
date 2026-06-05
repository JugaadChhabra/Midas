# Midas — Content Intelligence Upgrade

Adds **video-content-aware** audits and **autonomous thumbnail generation** to the existing Midas pipeline.

## What changes

The current audit polishes existing metadata. After this upgrade, the audit understands the actual video content (transcript + visual frames) and can generate metadata from scratch, plus generate brand-consistent thumbnails autonomously.

**Existing flow stays intact.** This plan extends `audits.py`, `youtube_client.py`, and adds new modules. No breaking changes to the autopilot, sync, or apply paths.

---

## High-level flow

```
Audit triggered (manual or autopilot)
    │
    ├── Fetch transcript (youtube-transcript-api)
    │        └── If unavailable: log + continue without it
    │
    ├── Extract keyframes (yt-dlp stream URL + ffmpeg scene detection)
    │        └── Best frames stored in Supabase Storage
    │
    ├── Vision-analyze keyframes (OpenRouter)
    │        └── Identify best moment, on-screen text, faces
    │
    ├── Run content-aware audit (OpenRouter, JSON mode)
    │        ├── Inputs: transcript + keyframe analysis + current metadata + thumbnail
    │        └── Outputs: title, description, tags (now actually content-aware)
    │
    └── If THUMBNAIL_GENERATION_ENABLED:
             │
             ├── Load style_profile.md (cached, generated once from thumbnail_reference/)
             ├── Generate thumbnail (Gemini 2.5 Flash Image via OpenRouter)
             ├── Vision-validate against style profile
             │        ├── Pass: store, mark selected
             │        └── Fail: regenerate (max 3 attempts)
             └── If 3 attempts fail: mark audit for human review
```

---

## Phase 0 — Dependencies & Configuration

### 0.1 Python packages

Add to `requirements.txt`:

```
youtube-transcript-api>=0.6.2
yt-dlp>=2024.1.0
ffmpeg-python>=0.2.0
Pillow>=10.0.0
```

System dependency: `ffmpeg` must be installed on the host machine.

```bash
# Ubuntu/Debian (your dedicated machine)
sudo apt-get install ffmpeg
```

### 0.2 Environment & Settings additions

Add to `app/config.py` (Settings class):

```python
# Thumbnail generation
THUMBNAIL_GENERATION_ENABLED: bool = False  # Master toggle
THUMBNAIL_GEN_MODEL: str = "google/gemini-2.5-flash-image"
THUMBNAIL_VALIDATION_MODEL: str = "google/gemini-2.0-flash-001"  # Reuse current vision model
THUMBNAIL_MAX_REGENERATIONS: int = 3
THUMBNAIL_VALIDATION_THRESHOLD: float = 0.7  # 0.0–1.0 confidence score

# Keyframe extraction
KEYFRAME_STRATEGY: str = "smart"  # 'smart' | 'interval' | 'scene_detection'
KEYFRAME_MAX_FRAMES: int = 8  # Cap per video to control costs
KEYFRAMES_LOCAL_DIR: str = "storage/keyframes"  # Temp dir, cleaned after upload

# Reference thumbnails
THUMBNAIL_REFERENCE_DIR: str = "thumbnail_reference"
STYLE_PROFILE_PATH: str = "thumbnail_reference/style_profile.md"

# Transcript
TRANSCRIPT_MAX_CHARS: int = 8000  # Truncate long transcripts before sending to LLM
# No language preference needed — we grab the best available transcript regardless of language.
# The channel's default_language controls all output language, not the transcript language.
```

Add to `.env.example`:

```env
THUMBNAIL_GENERATION_ENABLED=false
THUMBNAIL_GEN_MODEL=google/gemini-2.5-flash-image
THUMBNAIL_MAX_REGENERATIONS=3
THUMBNAIL_VALIDATION_THRESHOLD=0.7
```

---

## Phase 1 — Database Migrations

### 1.1 New tables

Create `supabase/migrations/XXX_thumbnail_generation.sql`:

```sql
-- Stores extracted keyframes per video
CREATE TABLE video_keyframes (
    id BIGSERIAL PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    timestamp_seconds FLOAT NOT NULL,
    storage_path TEXT NOT NULL,  -- Path in Supabase Storage 'keyframes' bucket
    vision_analysis JSONB,  -- LLM analysis output
    is_best_moment BOOLEAN DEFAULT FALSE,
    score FLOAT,  -- Computed thumbnail-suitability score
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_video_keyframes_video ON video_keyframes(video_id);
CREATE INDEX idx_video_keyframes_best ON video_keyframes(video_id, is_best_moment) WHERE is_best_moment = TRUE;

-- Generated thumbnails per audit (versioned)
CREATE TABLE generated_thumbnails (
    id BIGSERIAL PRIMARY KEY,
    audit_id BIGINT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,  -- Supabase Storage 'generated-thumbs' bucket
    prompt_used TEXT NOT NULL,
    model TEXT NOT NULL,
    generation_n INT NOT NULL,  -- 1, 2, 3 (which regeneration attempt)
    validation_score FLOAT,  -- 0.0-1.0 from validator
    validation_feedback JSONB,  -- Detailed feedback from validation step
    selected BOOLEAN DEFAULT FALSE,  -- The chosen one for this audit
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_generated_thumbs_audit ON generated_thumbnails(audit_id);
CREATE INDEX idx_generated_thumbs_selected ON generated_thumbnails(audit_id, selected) WHERE selected = TRUE;
```

### 1.2 Audit table additions

```sql
ALTER TABLE audits 
    ADD COLUMN IF NOT EXISTS transcript_available BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS keyframes_extracted INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS thumbnail_generation_status TEXT DEFAULT 'not_attempted',
    -- 'not_attempted' | 'generating' | 'success' | 'failed_validation' | 'failed_generation'
    ADD COLUMN IF NOT EXISTS selected_thumbnail_id BIGINT REFERENCES generated_thumbnails(id);
```

### 1.3 Supabase Storage buckets

Create two private buckets via Supabase dashboard or SQL:

```sql
INSERT INTO storage.buckets (id, name, public) VALUES 
    ('keyframes', 'keyframes', false),
    ('generated-thumbs', 'generated-thumbs', false);
```

---

## Phase 2 — Transcript Module

### 2.1 Language rule (core principle)

The transcript is a **content signal only**. Its language never determines the output language.
The channel's `default_language` (stored in the `channels` table) is the single source of
truth for what language all generated text — title, description, tags, and thumbnail text —
must target. This rule is enforced in three places:

1. `transcripts.py` — returns the detected transcript language alongside the text so it
   can be explicitly declared in the audit prompt
2. `audits.py` — `_build_user_block()` injects a non-negotiable language rule block into
   every user message
3. `thumbnail_generator.py` — the generation prompt carries the same language instruction
   so on-thumbnail text matches the channel language

### 2.2 Create `app/transcripts.py`

```python
"""Fetch YouTube video transcripts for content-aware audits."""
import logging
from typing import Optional, Tuple
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

from app.config import settings

logger = logging.getLogger(__name__)

# BCP-47 language code → human-readable name, for prompt clarity
LANG_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "bn": "Bengali",
    "ta": "Tamil", "te": "Telugu", "gu": "Gujarati", "kn": "Kannada",
    "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu",
}


def fetch_transcript(video_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch transcript text for a video.

    Returns:
        (transcript_text, detected_language_code)
        Both are None if no transcript is available.

    Strategy:
        1. Try any manually uploaded transcript (highest quality)
        2. Try any auto-generated transcript
        3. Fall back to whatever is available regardless of language
        → The language of the transcript does NOT affect output language.
          That is controlled by the channel's default_language.
    """
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None

        # 1. Try manually uploaded transcripts first (any language — quality > language match)
        try:
            manually_created = [t for t in transcript_list if not t.is_generated]
            if manually_created:
                transcript = manually_created[0]
        except Exception:
            pass

        # 2. Try auto-generated transcripts
        if transcript is None:
            try:
                generated = [t for t in transcript_list if t.is_generated]
                if generated:
                    transcript = generated[0]
            except Exception:
                pass

        # 3. Last resort: grab literally anything
        if transcript is None:
            available = list(transcript_list)
            if not available:
                logger.info(f"No transcript available for {video_id}")
                return None, None
            transcript = available[0]

        detected_lang = transcript.language_code  # e.g. 'mr', 'hi', 'en'

        # Fetch and join
        entries = transcript.fetch()
        text = " ".join(entry["text"] for entry in entries)

        # Truncate if too long
        if len(text) > settings.TRANSCRIPT_MAX_CHARS:
            text = text[:settings.TRANSCRIPT_MAX_CHARS] + " [...truncated]"

        logger.info(
            f"Fetched transcript for {video_id}: {len(text)} chars "
            f"(lang: {detected_lang}, generated: {transcript.is_generated})"
        )
        return text, detected_lang

    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        logger.info(f"No transcript for {video_id}: {type(e).__name__}")
        return None, None
    except Exception as e:
        logger.warning(f"Unexpected transcript error for {video_id}: {e}")
        return None, None


def lang_display_name(code: str) -> str:
    """Return a human-readable language name for use in prompts."""
    return LANG_NAMES.get(code, code)
```

---

## Phase 3 — Keyframe Extraction

### 3.1 Create `app/keyframes.py`

```python
"""Extract keyframes from YouTube videos using yt-dlp + ffmpeg."""
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

import yt_dlp

from app.config import settings
from app.db import supabase

logger = logging.getLogger(__name__)


def _get_stream_url(video_id: str) -> Optional[str]:
    """
    Get a direct stream URL for the video (no full download).
    Picks the lowest-quality stream that still has clear frames (480p target).
    """
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "best[height<=480]/best",  # Prefer 480p, fallback to best available
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False
            )
            return info.get("url")
    except Exception as e:
        logger.error(f"Failed to get stream URL for {video_id}: {e}")
        return None


def _get_video_duration(stream_url: str) -> Optional[float]:
    """Get video duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                stream_url
            ],
            capture_output=True, text=True, timeout=30, check=True
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"ffprobe failed: {e}")
        return None


def _smart_timestamps(duration: float, max_frames: int) -> List[float]:
    """
    Pick smart timestamps: skip the first 3s (intros), grab evenly through the
    middle, and grab one near the end.
    """
    if duration < 30:
        # Short video: grab a few evenly spaced
        return [duration * i / (max_frames + 1) for i in range(1, max_frames + 1)]
    
    # Skip first 3s (often a logo/intro), avoid last 5s (outro card)
    usable_start = 5.0
    usable_end = max(duration - 5.0, usable_start + 1)
    
    timestamps = []
    # Hook moment (5-10s in)
    timestamps.append(min(8.0, duration * 0.05))
    # Evenly spaced through the middle
    middle_count = max_frames - 2
    if middle_count > 0:
        step = (usable_end - usable_start) / (middle_count + 1)
        for i in range(1, middle_count + 1):
            timestamps.append(usable_start + step * i)
    # Near outro
    timestamps.append(usable_end)
    
    return sorted(set(timestamps))


def _extract_with_scene_detection(
    stream_url: str, video_id: str, max_frames: int, output_dir: Path
) -> List[Tuple[str, float]]:
    """
    Use ffmpeg's scene-detection filter to grab frames at shot changes.
    Returns list of (local_path, approx_timestamp) tuples.
    """
    pattern = str(output_dir / f"{video_id}_scene_%03d.jpg")
    try:
        # scene > 0.4 means significant shot change
        subprocess.run(
            [
                "ffmpeg", "-i", stream_url,
                "-vf", f"select='gt(scene,0.4)',scale=1280:-1",
                "-vsync", "vfr",
                "-frames:v", str(max_frames),
                "-q:v", "2",
                pattern,
                "-y"
            ],
            capture_output=True, timeout=180, check=True
        )
        # Collect generated files (timestamps approximate, ffmpeg doesn't expose them easily here)
        frames = []
        for path in sorted(output_dir.glob(f"{video_id}_scene_*.jpg")):
            frames.append((str(path), 0.0))  # Timestamp filled later if needed
        return frames
    except Exception as e:
        logger.warning(f"Scene detection failed, falling back: {e}")
        return []


def _extract_at_timestamps(
    stream_url: str, video_id: str, timestamps: List[float], output_dir: Path
) -> List[Tuple[str, float]]:
    """Extract one frame per timestamp."""
    frames = []
    for i, ts in enumerate(timestamps):
        out_path = output_dir / f"{video_id}_t{int(ts):04d}.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-ss", str(ts),
                    "-i", stream_url,
                    "-vframes", "1",
                    "-vf", "scale=1280:-1",
                    "-q:v", "2",
                    str(out_path),
                    "-y"
                ],
                capture_output=True, timeout=30, check=True
            )
            if out_path.exists():
                frames.append((str(out_path), ts))
        except Exception as e:
            logger.warning(f"Failed to extract frame at {ts}s: {e}")
    return frames


def extract_keyframes(video_id: str) -> List[Tuple[str, float, str]]:
    """
    Main entry. Extracts keyframes, uploads to Supabase Storage, returns
    list of (storage_path, timestamp, public_url) tuples.
    """
    stream_url = _get_stream_url(video_id)
    if not stream_url:
        return []
    
    duration = _get_video_duration(stream_url)
    if not duration:
        return []
    
    output_dir = Path(settings.KEYFRAMES_LOCAL_DIR) / video_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Hybrid strategy: scene detection first, fall back to timestamps
    local_frames: List[Tuple[str, float]] = []
    
    if settings.KEYFRAME_STRATEGY in ("scene_detection", "smart"):
        local_frames = _extract_with_scene_detection(
            stream_url, video_id, settings.KEYFRAME_MAX_FRAMES, output_dir
        )
    
    if not local_frames:
        timestamps = _smart_timestamps(duration, settings.KEYFRAME_MAX_FRAMES)
        local_frames = _extract_at_timestamps(stream_url, video_id, timestamps, output_dir)
    
    # Upload to Supabase Storage
    uploaded = []
    for local_path, ts in local_frames:
        try:
            with open(local_path, "rb") as f:
                content = f.read()
            
            storage_path = f"{video_id}/{Path(local_path).name}"
            supabase.storage.from_("keyframes").upload(
                path=storage_path,
                file=content,
                file_options={"content-type": "image/jpeg", "upsert": "true"}
            )
            
            # Get signed URL for vision model (valid 1 hour)
            signed = supabase.storage.from_("keyframes").create_signed_url(
                path=storage_path, expires_in=3600
            )
            
            uploaded.append((storage_path, ts, signed["signedURL"]))
            
            # Persist row
            supabase.table("video_keyframes").insert({
                "video_id": video_id,
                "timestamp_seconds": ts,
                "storage_path": storage_path,
            }).execute()
            
        except Exception as e:
            logger.error(f"Failed to upload keyframe {local_path}: {e}")
        finally:
            # Clean up local file
            try:
                os.remove(local_path)
            except Exception:
                pass
    
    # Clean up temp dir
    try:
        output_dir.rmdir()
    except Exception:
        pass
    
    logger.info(f"Extracted {len(uploaded)} keyframes for {video_id}")
    return uploaded
```

### 3.2 Frame analysis

Add to `app/keyframes.py`:

```python
from app.openrouter import chat_json


KEYFRAME_ANALYSIS_PROMPT = """Analyze this video frame for use as YouTube thumbnail material.

Return JSON only:
{
  "subjects": ["face", "product", "text", "action"],
  "on_screen_text": "text visible in frame, or null",
  "facial_expression": "description if face present, or null",
  "composition_quality": "high|medium|low",
  "contrast": "high|medium|low",
  "clarity": "high|medium|low",
  "thumbnail_suitability": 0.0-1.0,
  "reasoning": "one sentence on why this score"
}"""


def analyze_keyframe(image_url: str) -> dict | None:
    """Run vision analysis on a single keyframe via OpenRouter."""
    try:
        result = chat_json(
            system="You are a YouTube thumbnail expert. Return only valid JSON.",
            user=KEYFRAME_ANALYSIS_PROMPT,
            image_urls=[image_url],
            model=settings.THUMBNAIL_VALIDATION_MODEL
        )
        return result
    except Exception as e:
        logger.error(f"Frame analysis failed: {e}")
        return None


def pick_best_keyframe(video_id: str, keyframes: list[tuple]) -> dict | None:
    """
    Analyze all keyframes, score them, mark the best one, persist.
    keyframes: list of (storage_path, timestamp, signed_url)
    Returns the best frame's record.
    """
    best = None
    best_score = -1.0
    
    for storage_path, ts, url in keyframes:
        analysis = analyze_keyframe(url)
        if not analysis:
            continue
        
        score = analysis.get("thumbnail_suitability", 0.0)
        
        # Update DB row
        supabase.table("video_keyframes").update({
            "vision_analysis": analysis,
            "score": score,
        }).eq("video_id", video_id).eq("storage_path", storage_path).execute()
        
        if score > best_score:
            best_score = score
            best = {"storage_path": storage_path, "timestamp": ts, "url": url, "analysis": analysis}
    
    if best:
        supabase.table("video_keyframes").update({
            "is_best_moment": True
        }).eq("video_id", video_id).eq("storage_path", best["storage_path"]).execute()
    
    return best
```

---

## Phase 4 — Style Profile (One-time, Cached)

### 4.1 Create `app/style_profile.py`

```python
"""Build and load the channel's thumbnail style profile from reference images."""
import base64
import logging
from pathlib import Path

from app.config import settings
from app.openrouter import chat_json

logger = logging.getLogger(__name__)


STYLE_EXTRACTION_PROMPT = """Below are reference YouTube thumbnails that have performed well for this channel. 
Analyze them collectively and extract the visual style DNA.

Return a structured analysis as Markdown with these exact sections:

# Channel Thumbnail Style Profile

## Color Palette
List dominant colors with hex codes and their typical role (background, accent, text)

## Typography
- Font weight (bold/regular/extra-bold)
- Size relative to thumbnail
- Color and outline/shadow treatment
- Position pattern (where text usually sits)

## Composition
- Subject placement (center / rule of thirds / etc.)
- Background treatment (solid, blurred, textured)
- Negative space usage

## Visual Identity
- Recurring graphic elements (arrows, circles, brackets, etc.)
- Face/expression patterns if applicable
- Overall emotional tone (energetic, calm, dramatic, professional)

## What Makes These Work
3-5 specific takeaways that should guide new thumbnails for this channel.

Be specific and concrete. This document will be used as a generation guide."""


def _load_reference_images() -> list[dict]:
    """Load all images from thumbnail_reference/ as base64 data URLs."""
    ref_dir = Path(settings.THUMBNAIL_REFERENCE_DIR)
    if not ref_dir.exists():
        logger.warning(f"Reference dir {ref_dir} doesn't exist")
        return []
    
    images = []
    for path in sorted(ref_dir.iterdir()):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        try:
            with open(path, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode()
            mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else f"image/{path.suffix[1:]}"
            images.append({
                "url": f"data:{mime};base64,{data}",
                "filename": path.name
            })
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
    
    return images


def build_style_profile() -> str | None:
    """
    Analyze all reference thumbnails and write style_profile.md.
    Run this manually whenever thumbnail_reference/ contents change.
    """
    images = _load_reference_images()
    if not images:
        logger.error("No reference thumbnails found")
        return None
    
    logger.info(f"Building style profile from {len(images)} references")
    
    image_urls = [img["url"] for img in images]
    
    try:
        # We expect a Markdown response, not JSON, so use a free-form chat
        from app.openrouter import chat_text  # See note below — add this helper
        markdown = chat_text(
            system="You are a senior brand designer analyzing visual style.",
            user=STYLE_EXTRACTION_PROMPT,
            image_urls=image_urls,
            model=settings.THUMBNAIL_VALIDATION_MODEL
        )
        
        output_path = Path(settings.STYLE_PROFILE_PATH)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(markdown)
        
        logger.info(f"Style profile written to {output_path}")
        return markdown
        
    except Exception as e:
        logger.error(f"Style profile build failed: {e}")
        return None


def load_style_profile() -> str | None:
    """Read the cached style profile MD file."""
    path = Path(settings.STYLE_PROFILE_PATH)
    if not path.exists():
        logger.warning(f"Style profile missing at {path}. Run build_style_profile() first.")
        return None
    return path.read_text()
```

### 4.2 Add `chat_text` helper to `openrouter.py`

The existing `chat_json` forces JSON mode. Add a sibling that returns plain text for the style profile (Markdown output):

```python
def chat_text(
    system: str,
    user: str,
    image_urls: list[str] | None = None,
    model: str | None = None
) -> str:
    """Same as chat_json but returns plain text (no JSON mode)."""
    # Mirror chat_json's logic but skip response_format={"type": "json_object"}
    # and return the message content as-is.
```

### 4.3 Build endpoint

Add to `app/main.py`:

```python
@app.post("/style-profile/rebuild")
def rebuild_style_profile():
    """Rebuild style_profile.md from thumbnail_reference/ folder. Run when refs change."""
    from app.style_profile import build_style_profile
    result = build_style_profile()
    if not result:
        raise HTTPException(500, "Style profile build failed")
    return {"status": "ok", "preview": result[:500]}
```

---

## Phase 5 — Content-Aware Audit

### 5.1 Update `app/audits.py`

Replace `_build_user_block()` with a content-aware version that includes transcript, keyframe insights, and a hard language rule injected at the top of every user message.

```python
def _build_user_block(
    video: dict,
    transcript: str | None,
    transcript_lang: str | None,
    best_keyframe: dict | None,
    channel_language: str,  # from channels.default_language
) -> str:
    """Build the audit user message with transcript, keyframe context, and language rule."""
    from app.transcripts import lang_display_name

    channel_lang_name = lang_display_name(channel_language)
    transcript_lang_name = lang_display_name(transcript_lang) if transcript_lang else "unknown"

    lines = [
        # ── Language rule — always first, always explicit ──────────────────
        "LANGUAGE RULE (non-negotiable):",
        f"  Channel configured language: {channel_language} ({channel_lang_name}).",
        "  The transcript is a CONTENT SIGNAL ONLY — use it to understand what the",
        "  video is about. Do NOT use its language for output.",
        f"  ALL output (title, description, tags) must be written for a",
        f"  {channel_lang_name}-speaking audience.",
        f"  Use whatever mix of {channel_lang_name} and English performs best on",
        "  YouTube for this content type and audience. This is your editorial call.",
        "  NEVER let the transcript language override the channel's configured language.",
        "",
        # ── Current metadata ───────────────────────────────────────────────
        "VIDEO METADATA (CURRENT — may be placeholder/inadequate):",
        f"Title: {video.get('title', '')}",
        f"Description: {(video.get('description') or '')[:1500]}",
        f"Tags: {', '.join(video.get('tags', []) or [])}",
        f"Views: {video.get('view_count', 0)}",
        f"Likes: {video.get('like_count', 0)}",
        f"Published: {video.get('published_at', '')}",
    ]

    # ── Transcript ─────────────────────────────────────────────────────────
    if transcript:
        lines += [
            "",
            f"VIDEO TRANSCRIPT (language detected: {transcript_lang_name} — content signal only):",
            transcript,
        ]
    else:
        lines += [
            "",
            "VIDEO TRANSCRIPT: not available — base content judgment on metadata + visuals only.",
        ]

    # ── Keyframe context ───────────────────────────────────────────────────
    if best_keyframe:
        ka = best_keyframe.get("analysis", {})
        lines += ["", "BEST VIDEO FRAME ANALYSIS:"]
        lines.append(f"Subjects: {', '.join(ka.get('subjects', []))}")
        if ka.get("on_screen_text"):
            lines.append(f"On-screen text: {ka['on_screen_text']}")
        if ka.get("facial_expression"):
            lines.append(f"Facial expression: {ka['facial_expression']}")

    lines += [
        "",
        "Thumbnail: attached as image" if video.get("thumbnail_url") else "Thumbnail: not available",
        "",
        "IMPORTANT: The current title and description may be placeholder text or poorly",
        "written. Use the transcript and visual analysis as the primary signal for what",
        "the video is actually about. Generate metadata that accurately reflects the",
        "actual content — do not just polish the existing metadata.",
        "",
        "Run the audit now and return only the JSON object.",
    ]

    return "\n".join(lines)
```

### 5.2 Update the default audit prompt (`DEFAULT_PROMPT`)

Add this block near the top of `DEFAULT_PROMPT` in `audits.py`, before the JSON shape specification:

```
CONTENT SOURCES:
You will receive: the current title/description/tags (which may be placeholder or
inadequate), the video transcript when available (in any language — treat it as a
content signal only), analysis of the most thumbnail-worthy frame, and the current
thumbnail image.

Treat the transcript and frame analysis as the primary source of truth for what the
video is about. The current metadata is a starting point, not a constraint — generate
suggestions that reflect the actual video content, even if that means rewriting from
scratch.

LANGUAGE:
The user message will specify the channel's configured language. All your output must
target that language and audience regardless of what language the transcript is in.
Use the best-performing mix of the channel language and English for YouTube — this is
your editorial judgment call.
```

### 5.3 Update `audit_video()` orchestration

```python
def audit_video(video_id: str) -> dict:
    """Run a content-aware audit for a single video."""
    video = _load_video(video_id)
    _refuse_if_not_public(video)

    # Load channel for default_language
    channel = supabase.table("channels").select("default_language").eq(
        "id", video["channel_id"]
    ).single().execute().data
    channel_language = channel.get("default_language") or "en"

    # 1. Fetch transcript (graceful degradation — returns text + detected lang)
    transcript, transcript_lang = fetch_transcript(video_id)
    transcript_available = transcript is not None

    # 2. Extract & analyze keyframes
    keyframes = extract_keyframes(video_id)
    best_keyframe = None
    if keyframes:
        best_keyframe = pick_best_keyframe(video_id, keyframes)

    # 3. Build prompt with all context including language rule
    system_prompt = _load_channel_prompt(video["channel_id"])
    user_block = _build_user_block(
        video=video,
        transcript=transcript,
        transcript_lang=transcript_lang,
        best_keyframe=best_keyframe,
        channel_language=channel_language,
    )

    image_urls = []
    if video.get("thumbnail_url"):
        image_urls.append(video["thumbnail_url"])
    if best_keyframe:
        image_urls.append(best_keyframe["url"])

    # 4. Run audit (existing logic, with retry-text-on-image-failure)
    audit_json = _call_audit_llm(system_prompt, user_block, image_urls)

    # 5. Persist audit row
    audit_row = supabase.table("audits").insert({
        "video_id": video_id,
        "channel_id": video["channel_id"],
        "status": "pending",
        "suggested_title": audit_json.get("comparisons", {}).get("title", {}).get("suggested"),
        "suggested_description": audit_json.get("comparisons", {}).get("description", {}).get("suggested"),
        "suggested_tags": audit_json.get("comparisons", {}).get("tags", {}).get("suggested"),
        "issues_found": audit_json.get("issues"),
        "ai_reasoning": audit_json.get("reasoning"),
        "transcript_available": transcript_available,
        "keyframes_extracted": len(keyframes),
        # ... existing before-state fields ...
    }).execute().data[0]
    
    # 6. Generate thumbnail if enabled
    if settings.THUMBNAIL_GENERATION_ENABLED:
        from app.thumbnail_generator import generate_thumbnail_for_audit
        generate_thumbnail_for_audit(
            audit_id=audit_row["id"],
            video_id=video_id,
            best_keyframe=best_keyframe,
        )
    
    return audit_row
```

---

## Phase 6 — Thumbnail Generation (Autonomous)

### 6.1 Create `app/thumbnail_generator.py`

```python
"""Autonomous thumbnail generation with self-validation and regeneration."""
import base64
import logging
import uuid
from typing import Optional

from app.config import settings
from app.db import supabase
from app.openrouter import chat_json, chat_image_gen
from app.style_profile import load_style_profile

logger = logging.getLogger(__name__)


GENERATION_SYSTEM = """You are generating a YouTube thumbnail. Output a single 16:9 image.
The thumbnail must be visually striking, brand-consistent, and readable at 200x112px (mobile preview)."""


def _build_generation_prompt(
    video_title: str,
    channel_language: str,
    style_profile_md: str,
    best_keyframe_analysis: dict | None,
    audit_summary: str | None
) -> str:
    """Build the image-generation prompt with language rule for on-thumbnail text."""
    from app.transcripts import lang_display_name
    channel_lang_name = lang_display_name(channel_language)

    parts = [
        f'Generate a YouTube thumbnail for this video title: "{video_title}"',
        "",
        # Language rule for thumbnail text
        f"LANGUAGE RULE FOR THUMBNAIL TEXT (non-negotiable):",
        f"  This is a {channel_lang_name} channel ({channel_language}).",
        f"  Any text rendered on the thumbnail must be in {channel_lang_name} or a",
        f"  {channel_lang_name}/English mix that performs well for this audience.",
        f"  Do NOT default to English-only text on the thumbnail.",
        "",
        "STYLE GUIDELINES (must follow):",
        style_profile_md,
        "",
    ]
    
    if best_keyframe_analysis:
        parts.extend([
            "VIDEO CONTENT CONTEXT:",
            f"- Subjects in video: {', '.join(best_keyframe_analysis.get('subjects', []))}",
        ])
        if best_keyframe_analysis.get("on_screen_text"):
            parts.append(f"- Visible video text: {best_keyframe_analysis['on_screen_text']}")
        if best_keyframe_analysis.get("facial_expression"):
            parts.append(f"- Reference expression: {best_keyframe_analysis['facial_expression']}")
        parts.append("")
    
    parts.extend([
        "REQUIREMENTS:",
        "- 16:9 landscape aspect ratio (1280x720)",
        "- Bold, legible typography",
        "- High contrast for small-screen visibility",
        "- No watermarks, no YouTube logo, no text in unreadable fonts",
    ])
    
    return "\n".join(parts)


def _generate_image(prompt: str, reference_image_urls: list[str]) -> bytes | None:
    """Call OpenRouter image-gen model. Returns image bytes."""
    try:
        # OpenRouter image gen via Gemini 2.5 Flash Image
        # The model accepts reference images for style transfer
        image_b64 = chat_image_gen(
            prompt=prompt,
            reference_images=reference_image_urls,
            model=settings.THUMBNAIL_GEN_MODEL,
        )
        return base64.b64decode(image_b64)
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        return None


VALIDATION_PROMPT = """You are validating an AI-generated YouTube thumbnail against a brand style guide.

Score this thumbnail's adherence to the style profile and overall quality.

Return JSON only:
{
  "style_match_score": 0.0-1.0,
  "quality_score": 0.0-1.0,
  "overall_score": 0.0-1.0,
  "passes": true|false,
  "issues": ["list any problems"],
  "matches_style": ["list aspects that match the brand"],
  "verdict": "one sentence summary"
}

A thumbnail passes if overall_score >= {threshold} AND has no critical issues 
(unreadable text, broken composition, off-brand colors, generic AI feel)."""


def _validate_thumbnail(image_url: str, style_profile_md: str, threshold: float) -> dict | None:
    """Vision-validate the generated thumbnail against the style profile."""
    try:
        prompt = (
            f"STYLE PROFILE TO MATCH:\n{style_profile_md}\n\n"
            + VALIDATION_PROMPT.replace("{threshold}", str(threshold))
        )
        result = chat_json(
            system="You are a strict brand design reviewer. Return only valid JSON.",
            user=prompt,
            image_urls=[image_url],
            model=settings.THUMBNAIL_VALIDATION_MODEL
        )
        return result
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return None


def _upload_thumbnail(audit_id: int, video_id: str, image_bytes: bytes, n: int) -> tuple[str, str] | None:
    """Upload generated thumbnail to Supabase Storage. Returns (storage_path, signed_url)."""
    try:
        storage_path = f"{video_id}/{audit_id}-{n}.png"
        supabase.storage.from_("generated-thumbs").upload(
            path=storage_path,
            file=image_bytes,
            file_options={"content-type": "image/png", "upsert": "true"}
        )
        signed = supabase.storage.from_("generated-thumbs").create_signed_url(
            path=storage_path, expires_in=3600
        )
        return storage_path, signed["signedURL"]
    except Exception as e:
        logger.error(f"Thumbnail upload failed: {e}")
        return None


def generate_thumbnail_for_audit(
    audit_id: int,
    video_id: str,
    best_keyframe: dict | None
) -> dict | None:
    """
    Autonomous thumbnail generation loop:
    1. Generate
    2. Validate against style profile
    3. Pass → mark selected, return
    4. Fail → regenerate (up to MAX_REGENERATIONS)
    5. After all attempts fail → mark audit for human review
    """
    style_profile = load_style_profile()
    if not style_profile:
        logger.error("No style profile available — skipping thumbnail generation")
        _update_audit_status(audit_id, "failed_generation", reason="no_style_profile")
        return None
    
    # Load audit + video + channel for context
    audit = supabase.table("audits").select("*").eq("id", audit_id).single().execute().data
    video_title = audit.get("suggested_title") or "Untitled"
    audit_summary = audit.get("ai_reasoning")

    # Get channel language
    channel = supabase.table("channels").select("default_language").eq(
        "id", audit["channel_id"]
    ).single().execute().data
    channel_language = channel.get("default_language") or "en"

    # Load reference image URLs (signed) so the gen model can use them
    reference_urls = _get_reference_image_urls()

    _update_audit_status(audit_id, "generating")

    prompt = _build_generation_prompt(
        video_title=video_title,
        channel_language=channel_language,
        style_profile_md=style_profile,
        best_keyframe_analysis=best_keyframe.get("analysis") if best_keyframe else None,
        audit_summary=audit_summary,
    )
    
    for attempt in range(1, settings.THUMBNAIL_MAX_REGENERATIONS + 1):
        logger.info(f"Thumbnail generation attempt {attempt}/{settings.THUMBNAIL_MAX_REGENERATIONS} for audit {audit_id}")
        
        image_bytes = _generate_image(prompt, reference_urls)
        if not image_bytes:
            continue
        
        upload = _upload_thumbnail(audit_id, video_id, image_bytes, attempt)
        if not upload:
            continue
        
        storage_path, signed_url = upload
        
        # Validate
        validation = _validate_thumbnail(signed_url, style_profile, settings.THUMBNAIL_VALIDATION_THRESHOLD)
        if not validation:
            continue
        
        score = validation.get("overall_score", 0.0)
        passes = validation.get("passes", False) and score >= settings.THUMBNAIL_VALIDATION_THRESHOLD
        
        # Persist generation row
        gen_row = supabase.table("generated_thumbnails").insert({
            "audit_id": audit_id,
            "video_id": video_id,
            "storage_path": storage_path,
            "prompt_used": prompt,
            "model": settings.THUMBNAIL_GEN_MODEL,
            "generation_n": attempt,
            "validation_score": score,
            "validation_feedback": validation,
            "selected": passes,
        }).execute().data[0]
        
        if passes:
            logger.info(f"Thumbnail passed validation on attempt {attempt} (score: {score})")
            _update_audit_status(audit_id, "success", selected_thumbnail_id=gen_row["id"])
            return gen_row
        else:
            logger.info(f"Thumbnail failed validation on attempt {attempt} (score: {score}). Issues: {validation.get('issues')}")
            # Augment prompt with feedback for next attempt
            prompt = _refine_prompt(prompt, validation)
    
    # All attempts exhausted
    logger.warning(f"All {settings.THUMBNAIL_MAX_REGENERATIONS} thumbnail attempts failed for audit {audit_id}")
    _update_audit_status(audit_id, "failed_validation")
    return None


def _refine_prompt(original_prompt: str, validation: dict) -> str:
    """Augment the prompt with validation feedback for the next attempt."""
    issues = validation.get("issues", [])
    if not issues:
        return original_prompt
    
    refinement = "\n\nPREVIOUS ATTEMPT ISSUES (must fix):\n"
    refinement += "\n".join(f"- {issue}" for issue in issues)
    return original_prompt + refinement


def _update_audit_status(audit_id: int, status: str, selected_thumbnail_id: int | None = None, reason: str | None = None):
    """Update audit row with thumbnail generation outcome."""
    update = {"thumbnail_generation_status": status}
    if selected_thumbnail_id is not None:
        update["selected_thumbnail_id"] = selected_thumbnail_id
    supabase.table("audits").update(update).eq("id", audit_id).execute()


def _get_reference_image_urls() -> list[str]:
    """Build data URLs for all reference thumbnails."""
    from pathlib import Path
    ref_dir = Path(settings.THUMBNAIL_REFERENCE_DIR)
    urls = []
    for path in sorted(ref_dir.iterdir()):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else f"image/{path.suffix[1:]}"
        urls.append(f"data:{mime};base64,{data}")
    return urls
```

### 6.2 Add `chat_image_gen` to `openrouter.py`

OpenRouter's image-gen models return image data in the response. Add a helper:

```python
def chat_image_gen(
    prompt: str,
    reference_images: list[str] | None = None,
    model: str = "google/gemini-2.5-flash-image"
) -> str:
    """
    Call an image-generation model on OpenRouter.
    Returns base64-encoded image data.
    
    For Gemini 2.5 Flash Image, reference images are included as image_url 
    blocks in the user message, and the response includes a generated image
    in the assistant's content.
    """
    content = [{"type": "text", "text": prompt}]
    if reference_images:
        for img_url in reference_images:
            content.append({"type": "image_url", "image_url": {"url": img_url}})
    
    response = openrouter_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        modalities=["image", "text"],  # Request image output
    )
    
    # Parse response — Gemini returns image in the message content
    # The exact response shape depends on OpenRouter's pass-through; check:
    # https://openrouter.ai/docs/features/multimodal/image-generation
    msg = response.choices[0].message
    
    # Try common shapes
    if hasattr(msg, "images") and msg.images:
        # Direct image attachment
        return msg.images[0].get("image_url", {}).get("url", "").split(",")[-1]
    
    # Fallback: image embedded in content blocks
    if isinstance(msg.content, list):
        for block in msg.content:
            if block.get("type") == "image_url":
                url = block["image_url"]["url"]
                if url.startswith("data:"):
                    return url.split(",")[-1]
    
    raise ValueError("No image returned from generation model")
```

Note: confirm exact response shape against OpenRouter's current docs — the SDK surface for image gen evolved recently. Adjust the parsing accordingly.

---

## Phase 7 — Apply Path: Upload Generated Thumbnail to YouTube

### 7.1 Update `apply_audit_internal()` in `audits.py`

After `videos.update()` succeeds, if a selected thumbnail exists, upload it:

```python
def apply_audit_internal(audit_id: int) -> dict:
    audit = _load_audit(audit_id)
    if settings.DRY_RUN:
        return {"status": "dry_run"}
    
    # Existing snippet update
    youtube = _build_youtube_client(audit["channel_id"])
    youtube.videos().update(
        part="snippet",
        body={
            "id": audit["video_id"],
            "snippet": {
                "title": audit["suggested_title"],
                "description": audit["suggested_description"],
                "tags": audit["suggested_tags"],
                "categoryId": _resolve_category(audit),
                "selfDeclaredMadeForKids": True,
            }
        }
    ).execute()
    
    # NEW: Upload thumbnail if one was selected
    if audit.get("selected_thumbnail_id"):
        _apply_generated_thumbnail(youtube, audit)
    
    # Mark applied
    supabase.table("audits").update({
        "status": "applied",
        # ... baseline stats etc ...
    }).eq("id", audit_id).execute()
    
    return {"status": "applied"}


def _apply_generated_thumbnail(youtube, audit: dict):
    """Download selected generated thumbnail from Supabase Storage, upload to YouTube."""
    from googleapiclient.http import MediaIoBaseUpload
    import io
    
    gen_thumb = supabase.table("generated_thumbnails").select("*").eq(
        "id", audit["selected_thumbnail_id"]
    ).single().execute().data
    
    # Download from Supabase Storage
    file_bytes = supabase.storage.from_("generated-thumbs").download(gen_thumb["storage_path"])
    
    # Upload to YouTube
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="image/png")
    youtube.thumbnails().set(
        videoId=audit["video_id"],
        media_body=media
    ).execute()
    
    logger.info(f"Uploaded thumbnail to YouTube for video {audit['video_id']}")
```

Note: YouTube `thumbnails.set` costs **50 quota units** per call — your `quota.py` tracker needs to charge for it.

---

## Phase 8 — Quota Accounting

### 8.1 Update `quota.py`

Add the new operations:

```python
QUOTA_COSTS = {
    "videos.list": 1,        # per call (up to 50)
    "videos.update": 50,     # per call
    "thumbnails.set": 50,    # NEW — per call
    "playlistItems.list": 1, # per call
    "channels.list": 1,      # per call
}
```

In `_apply_generated_thumbnail()`, charge the quota:

```python
quota.charge("thumbnails.set", channel_id=audit["channel_id"])
```

In `autopilot.tick()`, check both `videos.update` (50) AND `thumbnails.set` (50) when a thumbnail is queued — i.e. budget for **100 units** per video with thumbnail vs **50 units** without.

---

## Phase 9 — Frontend (Minimal Additions)

### 9.1 Channel page — show thumbnail on review row

Update `channel.html`'s audit row UI: if `selected_thumbnail_id` is set, show the generated thumbnail next to the current one.

```html
<!-- In the audit suggestion expansion area -->
<div class="thumbnail-comparison">
  <div>
    <h5>Current</h5>
    <img src="{{ video.thumbnail_url }}" />
  </div>
  {% if audit.selected_thumbnail_id %}
  <div>
    <h5>Generated</h5>
    <img src="{{ generated_thumbnail_signed_url }}" />
    <small>Validation: {{ generated.validation_score }}</small>
  </div>
  {% endif %}
</div>
```

Endpoint to fetch signed URL:

```python
@app.get("/audits/{audit_id}/thumbnail")
def get_audit_thumbnail(audit_id: int):
    audit = supabase.table("audits").select("selected_thumbnail_id").eq("id", audit_id).single().execute().data
    if not audit or not audit["selected_thumbnail_id"]:
        return {"url": None}
    
    gen = supabase.table("generated_thumbnails").select("*").eq(
        "id", audit["selected_thumbnail_id"]
    ).single().execute().data
    
    signed = supabase.storage.from_("generated-thumbs").create_signed_url(
        path=gen["storage_path"], expires_in=3600
    )
    return {"url": signed["signedURL"], "validation_score": gen["validation_score"]}
```

### 9.2 Style profile rebuild button

On a settings/admin page, add a button that calls `POST /style-profile/rebuild`. Show a preview of the generated MD.

---

## Phase 10 — Implementation Order

Build and test in this order:

1. **DB migrations** — create the new tables and storage buckets
2. **Transcripts** — `app/transcripts.py`, test on a few videos manually
3. **Style profile** — drop your reference thumbs into `thumbnail_reference/`, run `/style-profile/rebuild`, eyeball the output MD, tweak by hand if needed
4. **Keyframe extraction** — verify `yt-dlp` + `ffmpeg` on your machine, run on one video, check Supabase Storage
5. **Frame analysis** — vision-analyze the keyframes, verify `pick_best_keyframe` selects sane frames
6. **Content-aware audit** — wire transcript + keyframe into `audit_video()`, audit one video, compare suggestions to the previous audit format
7. **Thumbnail generation (flag OFF)** — implement, test the loop manually with `THUMBNAIL_GENERATION_ENABLED=true` for one video
8. **Validation loop** — verify regenerations actually improve, tune the threshold
9. **Apply path** — test with `DRY_RUN=true`, confirm everything except the YouTube write
10. **Real apply** — flip `DRY_RUN=false` on a single non-critical video, verify thumbnail lands on YouTube
11. **Autopilot integration** — let the autopilot tick pick up the new flow on one channel

---

## Phase 11 — Cost Estimates (rough)

Per video, with thumbnail generation enabled:

| Step | Calls | Approx cost |
|---|---|---|
| Transcript fetch | 0 LLM, 0 quota | Free |
| Keyframe extraction | 0 LLM | yt-dlp + ffmpeg CPU only |
| Keyframe analysis | 8 vision calls | ~$0.005–0.01 |
| Audit | 1 vision call | ~$0.002 |
| Thumbnail gen (1–3 attempts) | 1–3 image-gen + 1–3 validation | ~$0.04–0.15 |
| Thumbnail apply (YouTube) | 50 quota units | — |
| Audit apply (YouTube) | 50 quota units | — |
| **Total per video** | — | **~$0.05–0.20** |

For 1000 videos with thumbnails: ~$50–200 in LLM + 100,000 YouTube quota units (need quota increase).

---

## Phase 12 — Open Decisions / Things to Watch

1. **Style profile staleness** — when you add a new reference thumbnail, you must re-run `/style-profile/rebuild`. Consider auto-detecting changes via a folder hash stored in the DB.
2. **Stream URL expiry** — `yt-dlp` URLs typically expire in ~6 hours. Always extract frames immediately, never store the URL.
3. **Region-locked videos** — `yt-dlp` might fail on videos restricted in your machine's region. Add error handling and log clearly.
4. **Keyframe at exact timestamps** — `ffmpeg -ss` before `-i` is fast but seeks to the nearest keyframe (not frame-accurate). Acceptable for thumbnail purposes; if you need frame-accuracy, move `-ss` after `-i` (much slower).
5. **Validation scoring drift** — the validator is the same model family as the generator. Consider using a different model for validation to reduce bias (e.g. generate with Gemini, validate with a different provider on OpenRouter).
6. **Thumbnail size** — Gemini 2.5 Flash Image outputs 1024x1024 by default. Post-process with PIL to crop/letterbox to YouTube's required 1280x720 (16:9). Add this as a step between generation and upload.
7. **`default_language` not set** — if a channel has `default_language = null`, the system falls back to `"en"`. Consider adding a UI warning for channels with no language set, since this affects every audit and every thumbnail.
8. **Multilingual title/description mix** — the LLM decides the best language mix. You may want to review early outputs per channel to confirm the mix feels right before enabling autopilot at scale.

---

## Files to create

```
app/
  transcripts.py           NEW
  keyframes.py             NEW
  style_profile.py         NEW
  thumbnail_generator.py   NEW

supabase/migrations/
  XXX_thumbnail_generation.sql   NEW

thumbnail_reference/
  style_profile.md         NEW (auto-generated)
  *.jpg, *.png             your reference thumbs

storage/keyframes/         NEW (temp dir, gitignored)
```

## Files to modify

```
app/audits.py              add transcript + keyframe to audit, hook thumbnail gen
app/openrouter.py          add chat_text + chat_image_gen helpers
app/quota.py               add thumbnails.set cost
app/config.py              add new settings
app/main.py                add /style-profile/rebuild + /audits/{id}/thumbnail endpoints
app/static/channel.html    add thumbnail comparison UI
requirements.txt           add new deps
.env.example               add new vars
```
