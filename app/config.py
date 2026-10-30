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
    # Freezes the weekly reflection job, its manual trigger and prompt
    # promotion (Phase A · A4). Live prompts keep running unchanged.
    REFLECTION_ENABLED = os.getenv("REFLECTION_ENABLED", "false").lower() == "true"

    # Tracing. Defaults to OFF so merging the instrumentation changes nothing
    # until an environment opts in. OTEL_ENDPOINT is the Phoenix collector's
    # OTLP/HTTP traces path; inside docker-compose that host is the service name.
    OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"
    OTEL_ENDPOINT = os.getenv("OTEL_ENDPOINT", "http://phoenix:6006/v1/traces")
    OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "midas")

    SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
    # Defaults to false: audits are APPLIED to YouTube live unless DRY_RUN=true is
    # set explicitly in the env. Set DRY_RUN=true to preview without pushing.
    DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

    YT_DAILY_QUOTA = int(os.getenv("YT_DAILY_QUOTA") or "10000")
    YT_QUOTA_SAFETY_BUFFER = int(os.getenv("YT_QUOTA_SAFETY_BUFFER") or "300")
    # Units withheld from BULK COLLECTION so applying audits can never be
    # starved by it. Collection passes this to quota.units_remaining(); the
    # apply path does not, so it can spend into the reserve. Sized for ~29
    # applies/day at APPLY_COST=51 — comfortably above the fleet's observed
    # 12-22/day. Only jobs that opt in (JobBudget) respect it.
    YT_QUOTA_APPLY_RESERVE = int(os.getenv("YT_QUOTA_APPLY_RESERVE") or "1500")
    # The mirror image (fleet readiness, 2026-10-25): autopilot applies, title or
    # backlinks, stop this many units short of the ceiling so the day's
    # collection (playlist_reconcile, video_sync, metrics_poll, which run late in
    # YouTube's Pacific quota day) is never starved by applies spent earlier.
    # 10,000 - 300 - 3,000 leaves ≈ 6,700u ≈ 130 applies at 51u, fleet-wide.
    YT_QUOTA_COLLECTION_RESERVE = int(os.getenv("YT_QUOTA_COLLECTION_RESERVE") or "3000")
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

    # Freeze switches for the writers whose changes nobody measures (Phase A ·
    # A4). Off means the job is not registered at startup; reconcile is the
    # exception — it still registers so sync_playlists runs, and only its
    # add/remove step is skipped, and POST .../playlists/reconcile returns 409.
    PLAYLIST_DISCOVERY_ENABLED = os.getenv("PLAYLIST_DISCOVERY_ENABLED", "false").lower() == "true"
    PLAYLIST_RECONCILE_WRITES_ENABLED = os.getenv("PLAYLIST_RECONCILE_WRITES_ENABLED", "false").lower() == "true"
    PLAYLIST_TUNING_ENABLED = os.getenv("PLAYLIST_TUNING_ENABLED", "false").lower() == "true"

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
    # Ceiling on what ONE nightly reconcile pass may spend walking playlist
    # membership, shared across every channel in the pass (not per channel).
    # The allowlist and the item_count skip above both cut the *expected* cost;
    # this bounds the WORST case, which neither of them can — a day when many
    # playlists legitimately changed, or the first pass after a long outage,
    # still walks everything it is asked to. Work that does not fit is deferred,
    # not dropped: playlists.membership_walked_at orders the next pass so it
    # resumes where this one stopped. 0 disables the walk entirely.
    PLAYLIST_SYNC_QUOTA_BUDGET = int(os.getenv("PLAYLIST_SYNC_QUOTA_BUDGET") or "2000")
    # Force-walk a playlist that has not been walked in this many days, whatever
    # its itemCount says. The skip is blind to an equal-count swap (one video
    # added + one removed => identical count, drifted membership); rotation
    # bounds how long that drift can hide. 0 disables rotation.
    PLAYLIST_FULL_WALK_DAYS = int(os.getenv("PLAYLIST_FULL_WALK_DAYS") or "30")

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
    # Reach CSVs for a data-day arrive 1-6 days late (2026-07-02 probe), so a
    # frontier a few days behind is the pipeline working. Past this, ingestion has
    # stopped and measurement is judging nothing — reach.is_stale says so, and the
    # measurement pass reports it per channel rather than waiting for someone to
    # notice a flat outcomes page. NOT a grace period: the grace runs in ingested
    # time now, so a stalled channel holds rather than expiring (see
    # plan_measurement).
    REACH_STALE_AFTER_DAYS = int(os.getenv("REACH_STALE_AFTER_DAYS") or "7")
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
    # Phase B · B1 (spec Part 2 §8): channels whose channel_traffic_source_a3 and
    # playlist_traffic_source_a2 reports traffic_poll ingests. Comma-separated
    # channel ids. Default: the rollout channel, Marathi. Widening is a config change.
    TRAFFIC_INGEST_CHANNELS = {
        c.strip()
        for c in (os.getenv("TRAFFIC_INGEST_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",")
        if c.strip()
    }
    # Phase B · B2 (spec Part 2 §1.3, §8): the share of each lever's triaged
    # videos held out as the control arm (recorded, never applied). Per lever, by
    # a stable hash of (video_id, lever): app/interventions.assign_arm.
    HOLDOUT_PCT = float(os.getenv("HOLDOUT_PCT") or "0.20")
    # Phase B · B4 (spec Part 2 §2.1, §8): the warm filter, app/warm.py. A video
    # is warm with >= WARM_MIN_IMPRESSIONS over the channel's latest
    # WARM_WINDOW_DAYS ingested reach data-days (not calendar days);
    # WARM_EXPLORE_PCT of picks come from the rest of the pool, not the top.
    WARM_MIN_IMPRESSIONS = int(os.getenv("WARM_MIN_IMPRESSIONS") or "500")
    WARM_WINDOW_DAYS     = int(os.getenv("WARM_WINDOW_DAYS")     or "28")
    WARM_EXPLORE_PCT     = float(os.getenv("WARM_EXPLORE_PCT")   or "0.10")
    # When true, app/warm.py ranks the pool in Postgres via the warm_pool() RPC
    # instead of reading videos + 28 days of video_reach_daily into the app. The
    # in-app path stays as the fallback and parity oracle (as for
    # AUTOPILOT_PICKER_USE_RPC); tests/test_warm_pool_parity_live.py is the gate
    # for flipping it on.
    WARM_POOL_USE_RPC = os.getenv("WARM_POOL_USE_RPC", "false").lower() == "true"
    # Phase B · B5 (spec Part 2 §8, Part 3 B5): the backend app/decide.py asks
    # in shadow next to the rules: `llm` (openrouter.chat_json) or `jev` (a stub
    # that raises NotConfigured until access exists). Its answer is logged to
    # decision_log, never used.
    DECIDE_BACKEND = os.getenv("DECIDE_BACKEND") or "llm"
    # Spec Part 2 §2.2, §8: below this many backlink candidates, the triage
    # rules say `no_change` (app/decide.py TRIAGE).
    BACKLINK_MIN_CANDIDATES = int(os.getenv("BACKLINK_MIN_CANDIDATES") or "2")
    # Slice 1 · S1.2 (spec Part 4 Config, Part 2 §8): the most targets one
    # canonical backlink block links to (app/backlinks.py render refuses more).
    # Start conservative: spam/ToS risk.
    BACKLINK_MAX = int(os.getenv("BACKLINK_MAX") or "3")
    # Slice 1 · S1.1 (spec Part 4 Config, Part 2 §2.3, §8): a sibling channel
    # sent the channel's videos at least this many suggested (type 7) views over
    # its trailing 28 ingested traffic data-days (app/backlinks.py siblings).
    # Inbound only, read from the channel's own report (Part 4 finding 1).
    SIBLING_MIN_VIEWS = int(os.getenv("SIBLING_MIN_VIEWS") or "100")
    # Slice 1 · S1.4a (spec Part 4 Config, finding 2; Part 2 §2.1, §8): the warm
    # pool skips a video with any Midas intervention created this many days ago
    # or fewer, whatever its status, so a `no_change` (declined, not active)
    # isn't offered again on the next tick (app/warm.py, warm_pool()).
    TRIAGE_COOLDOWN_DAYS = int(os.getenv("TRIAGE_COOLDOWN_DAYS") or "7")
    # Slice 1 · S1.3 (spec Part 4 Config): the kill switch for backlink writes to
    # YouTube. While false, app/backlinks_apply.py's apply and revert refuse
    # (`apply_disabled`) and send nothing. DRY_RUN is honoured on top of it.
    BACKLINK_APPLY_ENABLED = os.getenv("BACKLINK_APPLY_ENABLED", "false").lower() == "true"
    # Slice 3 · S3.1 (spec Part 6 Config, F1): the kill switch for title writes
    # to YouTube. While false, app/titles_apply.py's apply and revert refuse
    # (`apply_disabled`) and send nothing. DRY_RUN is honoured on top of it.
    TITLE_APPLY_ENABLED = os.getenv("TITLE_APPLY_ENABLED", "false").lower() == "true"
    # Slice 3 · S3.2 (spec Part 6 Config, F9): the model the title writer asks
    # (app/titles.py write_candidates), and the candidates per call. The
    # writer starts as AUDIT_MODEL and is set from the offline bake-off
    # (scripts/title_bakeoff.py).
    WRITER_MODEL = os.getenv("WRITER_MODEL") or AUDIT_MODEL
    TITLE_CANDIDATES = int(os.getenv("TITLE_CANDIDATES") or "3")
    # Slice 3 (spec Part 6 Config, F2): warm-window impressions above which a
    # video is never retitled, on top of the channel's top 1% (the ceiling,
    # app/titles.py channel_context). Read by triage since S3.3.
    TITLE_MAX_IMPRESSIONS = int(os.getenv("TITLE_MAX_IMPRESSIONS") or "5000000")
    # Slice 3 (spec Part 6 Config, F5): the share of treated title videos the
    # agent writes, by hash (app/titles.py title_path); 0 = pipeline only.
    TITLE_AGENT_PCT = float(os.getenv("TITLE_AGENT_PCT") or "0.5")
    # Slice 3 · S3.3 (spec Part 6 Config, F3): the channels where triage may
    # answer `title` (app/agent_tick.py titles_open). Comma list.
    TITLE_CHANNELS = {
        c.strip()
        for c in (os.getenv("TITLE_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",")
        if c.strip()
    }
    # Slice 3 · S3.3 (spec Part 6 Config, F4, F14): treated title rows per
    # channel per day (inside `autopilot_daily_cap`), and agent runs per channel
    # per day, declines included (app/agent_tick.py _title_enabled).
    TITLE_DAILY_CAP = int(os.getenv("TITLE_DAILY_CAP") or "10")
    TITLE_AGENT_DAILY_RUNS = int(os.getenv("TITLE_AGENT_DAILY_RUNS") or "20")
    # Slice 3 · S3.3 (spec Part 6 Config, F12): video ids the SEO team protects;
    # triage never answers `title` for them. Comma list, empty by default.
    TITLE_EXCLUDE_VIDEOS = {
        v.strip() for v in (os.getenv("TITLE_EXCLUDE_VIDEOS") or "").split(",") if v.strip()
    }
    # Slice 3 · S3.4 (spec Part 6 Config, Part 2 §3.1, §8): the most model
    # turns (chat_tools calls) an agent run gets before it ends `failed`,
    # `turn_cap` (app/agent/loop.py run_title_agent).
    AGENT_MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS") or "12")
    # Slice 3 · S3.5 (spec Part 6 Config, F6): a title row's post window in
    # traffic data-days (the pre is 14), and the floor on its browse +
    # suggested views in the pre window, else `insufficient_data`
    # (app/title_measurement.py).
    TITLE_WINDOW_DAYS = int(os.getenv("TITLE_WINDOW_DAYS") or "14")
    TITLE_MIN_PRE_VIEWS = int(os.getenv("TITLE_MIN_PRE_VIEWS") or "100")
    # Slice 3 · S3.5 (spec Part 6 Config, F7): the log-ratio verdict band and
    # stop bar per path, the windows before the stop rule, and the harm guard:
    # a cumulative lift ≤ −TITLE_HARM_LIFT after TITLE_HARM_WINDOWS stops a
    # path early (app/lever_verdicts.py).
    TITLE_MIN_LIFT = float(os.getenv("TITLE_MIN_LIFT") or "0.05")
    TITLE_EXPERIMENT_WINDOWS = int(os.getenv("TITLE_EXPERIMENT_WINDOWS") or "4")
    TITLE_HARM_WINDOWS = int(os.getenv("TITLE_HARM_WINDOWS") or "2")
    TITLE_HARM_LIFT = float(os.getenv("TITLE_HARM_LIFT") or "0.10")
    # Slice 3 · S3.5 (spec Part 6 Config, F8): a judged title whose delta minus
    # the holdout mean is ≤ −TITLE_REVERT_LIFT is put back, at most
    # TITLE_REVERTS_PER_DAY per channel per run (app/lever_verdicts.py auto_revert).
    TITLE_REVERT_LIFT = float(os.getenv("TITLE_REVERT_LIFT") or "0.30")
    TITLE_REVERTS_PER_DAY = int(os.getenv("TITLE_REVERTS_PER_DAY") or "10")
    # Slice 1 · S1.6 (spec Part 4 Config, Part 2 §1.7): the floor on the SOURCE
    # video's total views in a backlinks intervention's post window. Under it
    # the window is extended once to 14 days, then `insufficient_data`
    # (app/lever_measurement.py). Nobody clicks a link on a video nobody watched.
    LEVER_MIN_SOURCE_VIEWS = int(os.getenv("LEVER_MIN_SOURCE_VIEWS") or "100")
    # Slice 1 · S1.6b (spec Part 4 Config, P1): the P1 time box. Once this many
    # weekly treated-vs-holdout verdicts are written for a channel and the
    # cumulative lift is under BACKLINK_MIN_LIFT, the backlinks lever stops there
    # (app/lever_verdicts.py; triage reads it, app/agent_tick.backlinks_stopped).
    BACKLINK_EXPERIMENT_WINDOWS = int(os.getenv("BACKLINK_EXPERIMENT_WINDOWS") or "3")
    # Slice 1 · S1.6b (spec Part 4 Config, D6): attributable views per treated
    # video per week that the treated arm must beat holdout by. Both the weekly
    # verdict's band (helped / no_change / worse) and the stop rule's bar.
    BACKLINK_MIN_LIFT = float(os.getenv("BACKLINK_MIN_LIFT") or "1.0")
    # Slice 2 · S2.1 (spec Part 5 Config, E4): the share of a channel's eligible
    # playlists held out of the playlist test (measured, never dosed). Per
    # playlist, by a stable hash of its id: app/playlist_test.assign_arm.
    PLAYLIST_HOLDOUT_PCT = float(os.getenv("PLAYLIST_HOLDOUT_PCT") or "0.5")
    # Slice 2 · S2.1 (spec Part 5 Config, E5): the most videos one treated
    # playlist is proposed in the test's one dose (app/playlist_test.candidates).
    PLAYLIST_TEST_MAX_ADDS = int(os.getenv("PLAYLIST_TEST_MAX_ADDS") or "5")
    # Slice 2 · S2.2 (spec Part 5 Config): the kill switch for the playlist
    # test's YouTube writes. While false the daily playlist_test_apply job does
    # nothing (app/playlist_test.run_apply); approval only queues the adds.
    PLAYLIST_APPLY_ENABLED = os.getenv("PLAYLIST_APPLY_ENABLED", "false").lower() == "true"
    # Slice 2 · S2.2 (spec Part 5 Config, E5): what one playlist_test_apply run
    # may spend (quota.JobBudget), on top of the YT_QUOTA_COLLECTION_RESERVE gate.
    PLAYLIST_TEST_DAILY_UNITS = int(os.getenv("PLAYLIST_TEST_DAILY_UNITS") or "2000")
    # Slice 2 · S2.2 (spec Part 5 Config): the runs a failing test add is tried
    # in before it counts as failed for good.
    PLAYLIST_TEST_MAX_ATTEMPTS = int(os.getenv("PLAYLIST_TEST_MAX_ATTEMPTS") or "3")
    # Slice 2 · S2.3 (spec Part 5 Config, E8): the playlist test's weekly post
    # windows before its answer (app/playlist_test.measure_channel).
    PLAYLIST_EXPERIMENT_WINDOWS = int(os.getenv("PLAYLIST_EXPERIMENT_WINDOWS") or "4")
    # Slice 2 · S2.3 (spec Part 5 Config, E8): playlist starts per playlist per
    # week. The weekly verdict band (±it), and the cumulative lift the test must
    # reach at PLAYLIST_EXPERIMENT_WINDOWS for "yes" (lever_verdicts.directional).
    PLAYLIST_MIN_LIFT = float(os.getenv("PLAYLIST_MIN_LIFT") or "1.0")
    # Slice 2 · S2.4 (spec Part 5 Config, E13): channels whose Shorts get link
    # recommendations (app/short_links.py), comma-separated ids as
    # TRAFFIC_INGEST_CHANNELS; the job runs only those also in it. Default:
    # Marathi. Widening is a setting, once a channel's Shorts are synced and embedded.
    SHORT_LINK_CHANNELS = {
        c.strip()
        for c in (os.getenv("SHORT_LINK_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",")
        if c.strip()
    }
    # Slice 2 · S2.4 (spec Part 5 Config, E10): the most targets recommended per Short.
    SHORT_LINK_TARGETS = int(os.getenv("SHORT_LINK_TARGETS") or "3")
    # Slice 2 · S2.4 (spec Part 5 Config, E9): a Short is listed with at least
    # this many Shorts-feed (type 24) views over its channel's latest 28
    # ingested traffic data-days.
    SHORT_LINK_MIN_FEED_VIEWS = int(os.getenv("SHORT_LINK_MIN_FEED_VIEWS") or "1")
    # Slice 2 · S2.4 (spec Part 5 Config): Shorts recommended per weekly run,
    # which bounds its shadow next-watch calls at SHORT_LINK_TARGETS × this.
    SHORT_LINK_MAX_PER_RUN = int(os.getenv("SHORT_LINK_MAX_PER_RUN") or "50")
    # Slice 2 · S2.6 (spec Part 5 Config): a (Short, target) pair counts as set
    # once it has this many type-32 views over the target channel's latest 28
    # ingested traffic data-days (app/short_links.py `seen_pairs`).
    SHORT_LINK_SEEN_MIN_VIEWS = int(os.getenv("SHORT_LINK_SEEN_MIN_VIEWS") or "1")
    # Tier 2 (Supabase free-tier): the daily metrics_poll used to pull an Analytics
    # report for EVERY public video (~39k/day → one units=0 quota_log row + one
    # video_metrics upsert each, and reporting_poll then backfilled every row).
    # Nothing consumes those weekly sensor rows yet — Loop 1 measures off
    # video_reach_daily. When true (default) the sensor polls ONLY videos under an
    # active measurement window (audits.measurement_status in awaiting_window/
    # measuring), collapsing the daily set ~87×. Set false to restore the wide net
    # without a deploy (e.g. if a future loop wants longitudinal watch-time history).
    METRICS_POLL_MEASURED_ONLY = os.getenv("METRICS_POLL_MEASURED_ONLY", "true").lower() == "true"
    # Human-readable prefix of the strategy stamp for Loop 3 attribution. The
    # stamp itself is derived per audit, `<STRATEGY_LABEL>-<short hash>` over the
    # prompt source, AUDIT_MODEL and the decision question-set version
    # (audits.strategy_version), so a model swap in .env shows up in the stamp.
    # The Loop 1 migration's `2026.07-baseline-v1` seed row stays for history.
    STRATEGY_LABEL = os.getenv("STRATEGY_LABEL") or "2026.07-baseline"

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
    # pg_dump refuses to dump a server newer than itself. The container image
    # installs postgresql-client-16, so the default is right there; on a dev
    # machine whose `pg_dump` is older than the server, point this at a newer
    # one (macOS/Homebrew: /opt/homebrew/opt/libpq/bin/pg_dump).
    BACKUP_PG_DUMP      = os.getenv("BACKUP_PG_DUMP", "pg_dump")
    # First boot on a new machine: ./pgdata starts empty, so the app restores
    # last night's NAS snapshot into it before serving anything (app/provision.py).
    # Turning this off means a fresh machine comes up with an empty catalogue.
    RESTORE_ON_EMPTY    = os.getenv("RESTORE_ON_EMPTY", "true").lower() == "true"
    # Same version story as BACKUP_PG_DUMP, one direction earlier: psql replays
    # the dump. Older psql chokes on newer dump syntax.
    RESTORE_PSQL        = os.getenv("RESTORE_PSQL", "psql")


settings = Settings()

# Allow OAuth over plain http://localhost during local dev.
if os.getenv("OAUTHLIB_INSECURE_TRANSPORT"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = os.environ["OAUTHLIB_INSECURE_TRANSPORT"]
