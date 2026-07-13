import os
from dotenv import load_dotenv

load_dotenv()

# Tolerate scope mismatch between the request and Google's token response.
# Needed when a re-consenting user unchecks the analytics scope box: Google
# returns a smaller scope set than we requested, and oauthlib would otherwise
# raise. We detect the actual grant via creds.granted_scopes in /auth/callback.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


class Settings:
    CLIENT_SECRETS_FILE = os.getenv("CLIENT_SECRETS_FILE", "client_secret.json")
    OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")
    SCOPES = [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.readonly",
        # Loop 0 sensor — per-video CTR + per-playlist session metrics.
        # Existing tokens were granted without this scope; each channel must re-consent.
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]
    ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"

    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    AUDIT_MODEL = os.getenv("AUDIT_MODEL") or "anthropic/claude-haiku-4.5"
    PROMPT_GEN_MODEL = os.getenv("PROMPT_GEN_MODEL") or "google/gemini-2.0-flash-001"
    REFLECTION_MODEL = os.getenv("REFLECTION_MODEL") or "anthropic/claude-sonnet-4-6"

    SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    YT_DAILY_QUOTA = int(os.getenv("YT_DAILY_QUOTA") or "10000")
    YT_QUOTA_SAFETY_BUFFER = int(os.getenv("YT_QUOTA_SAFETY_BUFFER") or "300")
    AUTOPILOT_TICK_SECONDS = int(os.getenv("AUTOPILOT_TICK_SECONDS") or "120")

    # Working/cache dir for locally cut shorts.
    SHORTS_CACHE_DIR    = os.getenv("SHORTS_CACHE_DIR", "./shorts_cache")

    # Where to write rotating log files (in addition to stdout). Bind-mounted to
    # the host in docker-compose so a quota-failed run is still traceable after
    # the container has been pruned.
    LOG_DIR             = os.getenv("LOG_DIR", "logs")
    LOG_LEVEL           = os.getenv("LOG_LEVEL", "INFO").upper()

    # YouTube transcript proxy (to work around IP bans)
    # Option A: any HTTP/HTTPS/SOCKS proxy  e.g. "http://user:pass@host:port"
    YOUTUBE_PROXY_URL = os.getenv("YOUTUBE_PROXY_URL", "")
    # Option B: Webshare rotating residential proxy (recommended for cloud deployments)
    WEBSHARE_PROXY_USERNAME = os.getenv("WEBSHARE_PROXY_USERNAME", "")
    WEBSHARE_PROXY_PASSWORD = os.getenv("WEBSHARE_PROXY_PASSWORD", "")

    # Set to false to skip human review and execute playlist changes directly (autopilot mode).
    PLAYLIST_HITL = os.getenv("PLAYLIST_HITL", "true").lower() == "true"

    # Playlist assignment thresholds (cosine similarity, 0–1)
    PLAYLIST_JOIN_HIGH    = float(os.getenv("PLAYLIST_JOIN_HIGH")    or "0.72")  # direct add
    PLAYLIST_JOIN_LOW     = float(os.getenv("PLAYLIST_JOIN_LOW")     or "0.55")  # haiku band lower bound
    PLAYLIST_LEAVE        = float(os.getenv("PLAYLIST_LEAVE")        or "0.60")  # haiku-confirmed removal
    PLAYLIST_MUTATION_CAP = int(os.getenv("PLAYLIST_MUTATION_CAP")   or "20")    # max add+remove per reconcile

    # Phase 1B — Playlist health scoring (recommend-only).
    # PO §Config table defaults; PHASE_1B_PLAN.md §5.5 for justification.
    # Thresholds intentionally stricter than the plan's 10 / 33 — the pilot
    # is bootstrapping trust, so false-positive `remove` recommendations are
    # more costly than missed ones. Loosen after a clean rollout-watch week.
    MIN_PLAYLIST_STARTS                 = int(os.getenv("MIN_PLAYLIST_STARTS")                 or "50")
    PLAYLIST_MEASUREMENT_WINDOW_DAYS    = int(os.getenv("PLAYLIST_MEASUREMENT_WINDOW_DAYS")    or "35")
    PLAYLIST_HEALTH_AGG_WEEKS           = int(os.getenv("PLAYLIST_HEALTH_AGG_WEEKS")           or "4")
    PLAYLIST_HEALTH_REMOVE_PCTL         = int(os.getenv("PLAYLIST_HEALTH_REMOVE_PCTL")         or "5")
    PLAYLIST_HEALTH_REVIVE_PCTL         = int(os.getenv("PLAYLIST_HEALTH_REVIVE_PCTL")         or "20")

    # Phase 1A — CIL Loop 1 (per-video measurement). §1.9 config table.
    # Per-channel gate is channels.measurement_enabled (DB flag, not env).
    MEASUREMENT_WINDOW_DAYS   = int(os.getenv("MEASUREMENT_WINDOW_DAYS")   or "21")
    MIN_IMPRESSIONS           = int(os.getenv("MIN_IMPRESSIONS")           or "500")
    CTR_WIN_THRESHOLD         = float(os.getenv("CTR_WIN_THRESHOLD")         or "0.10")   # relative, +10%
    CTR_REGRESSION_THRESHOLD  = float(os.getenv("CTR_REGRESSION_THRESHOLD")  or "-0.10")  # relative, -10%
    MAX_REDO                  = int(os.getenv("MAX_REDO")                  or "2")
    # Destructive action — human-gated by default (CIL open-question decision:
    # human-review-first in v1). Regressions surface via the outcomes endpoint;
    # an operator reverts manually until this flag is trusted per-channel.
    AUTO_REVERT_ON_REGRESSION = os.getenv("AUTO_REVERT_ON_REGRESSION", "false").lower() == "true"
    # If a measurement window has elapsed but reach-CSV coverage for the post
    # window still hasn't completed after this many extra days, give up and
    # classify neutral ("can't tell") rather than waiting forever.
    MEASUREMENT_COVERAGE_GRACE_DAYS = int(os.getenv("MEASUREMENT_COVERAGE_GRACE_DAYS") or "14")
    # Strategy stamp for Loop 3 attribution (seeded in the Loop 1 migration).
    STRATEGY_VERSION = os.getenv("STRATEGY_VERSION") or "2026.07-baseline-v1"

    # Content-aware audit (Block B)
    TRANSCRIPT_MAX_CHARS = int(os.getenv("TRANSCRIPT_MAX_CHARS") or "8000")
    KEYFRAME_MAX_FRAMES = int(os.getenv("KEYFRAME_MAX_FRAMES") or "4")
    KEYFRAMES_LOCAL_DIR = os.getenv("KEYFRAMES_LOCAL_DIR", "storage/keyframes")
    KEYFRAME_FFMPEG_TIMEOUT = int(os.getenv("KEYFRAME_FFMPEG_TIMEOUT") or "30")


settings = Settings()

# Allow OAuth over plain http://localhost during local dev.
if os.getenv("OAUTHLIB_INSECURE_TRANSPORT"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = os.environ["OAUTHLIB_INSECURE_TRANSPORT"]
