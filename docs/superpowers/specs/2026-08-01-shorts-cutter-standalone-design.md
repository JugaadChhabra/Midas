# Shorts Cutter — Standalone Paid Product (Design)

**Date:** 2026-08-01
**Status:** Approved direction, pre-implementation
**Supersedes intake model of:** `2026-07-12-shorts-cutter-saas-design.md` (which predates the NAS work and left intake open). This spec locks the stack, pricing research, and extraction mechanic.

## The product in one line

Paste a YouTube URL → get back ready-to-post vertical shorts. Pay with credits. No YouTube account, no write-back, no NAS.

We ship **only** the Shorts Cutter as its own web product in a fresh repo. The rest of Midas (auditor, autopilot, playlists) stays behind. Dropping YouTube upload removes the Google OAuth verification blocker entirely.

## Why a new repo (and not a refactor)

The cutter engine (`app/shorts/cutter/*`) is a **true leaf**: every internal import stays within `app.shorts.cutter.*`. Verified — its only reach outside itself is one `os.getenv("BGUTIL_POT_HTTP_BASE_URL")` in `download.py`. Everything Midas-specific around it (routes, runner, dispatcher, NAS, YouTube upload, dashboard) is shell we discard. A fresh repo gives independent deploy, own domain, own billing, and — critically — a web service that carries **none** of the ML weight.

## Architecture — a hard structural seam

Three layers that cannot cross-contaminate. This is the answer to "don't ship unneeded modules": the always-on web service imports neither the engine nor any ML dependency.

```
shorts-cutter/                    ← fresh repo
  engine/          lifted from app/shorts/cutter/*  (unchanged, tests come with it)
                     - pure pipeline: cut_video(local_path) → clips
                     - download.py: fetch_video / is_youtube_url / refresh_pot_provider
  worker/
    modal_app.py   Modal app: GPU fn = download → engine.cut_video() → upload clips to R2
  api/             FastAPI control plane (always-on, CPU, NO ML deps)
    main.py
    auth.py        Supabase Auth session verification (Google login)
    jobs.py        POST /jobs (validate→price→reserve→spawn Modal), GET /jobs/{id}
    youtube.py     duration probe via YouTube Data API (API key only, no OAuth)
    credits.py     ledger: balance / reserve / settle / refund
    billing.py     Dodo checkout link + webhook → credit top-up
    db.py          Supabase/Postgres client
  web/             Next.js: landing page + app (paste URL → progress → download → buy credits)
  migrations/      SQL: users, jobs, credit_ledger
```

**Import rule (enforced structurally):** `engine` imports nothing from `api`/`worker`. `worker` imports `engine`. `api` imports **neither** `engine` nor any ML library. The web service is a few MB of `fastapi`/`supabase`/`httpx`; the multi-GB ML stack exists only inside the Modal worker and only runs during a job.

## The stack (locked, with 2026 pricing research)

| Concern | Choice | Why it won |
|---|---|---|
| GPU compute | **Modal** | Real L4 @ $0.80/hr, true scale-to-zero (~$0.02/job), $30/mo free credits, and hosts the warm CPU control plane on the same platform. Cold-start unpublished → **validate empirically in Slice 0**. RunPod (sub-200ms cold start) is the fallback if cold start proves unacceptable. |
| Auth + DB | **Supabase** | One platform: Google login (non-sensitive scopes, no verification) + Postgres. Start on **free** for dev; **must go Pro ($25/mo) before ship** — free projects pause after ~1 week idle. New project, separate from Midas. |
| Media storage | **Cloudflare R2** | Genuinely **$0 egress, uncapped**; no min storage duration; S3-compatible presigned downloads; 10 GB free. We serve user-downloadable clips, so egress is the cost driver. |
| Payments | **Dodo Payments** | India-founded MoR → native INR settlement + GST + sub-day KYC. Lowest rate (4% + 40¢ vs 5% + 50¢). First-class credit-pack + usage billing with purchase webhooks. No monthly fee. |
| Frontend | **Vercel (Next.js)** | Zero-friction Next.js (landing + app). Non-commercial free tier → **Pro $20/mo** once charging. Cloudflare Pages/Workers ($0 egress, $5/mo, needs adapter) is the cost-optimized fallback. |

**Cost shape:** fixed floor ~$45/mo once fully commercial (Supabase Pro $25 + Vercel Pro $20; Modal/R2/Dodo have no floor). Variable ~$0.02–0.05/job. At ~$0.10/min pricing a 4-min job nets ~$0.37 — near-zero fixed floor means profitability almost immediately.

**With YouTube-URL-only intake, R2 is output-only** — the worker pulls the source straight from YouTube, so there is no file-upload path and no source storage in v1.

## Extraction mechanic — history-preserving

**Move (and nothing else):**

| Carry over | Leave in Midas |
|---|---|
| `app/shorts/cutter/*` (13 files) → `engine/` | `runner.py`, `routes.py`, `dispatcher.py` |
| `tests/shorts/cutter/*` (18 test files) → `tests/` | `nas_source.py`, `nas_service.py`, `worker.py`, `status.py` |
| `requirements-ml.txt` (the ML pins) | `youtube_upload.py` (dropped — no write-back) |
| `BGUTIL_POT_HTTP_BASE_URL` env | everything else in `app/` (auditor, autopilot, playlists) |

**Method — preserve history (chosen):** use `git filter-repo --path app/shorts/cutter --path tests/shorts/cutter` (or `git subtree split -P app/shorts/cutter`) to produce a tree containing only those paths **with full commit history and blame intact**, then pull it into the fresh repo. The proven engine keeps its provenance. Midas keeps its own copy — the two engines are allowed to diverge (extract to a shared pip package later only if lockstep is ever needed; YAGNI).

**One mechanical edit:** rewrite absolute imports `from app.shorts.cutter.X` → `from engine.X` (13 sites, single `sed`). The 18 copied tests immediately prove correctness.

## The one real gotcha — reviving YouTube download

The download code exists (`cutter/download.py`); the risk is the **worker image/runtime**, documented in Midas's own history. The Modal worker container must include:

- `yt-dlp==2026.6.9` — the verified-good pin (newer releases broke YouTube extraction).
- `bgutil-ytdlp-pot-provider==1.3.1` **+ the POT provider server, version-matched** — a skew makes the server mint tokens the plugin can't use.
- **A JS runtime (node/Deno)** in the image — without it, yt-dlp cannot solve YouTube's n-challenge and every video reports "not available".
- **Rotating residential proxies** — to run downloads on Modal's shared IPs without blocks. Validate URL + enforce length cap before spending compute; process-and-delete source (no retain/rehost).

This all runs inside the disposable Modal worker (ephemeral IPs, isolated from the app) — the right place for it.

## Job lifecycle (fail cheap before spending GPU)

Everything that can reject a job happens on the control plane **before** Modal is invoked.

```
1. User logs in (Supabase Auth, Google)
2. Pastes YouTube URL → POST /jobs
3. Control plane (NO GPU yet):
     a. validate URL
     b. probe duration via YouTube Data API   ← API key only, no OAuth, no download
     c. enforce length cap (≤ configurable max, e.g. 10 min)
     d. check balance ≥ duration-minutes; if short → 402, prompt to buy
     e. RESERVE credits (ledger hold), create job row (status=queued)
     f. modal_fn.spawn(job_id, youtube_url) → returns immediately
4. Modal GPU worker (only place ML runs):
     download (yt-dlp+POT+proxy) → engine.cut_video() → upload clips to R2
     → writes status/progress to Supabase (service role)
5. Frontend polls GET /jobs/{id} → progress → presigned R2 download links
6. Settle: on success → finalize credits to ACTUAL minutes;
           on failure (download OR engine) → FULL refund of the hold
```

## Data model & credits ledger

Three tables. The ledger is **append-only** — balance is always `SUM(delta_minutes)`; refunds are just another row, so a balance can never be corrupted.

```
users          mirrors Supabase auth; free-trial minutes granted on signup
jobs           id · user_id · youtube_url · duration_sec · status
               (queued→downloading→processing→done/failed) · clip_r2_keys[] · error
credit_ledger  id · user_id · delta_minutes · reason · job_id · created_at
               reason ∈ {trial_grant, purchase, job_reserve, job_settle, job_refund}
```

Per-job credit flow: `job_reserve` (−estimate) → on done `job_settle` (adjust to actual) → or on fail `job_refund` (+estimate, full). Dodo webhook adds `purchase` (+pack), **idempotent** (dedupe on Dodo event id) so a retried webhook never double-grants.

**Billing model (v1):** credit packs + free trial. Sign up → X free minutes → buy packs (e.g. 60/300/1000 min) when they run out. 1 credit = 1 source-minute (the real cost driver is minutes of source, not clip count). No subscriptions in v1.

## MVP slices (each a working vertical)

- **Slice 0 — Prove the engine.** Extract `engine/` (history-preserving), wrap `cut_video()` as a Modal GPU fn, YouTube URL → clips in R2, invoked from a script. **Benchmark Modal cold-start here** (the one open stack risk). No auth, no UI.
- **Slice 1 — Free usable tool.** Control plane + Supabase auth + jobs + minimal Next.js (paste URL → progress → download). No billing.
- **Slice 2 — Credits.** Trial grant + ledger + reserve/settle/refund + balance gate.
- **Slice 3 — Money.** Dodo checkout → webhook → credit top-ups. Now it's paid.
- **Slice 4 — Landing + launch.**

## Error handling & testing

- **Errors:** fail-fast validation pre-GPU; auto-refund on any worker failure; idempotent webhooks; Modal job timeout with reserve-once semantics (a retry never double-charges).
- **Testing:** engine keeps its existing 18 tests (copied, proven). New unit tests for ledger math (reserve/settle/refund), webhook idempotency, and duration→cost, mocking Modal/Supabase. One live end-to-end against a real short YouTube URL (marked `@live`, matching Midas's convention).

## Explicitly OUT of v1 (YAGNI)

File upload (URL-only), YouTube write-back/upload, NAS anything, subscriptions, team accounts, and the entire Midas auditor/autopilot/playlists surface.

## Locked v1 defaults

- **Length cap:** 10 min max source duration per job.
- **Free trial:** 15 free minutes granted on signup.
- **Frontend:** Vercel / Next.js (Cloudflare Pages is the cost-optimized fallback, not v1).
- **Modal cold-start:** committed to Modal; acceptability validated empirically in Slice 0, RunPod pre-vetted as the escape hatch.

## Open decisions (defer, don't block)

- Pricing tiers / credit-pack sizes ($ per minute) — research points to ~$0.08–0.15/min against ~$0.01–0.05/job cost. Set before Slice 3 (Money).
