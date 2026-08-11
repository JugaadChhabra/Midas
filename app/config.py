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
    # Defaults to false: audits are APPLIED to YouTube live unless DRY_RUN=true is
    # set explicitly in the env. Set DRY_RUN=true to preview without pushing.
    DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

    YT_DAILY_QUOTA = int(os.getenv("YT_DAILY_QUOTA") or "10000")
    YT_QUOTA_SAFETY_BUFFER = int(os.getenv("YT_QUOTA_SAFETY_BUFFER") or "300")
    AUTOPILOT_TICK_SECONDS = int(os.getenv("AUTOPILOT_TICK_SECONDS") or "120")
    # When true, the autopilot picks the next video to audit via the
    # next_audit_candidate() RPC (returns ONE row) instead of pulling the
    # channel's whole videos + audits lists into the app every tick — the
    # dominant Supabase egress source. Defaults OFF: ship the migration + code
    # inert, run the live parity test, then flip on. Auto-falls back to the
    # in-app picker if the RPC errors (e.g. an unmigrated env).
    AUTOPILOT_PICKER_USE_RPC = os.getenv("AUTOPILOT_PICKER_USE_RPC", "false").lower() == "true"
    # Minutes after which a 'repeated_failures' autopilot pause auto-clears so the
    # channel is retried (it re-pauses if it fails 3 more times). Only this
    # transient reason expires — token_expired / unsafe_model stay latched until a
    # human reconnects / fixes config. Set to 0 to disable auto-unpause entirely.
    AUTOPILOT_PAUSE_COOLDOWN_MINUTES = int(os.getenv("AUTOPILOT_PAUSE_COOLDOWN_MINUTES") or "60")

    # Shorts job queue: how many cutter jobs run concurrently, and how often
    # the dispatcher polls for CREATED jobs / reaps finished workers. Cap 1
    # reproduces the old single-job behavior.
    SHORTS_MAX_CONCURRENT_JOBS = int(os.getenv("SHORTS_MAX_CONCURRENT_JOBS") or "2")
    SHORTS_DISPATCH_INTERVAL_SECONDS = int(os.getenv("SHORTS_DISPATCH_INTERVAL_SECONDS") or "5")

    # Retired flow: cutting shorts from a downloaded YouTube URL (yt-dlp + bgutil
    # PO tokens). Off by default — shorts now come from the NAS source only. The
    # download code (app/shorts/cutter/download.py) is retained but gated by this
    # flag; the image no longer ships yt-dlp/Deno/bgutil. To revive: set this
    # true AND restore those deps in requirements*.txt / Dockerfile + rebuild.
    SHORTS_YT_DOWNLOAD_ENABLED = (os.getenv("SHORTS_YT_DOWNLOAD_ENABLED", "false").lower() == "true")

    # Upper bound (seconds) on a source video's length for autopilot shorts.
    # Videos at/above this are never auto-cut. Kept just above the individual
    # rhyme uploads (~3–4 min) and below the long compilations, which are just
    # those same rhymes concatenated — auto-cutting them would re-produce clips
    # already made from the standalone videos. Configurable; set to 0 to disable
    # the length cap entirely (only videos with a known, non-NULL duration are
    # ever eligible regardless). Default 300 (5 min).
    SHORTS_MAX_SOURCE_SECONDS = int(os.getenv("SHORTS_MAX_SOURCE_SECONDS") or "300")

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
    # When true, join_pass/reconcile score videos against playlist centroids via
    # the Postgres playlist_video_sims() RPC (returns floats) instead of pulling
    # every pooled embedding — a vector(3072), ~39 KB/row — into the app. The
    # daily reconcile's embedding egress is the biggest recurring Supabase egress
    # source. Defaults OFF: ship the migration + code inert, run the live parity
    # test (tests/test_playlist_sims_parity_live.py) to confirm the RPC matches
    # the in-app centroid math, THEN flip this on. Falls back to the in-app path
    # automatically if the RPC errors (e.g. an unmigrated env), like DASHBOARD_USE_RPC.
    PLAYLIST_SIMS_USE_RPC = os.getenv("PLAYLIST_SIMS_USE_RPC", "false").lower() == "true"
    # Same idea for the WEEKLY discovery pass (Tier 3′ RPC 2): cluster orphan
    # videos via the Postgres discover_orphan_clusters() RPC (returns labels)
    # instead of pulling every orphan's pooled embedding into the app. Independent
    # flag so it can be validated + enabled separately from PLAYLIST_SIMS_USE_RPC.
    # Defaults OFF; falls back to the in-app greedy clustering if the RPC errors.
    PLAYLIST_DISCOVERY_USE_RPC = os.getenv("PLAYLIST_DISCOVERY_USE_RPC", "false").lower() == "true"
    # Daily playlist reconcile (_daily_reconcile → sync_playlists + reconcile_channel)
    # walks every playlist's FULL membership per channel via playlistItems.list — the
    # dominant YouTube Data API quota cost (~8k units/day fleet-wide, enough to exhaust
    # the 10k/day cap on its own). Restrict it to channels actively using playlist build.
    # Comma-separated channel-id allowlist; "*" runs it for all channels (legacy). The
    # manual reconcile endpoint is unaffected. Default: the four language channels.
    _PLAYLIST_RECONCILE_DEFAULT = (
        "UCr5-YUqBiW7PUmeAtxUWuRg,"  # Marathi
        "UC8KjoL0Z9mTHKqB6gFutkJw,"  # Punjabi
        "UCOVKJdzghm2gOnuaGeJTonA,"  # Gujarati
        "UCc4Tv_DEGDEKrKAt-vyVNmw"   # Haryanvi
    )
    _pr_raw = os.getenv("PLAYLIST_RECONCILE_CHANNELS", _PLAYLIST_RECONCILE_DEFAULT).strip()
    PLAYLIST_RECONCILE_ALL = _pr_raw == "*"
    PLAYLIST_RECONCILE_CHANNELS = set() if PLAYLIST_RECONCILE_ALL else {
        c.strip() for c in _pr_raw.split(",") if c.strip()
    }

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
    # When true, /dashboard computes per-channel aggregates via the Postgres
    # dashboard_summary() RPC (a few KB) instead of pulling the whole videos +
    # audits + shorts_clips tables into the app and counting in Python (~2 MB
    # egress/call). The in-app path (_aggregate_legacy) stays as the fallback and
    # correctness oracle; flip this off to revert instantly. Falls back to the
    # in-app path automatically if the RPC errors (e.g. an unmigrated env).
    DASHBOARD_USE_RPC = os.getenv("DASHBOARD_USE_RPC", "true").lower() == "true"
    # If a measurement window has elapsed but reach-CSV coverage for the post
    # window still hasn't completed after this many extra days, give up and
    # classify neutral ("can't tell") rather than waiting forever.
    MEASUREMENT_COVERAGE_GRACE_DAYS = int(os.getenv("MEASUREMENT_COVERAGE_GRACE_DAYS") or "14")
    # reporting_poll ingests daily reach CSVs into video_reach_daily and backfills
    # video_metrics.impressions/ctr. BOTH are consumed only by app/measurement.py,
    # which only runs on measurement_enabled channels. Ingesting reach for the
    # other channels was pure write-only waste — video_reach_daily's runaway
    # growth (~35k rows/day) and the main free-tier DB-size pressure. When true
    # (default) reporting_poll skips channels that aren't measurement_enabled.
    # Flip off to restore reach ingestion for every analytics_authorized channel.
    # NOTE: enabling measurement on a fresh channel means its reach starts
    # accruing that day — allow ~1 pre-change window (MEASUREMENT_WINDOW_DAYS) of
    # warmup before its first measurements are reliable.
    REPORTING_MEASURED_CHANNELS_ONLY = os.getenv("REPORTING_MEASURED_CHANNELS_ONLY", "true").lower() == "true"
    # Tier 2 (Supabase free-tier): the daily metrics_poll used to pull an Analytics
    # report for EVERY public video (~39k/day → one units=0 quota_log row + one
    # video_metrics upsert each, and reporting_poll then backfilled every row).
    # Nothing consumes those weekly sensor rows yet — Loop 1 measures off
    # video_reach_daily. When true (default) the sensor polls ONLY videos under an
    # active measurement window (audits.measurement_status in awaiting_window/
    # measuring), collapsing the daily set ~87×. Set false to restore the wide net
    # without a deploy (e.g. if a future loop wants longitudinal watch-time history).
    METRICS_POLL_MEASURED_ONLY = os.getenv("METRICS_POLL_MEASURED_ONLY", "true").lower() == "true"
    # Strategy stamp for Loop 3 attribution (seeded in the Loop 1 migration).
    STRATEGY_VERSION = os.getenv("STRATEGY_VERSION") or "2026.07-baseline-v1"

    # Content-aware audit (Block B)
    TRANSCRIPT_MAX_CHARS = int(os.getenv("TRANSCRIPT_MAX_CHARS") or "8000")
    KEYFRAME_MAX_FRAMES = int(os.getenv("KEYFRAME_MAX_FRAMES") or "4")
    KEYFRAMES_LOCAL_DIR = os.getenv("KEYFRAMES_LOCAL_DIR", "storage/keyframes")
    KEYFRAME_FFMPEG_TIMEOUT = int(os.getenv("KEYFRAME_FFMPEG_TIMEOUT") or "30")

    # --- NAS (shorts cutter source) ---
    # SMB share holding rhyme source videos, organized as
    # <NAS_SOURCE_ROOT_PATH>/<LANGUAGE>/<file>.mp4. Cut clips + the moved
    # source land under <NAS_DESTINATION_ROOT_PATH>/<LANGUAGE>/. "local" mode
    # (a plain filesystem root) exists for tests and dev without a NAS.
    NAS_MODE            = os.getenv("NAS_MODE", "smb").lower()
    NAS_SERVER          = os.getenv("NAS_SERVER", "")
    NAS_SHARE           = os.getenv("NAS_SHARE", "")
    NAS_USERNAME        = os.getenv("NAS_USERNAME", "")
    NAS_PASSWORD        = os.getenv("NAS_PASSWORD", "")
    NAS_DOMAIN          = os.getenv("NAS_DOMAIN", "")
    NAS_PORT            = int(os.getenv("NAS_PORT") or "445")
    # SMB auth mechanism. Default "ntlm" because the standalone NAS (raw IP, local
    # user, no domain/KDC) can't do Kerberos: the default "negotiate" path tries
    # Kerberos first — since the image ships gssapi — and dies with "Unable to
    # negotiate common mechanism" instead of falling back to NTLM. Set "negotiate"
    # or "kerberos" only for an AD-joined share.
    NAS_AUTH_PROTOCOL   = os.getenv("NAS_AUTH_PROTOCOL", "ntlm").lower()
    NAS_SOURCE_ROOT_PATH      = os.getenv("NAS_SOURCE_ROOT_PATH", "Animations/SHORTS CUTTER/RHYMES")
    NAS_DESTINATION_ROOT_PATH = os.getenv("NAS_DESTINATION_ROOT_PATH", "Animations/SHORTS CUTTER/COMPLETED")
    # local-mode root (mode="local"): a directory that stands in for the share.
    NAS_LOCAL_ROOT      = os.getenv("NAS_LOCAL_ROOT", "./nas_data")

    # ── Self-hosted Postgres + nightly NAS snapshot (app/backup.py) ────────
    # DATABASE_URL is the direct libpq connection used by pg_dump and by
    # scripts/apply_migrations.py. It is NOT how the app reads data — that
    # still goes through PostgREST via SUPABASE_URL, so no call site changed.
    DATABASE_URL        = os.getenv("DATABASE_URL", "")
    BACKUP_ENABLED      = os.getenv("BACKUP_ENABLED", "true").lower() == "true"
    # Local hour for the nightly dump. Late enough that the day's work is done,
    # early enough to be well clear of the 02:00 daily reconcile.
    BACKUP_HOUR         = int(os.getenv("BACKUP_HOUR") or "0")
    BACKUP_WORK_DIR     = os.getenv("BACKUP_WORK_DIR", "./backups")
    # 1 = a single snapshot replaced nightly (max one day of data loss, but a
    # corrupt DB overwrites the last healthy copy). 2 = alternate between two
    # slots by day-of-year, which costs one extra file and survives that case.
    BACKUP_SLOTS        = int(os.getenv("BACKUP_SLOTS") or "1")


settings = Settings()

# Allow OAuth over plain http://localhost during local dev.
if os.getenv("OAUTHLIB_INSECURE_TRANSPORT"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = os.environ["OAUTHLIB_INSECURE_TRANSPORT"]
