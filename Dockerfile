# Multi-stage build for a small runtime image.
FROM python:3.13-slim AS base

WORKDIR /app

# ffmpeg: used by the shorts cutter (clip extraction/encoding) and app/keyframes.py.
# postgresql-client: app/backup.py shells out to pg_dump for the nightly NAS
# snapshot. pg_dump REFUSES to dump a server newer than itself, so this has to
# stay >= the server's major version (pg16, see docker-compose.yml).
#
# Unversioned on purpose: python:3.13-slim is Debian trixie, which ships
# postgresql-client-17 and has no -16 package at all, so pinning the server's
# exact major failed the build outright. The meta-package tracks whatever the
# base image's Debian offers, which has only ever moved forward — and the RUN
# below fails the build if it ever doesn't, rather than letting a too-old
# pg_dump ship and break the nightly backup at 00:00.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pg_dump --version \
    && [ "$(pg_dump --version | sed -E 's/.* ([0-9]+).*/\1/')" -ge 16 ]

# NOTE: Deno was installed here solely as the JS runtime for yt-dlp's "n"-challenge
# solver in the retired YouTube-URL shorts download flow. Removed with that flow.
# To revive it, restore the Deno install step and the yt-dlp/bgutil deps below.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Local shorts cutter ML stack (CPU-only — see docs Phase A). Install torch from
# the CPU wheel index so the image doesn't pull ~2 GB of unused CUDA libs, then
# the remaining ML deps. ffmpeg is already installed above.
COPY requirements-ml.txt .
RUN pip install --no-cache-dir torch==2.12.1 torchvision==0.27.1 torchaudio==2.11.0 \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements-ml.txt

COPY app ./app

RUN mkdir -p /app/storage/keyframes /app/shorts_cache /app/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5.0)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
