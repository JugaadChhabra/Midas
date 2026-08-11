# Multi-stage build for a small runtime image.
FROM python:3.13-slim AS base

WORKDIR /app

# ffmpeg: used by the shorts cutter (clip extraction/encoding) and app/keyframes.py.
#
# postgresql-client-16: app/backup.py shells out to pg_dump for the nightly NAS
# snapshot, and app/provision.py shells out to psql to restore it. The major
# version must EQUAL the server's (pg16, see docker-compose.yml) — not merely be
# >= it, which is the easy mistake:
#
#   older than the server -> pg_dump refuses to run. Loud, harmless.
#   NEWER than the server -> pg_dump runs fine and writes a dump the server
#     cannot replay. pg_dump 18 emits `SET transaction_timeout = 0`, a pg17
#     parameter, and the restore dies on line 13. Nothing fails until the day
#     someone actually needs the backup.
#
# From apt.postgresql.org, because Debian trixie carries only -17: pinning to
# the server's major is the requirement, so the repo that has every major is the
# right answer rather than taking whatever the base image happens to ship.
ARG PG_MAJOR=16
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    "postgresql-client-${PG_MAJOR}" \
    && rm -rf /var/lib/apt/lists/* \
    && pg_dump --version && psql --version \
    && [ "$(pg_dump --version | sed -E 's/.* ([0-9]+).*/\1/')" = "${PG_MAJOR}" ] \
    && [ "$(psql --version | sed -E 's/.* ([0-9]+).*/\1/')" = "${PG_MAJOR}" ]

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
