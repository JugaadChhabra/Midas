# Midas — Build Plan

## Overview

An AI-assisted tool that audits and optimizes metadata across a fleet of YouTube channels. It pulls video data via the YouTube Data API v3 using OAuth 2.0, analyzes it with an LLM, surfaces specific improvement suggestions, and lets you review and push approved changes back to YouTube — all from a single dashboard.

---

## What It Can Do

| Field | Read | Write | Notes |
|---|---|---|---|
| Title | Yes | Yes | Full control |
| Description | Yes | Yes | Full control |
| Tags | Yes | Yes | Full control |
| Thumbnail | Yes | Yes (upload) | Must supply image; channel must be phone-verified |
| Playlist membership | Yes | Yes | Can add/remove/create playlists |
| Category | Yes | Yes | Broad YouTube categories only |
| End screens / Cards | Yes | No | Not exposed in the API |
| Chapters | Indirectly | Indirectly | Parsed from description timestamps |
| Video file | No | No | API does not touch the video itself |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│                  Dashboard (Frontend)       │
│   Channel list · Audit queue · Review UI    │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│                Backend (Python)             │
│  Channel sync · Audit engine · Write-back   │
└──────┬──────────────────────────┬───────────┘
       │                          │
┌──────▼──────┐          ┌────────▼────────┐
│ YouTube     │          │  LLM API        │
│ Data API v3 │          │  Audit + rewrite│
└─────────────┘          └─────────────────┘
       │
┌──────▼──────┐
│  Database   │
│ (Postgres)  │
└─────────────┘
```

---

## Phase 1 — YouTube API Setup & Auth

### 1.1 What You've Already Done

- Created a Google Cloud project
- Enabled YouTube Data API v3
- Set up OAuth consent screen with scope `https://www.googleapis.com/auth/youtube`
- Created an OAuth 2.0 Client ID (Web application type)
- Set authorized JS origin: `http://localhost:3000`
- Set authorized redirect URI: `http://localhost:8000/auth/callback`
- Downloaded `client_secrets.json`

No separate API key needed — OAuth 2.0 handles both reading and writing everything.

### 1.2 Per-Channel Auth Flow

For each channel you want to manage, you run a one-time OAuth flow. Since you set up a Web application client, the flow goes through the browser via your FastAPI backend.

**FastAPI auth endpoints:**

```python
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import json, os

app = FastAPI()

SCOPES = ["https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS_FILE = "client_secrets.json"
REDIRECT_URI = "http://localhost:8000/auth/callback"

@app.get("/auth/login")
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"  # forces refresh token to be issued every time
    )
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
def callback(code: str, state: str):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # Save refresh token — do this per channel
    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
    }
    # In production, store this encrypted in your DB against the channel ID
    with open(f"tokens/channel_{state}.json", "w") as f:
        json.dump(token_data, f)

    return {"message": "Auth successful"}
```

Each channel owner visits `/auth/login` once. After that the refresh token is stored and your backend operates autonomously — no manual re-auth needed.

---

## Phase 2 — Data Ingestion

### 2.1 Fetching All Videos for a Channel

```python
from googleapiclient.discovery import build

youtube = build("youtube", "v3", developerKey=API_KEY)

def get_all_videos(channel_id):
    videos = []
    next_page_token = None

    # First get the uploads playlist ID
    channel_resp = youtube.channels().list(
        part="contentDetails",
        id=channel_id
    ).execute()
    uploads_playlist = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Paginate through all videos
    while True:
        playlist_resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=next_page_token
        ).execute()

        video_ids = [item["contentDetails"]["videoId"] for item in playlist_resp["items"]]

        # Fetch full metadata in batches of 50
        video_resp = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(video_ids)
        ).execute()

        videos.extend(video_resp["items"])
        next_page_token = playlist_resp.get("nextPageToken")
        if not next_page_token:
            break

    return videos
```

### 2.2 What You Get Per Video

```json
{
  "id": "VIDEO_ID",
  "snippet": {
    "title": "My Video Title",
    "description": "Full description text...",
    "tags": ["tag1", "tag2"],
    "thumbnails": {
      "maxres": { "url": "https://..." }
    },
    "categoryId": "22",
    "publishedAt": "2024-01-15T10:00:00Z"
  },
  "statistics": {
    "viewCount": "15420",
    "likeCount": "342",
    "commentCount": "28"
  }
}
```

### 2.3 Database Schema

```sql
CREATE TABLE channels (
    id TEXT PRIMARY KEY,
    name TEXT,
    handle TEXT,
    oauth_token_path TEXT,
    last_synced_at TIMESTAMP
);

CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    channel_id TEXT REFERENCES channels(id),
    title TEXT,
    description TEXT,
    tags TEXT[],
    thumbnail_url TEXT,
    view_count INTEGER,
    like_count INTEGER,
    published_at TIMESTAMP,
    last_fetched_at TIMESTAMP
);

CREATE TABLE audits (
    id SERIAL PRIMARY KEY,
    video_id TEXT REFERENCES videos(id),
    created_at TIMESTAMP DEFAULT NOW(),
    status TEXT DEFAULT 'pending', -- pending | approved | rejected | applied
    suggested_title TEXT,
    suggested_description TEXT,
    suggested_tags TEXT[],
    thumbnail_feedback TEXT,
    issues_found JSONB,
    ai_reasoning TEXT
);
```

---

## Phase 3 — AI Audit Engine

### 3.1 What the Audit Checks

**Title analysis:**
- Is it under 60 characters? (truncates in search results after ~60)
- Does it lead with the main keyword?
- Is it compelling / does it create curiosity?
- Does it have unnecessary filler words?

**Description analysis:**
- Are the first 2-3 lines (above the fold, ~157 chars) doing real work?
- Are there timestamps / chapters?
- Are there relevant links and CTAs?
- Is the target keyword mentioned naturally in the first paragraph?

**Tags analysis:**
- Are there 10-15 tags?
- Do they range from broad to specific?
- Are there obvious missing tags given the title/description?

**Thumbnail analysis (vision):**
- Is there a face? (faces drive higher CTR generally)
- Is text legible at small sizes?
- Is there high contrast?
- Is the composition clean and not cluttered?

**Performance-aware prioritization:**
- Videos with high impressions but low CTR → title/thumbnail issue
- Videos with high CTR but low watch time → not directly fixable via metadata, flagged for content note
- Low view count on older videos → may benefit most from metadata refresh

### 3.2 Audit Prompt Structure

```python
def build_audit_prompt(video: dict, channel_niche: str) -> str:
    return f"""
You are a YouTube SEO and content optimization expert. Audit this video's metadata for a {channel_niche} channel.

VIDEO DATA:
Title: {video['title']}
Description: {video['description'][:1000]}
Tags: {', '.join(video.get('tags', []))}
Views: {video['view_count']}
Published: {video['published_at']}

Return a JSON object with this exact structure:
{{
  "issues": [
    {{ "field": "title|description|tags|thumbnail", "severity": "high|medium|low", "problem": "...", "fix": "..." }}
  ],
  "suggested_title": "...",
  "suggested_description": "...",
  "suggested_tags": ["tag1", "tag2", ...],
  "thumbnail_feedback": "...",
  "reasoning": "Brief summary of main issues"
}}

Rules:
- suggested_title must be under 70 characters
- suggested_description must open with a compelling first 2 lines
- suggested_tags should have 12-15 tags, mix of broad and specific
- Be specific and actionable, not generic
- Preserve the channel's voice — do not make it sound generic
"""
```

### 3.3 Batching Strategy

To avoid quota exhaustion and API rate limits:

- Process one channel at a time
- Within a channel, prioritize videos by: (high views + low engagement) first, then oldest videos with no recent update
- Add a 1-second delay between video API calls
- Store audit results to DB immediately so work isn't lost if something crashes
- Run audits on a schedule (e.g. weekly cron) rather than all at once

---

## Phase 4 — Write-Back Engine

### 4.1 Updating Video Metadata

```python
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

def update_video(channel_id: str, video_id: str, audit: dict):
    creds = load_credentials(channel_id)  # load from stored token
    youtube = build("youtube", "v3", credentials=creds)

    youtube.videos().update(
        part="snippet",
        body={
            "id": video_id,
            "snippet": {
                "title": audit["suggested_title"],
                "description": audit["suggested_description"],
                "tags": audit["suggested_tags"],
                "categoryId": "22"  # preserve or update as needed
            }
        }
    ).execute()
```

### 4.2 Uploading a Custom Thumbnail

```python
from googleapiclient.http import MediaFileUpload

def upload_thumbnail(channel_id: str, video_id: str, image_path: str):
    creds = load_credentials(channel_id)
    youtube = build("youtube", "v3", credentials=creds)

    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(image_path, mimetype="image/jpeg")
    ).execute()
```

Note: The channel must be phone-verified for custom thumbnails to work.

### 4.3 Adding a Video to a Playlist

```python
def add_to_playlist(channel_id: str, video_id: str, playlist_id: str):
    creds = load_credentials(channel_id)
    youtube = build("youtube", "v3", credentials=creds)

    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                }
            }
        }
    ).execute()
```

---

## Phase 5 — Review Dashboard

This is the human-in-the-loop layer. No change goes live without approval.

### Key screens:

**Channel overview** — list of all 20 channels, last synced, number of videos, number of pending audits

**Audit queue** — list of videos flagged with issues, sorted by severity/potential impact. Each row shows the video thumbnail, current title, and a summary of issues found.

**Video review screen** — side-by-side view:
- Left: current title / description / tags
- Right: AI-suggested version
- Diff highlighting so changes are obvious
- Thumbnail feedback panel
- Accept / Reject / Edit buttons per field

**Bulk approve** — approve all suggested changes for a channel or a filtered set (e.g. all "high severity title issues")

**Apply log** — history of all changes pushed, with timestamps and before/after values

### Tech stack suggestion:

- **Backend**: Python (FastAPI)
- **Database**: PostgreSQL
- **Frontend**: React + Tailwind (or even a simpler Next.js setup)
- **Job queue**: Celery + Redis (for scheduled syncs and audit runs)
- **Auth storage**: Encrypted JSON files or Postgres with encrypted columns for OAuth tokens

---

## Phase 6 — Quota Management

YouTube Data API v3 quota costs:

| Operation | Cost (units) |
|---|---|
| `videos.list` | 1 per call (up to 50 videos) |
| `videos.update` | 50 per call |
| `thumbnails.set` | 50 per call |
| `playlistItems.insert` | 50 per call |
| `channels.list` | 1 per call |

Default daily quota: **10,000 units**

With 20 channels and ~50 videos each (1,000 videos total):
- Reading all videos: ~20-30 units total (very cheap)
- Updating all metadata: 1,000 × 50 = 50,000 units (need quota increase)

**Strategy**: Don't update everything at once. Prioritize high-impact videos first and spread updates across days. You can apply for a quota increase via the Google Cloud Console once you have a use case to describe.

---

## Rollout Order

1. Set up Google Cloud project + YouTube Data API + OAuth
2. Write the channel sync script — pull all videos for one channel, store in DB
3. Write the audit engine — run one video through the LLM, verify output format
4. Build the review UI — even a minimal one (React or just a CLI prompt for now)
5. Wire up the write-back — test on a single non-critical video first
6. Add thumbnail feedback (vision model on thumbnail URL)
7. Scale to all 20 channels
8. Add scheduling (weekly cron audit runs)
9. Add quota tracking and alerting

---

## Open Questions Before Starting

- Are all 20 channels owned by you, or are some client channels needing their OAuth consent?
- Are the channels in the same niche, or different verticals? (affects how you prompt the LLM — niche-specific prompts outperform generic ones)
- Do you want a web dashboard, or would a CLI + spreadsheet export be enough for v1?
- Do you want thumbnail generation (AI-generated new thumbnails) or just feedback on existing ones?
- Weekly scheduled audits, or on-demand only?