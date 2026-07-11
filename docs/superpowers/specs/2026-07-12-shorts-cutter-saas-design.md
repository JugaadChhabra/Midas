# Shorts Cutter — Standalone SaaS

**Date:** 2026-07-12
**Status:** Approved direction, pre-implementation

## The product in one line

Give it a long video → get back ready-to-post vertical shorts. Upload a file or paste a YouTube link. Pay with credits. No YouTube account, no write-back.

We ship *only* the Shorts Cutter. The rest of Midas (auditor, autopilot, playlists) stays separate. Dropping YouTube upload removes the Google OAuth verification blocker entirely.

## Architecture

Thin always-on control plane + scale-to-zero serverless GPU worker.

```
Browser ──▶ Control plane (FastAPI + Postgres)          ~$7–20/mo
                │   auth · credits · job create/status · download links
                ├──▶ Cloudflare R2        uploads + output clips (zero egress)
                └──▶ Modal GPU function   wraps existing cut_video()
                        scale-to-zero · per-second billing · ~$0 idle
```

**Why:** the pipeline is heavy and bursty (demucs + faster-whisper + YOLO). Serverless GPU runs only during a job and bills per second — GPU speed with a near-zero idle bill. CPU-only would make a 3-min song take 5–15 min; not acceptable for a paid product. Always-on GPU only wins at steady high volume, which we don't have at launch.

**R2, not S3:** we serve video files back to users; R2 has no egress fees.

## Reuse vs build

| Reuse as-is | Build new (the shell) |
|---|---|
| `app/shorts/cutter/*` engine (already framework-free) | Landing / marketing page |
| Job + runner pattern | Auth — Supabase Auth (already in stack) |
| Supabase (auth + storage) | Credits ledger + billing webhooks |
| | Intake: file upload (presigned R2) + YouTube URL paste |
| | Job UX: submit → live progress → download clips |
| | Output to R2 + presigned download (today: local `shorts_cache/`) |
| | Thin Modal wrapper around `cut_video()` |

The ML engine is done. The work is standard SaaS plumbing around it. Not a rewrite.

## Billing — credits / pay-as-you-go

Compute costs real money per job, so revenue tracks usage.

**Unit economics:** a 3–5 min source ≈ 45–90s on an L4 GPU ≈ **~$0.03–0.05 all-in per job**. Price so one processed video costs the user ~$0.30–0.60 → 6–10× margin, room for free-trial credits.

**Gateway:** use a Merchant of Record (handles global VAT/sales tax, so no multi-jurisdiction registration). Primary: **Dodo Payments** (MoR, India-based → clean INR payouts) or **Polar** (best native credits/usage primitives + DX). Fallback: **Lemon Squeezy**. Not Stripe-direct — not an MoR, India export friction. The MoR choice is the real decision; all three qualify.

## Input handling (chosen: both upload + URL)

- **Upload:** presigned direct-to-R2 so large files never touch the control plane.
- **YouTube URL:** server-side `yt-dlp` download. Carries ToS / IP-ban risk at scale — needs proxy / pot-provider hardening before heavy traffic. Re-add the URL intake form (it was removed from `/shorts` in a recent commit).

## Rollout

1. **Extract** — cutter into a standalone service; wrap `cut_video()` as a Modal GPU function; wire R2 in/out. Prove *video in → clips out*, no UI.
2. **Shell** — Supabase auth + credits ledger + upload/URL intake + job/progress/download UI.
3. **Money** — Dodo/Polar checkout → credit top-ups via webhook; free-trial credits.
4. **Landing + launch.**

## Open decisions (defer, don't block)

- YouTube-download hardening (proxy / pot-provider).
- Free-trial credit amount.
- Pricing tiers / credit pack sizes.
