# Multi-stage build for a small runtime image.
FROM python:3.13-slim AS base

WORKDIR /app

# ffmpeg is used by app/keyframes.py for frame extraction.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Local shorts cutter ML stack (CPU-only — see docs Phase A). Install torch from
# the CPU wheel index so the image doesn't pull ~2 GB of unused CUDA libs, then
# the remaining ML deps. ffmpeg is already installed above.
COPY requirements-ml.txt .
RUN pip install --no-cache-dir torch==2.12.1 torchvision==0.27.1 torchaudio==2.11.0 \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements-ml.txt

# yt-dlp chases YouTube's server-side changes (roughly weekly), so the version
# resolved into the cached pip layer above freezes stale within days and YouTube
# starts lying "this video is not available". Reinstall the nightly build in its
# own late layer (after the expensive torch/ML layers, so those stay cached) that
# CI busts on EVERY build via YTDLP_CACHEBUST — a unique run id, including the
# weekly scheduled rebuild — so :latest always ships a current extractor.
ARG YTDLP_CACHEBUST=dev
RUN pip install --no-cache-dir -U --pre "yt-dlp[default]"

COPY app ./app
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

RUN mkdir -p /app/storage/keyframes /app/shorts_cache /app/logs

EXPOSE 8000

# start-period covers the entrypoint's boot-time yt-dlp refresh (a pip install +
# network round-trip runs before uvicorn binds :8000) so the container isn't
# marked unhealthy while it's still legitimately starting.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5.0)" || exit 1

# Entrypoint refreshes yt-dlp, then exec's this CMD (uvicorn).
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
